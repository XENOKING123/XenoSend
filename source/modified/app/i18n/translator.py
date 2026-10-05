"""Runtime translation layer for SendPP.

The application was authored in Brazilian Portuguese, so Portuguese strings are the
*lookup keys*: every catalog maps ``source text -> translated text``.  A key that is
missing from a catalog silently falls back to the source text, which means a partially
translated catalog can never break the UI.

Two ways to use it:

* KV (live, rebinds automatically when the language changes)::

      MDLabel:
          text: app.tr._("Conexão PS5")
          # dynamic text coming from Python is translated at display time as well:
          text: app.tr._(root.status_text)

* Python::

      tr("Nenhum payload disponível.")              # translate + shape for display
      translator.translate("Enviando {name}...")    # logical text, no shaping

Messages that are rendered *before* they reach the UI (``f"Preparando • {label}"``
produced deep inside a controller) are matched against the catalog's ``{placeholder}``
templates by :meth:`Translator.translate`; captured values are translated recursively, so
``"Falha • {message}"`` also translates the ``message`` it wraps.

Display shaping (Arabic joining + bidi reordering, see :mod:`app.i18n.rtl`) is applied
last and only for right-to-left languages.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from kivy.event import Observable

from app.i18n import rtl

SOURCE_LANGUAGE = "pt"

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_TRAILING_DOTS = re.compile(r"[.…]+$")
# Progress lines are "<message> • <n>%".  They are split off *before* template matching: a template such
# as "Baixando {name}" would otherwise swallow the " • 12%" suffix into {name} and misorder the sentence.
_PROGRESS_KEY = "{message} • {percent}%"
_PROGRESS_SUFFIX = re.compile(r"^(?P<message>.*\S) • (?P<percent>\d{1,3})%$", re.DOTALL)


@dataclass(frozen=True)
class Language:
    """A selectable UI language."""

    code: str
    native_name: str
    english_name: str
    rtl: bool = False
    # Key of a font family bundled for scripts that Roboto cannot draw (see fonts.py).
    script_font: Optional[str] = None


LANGUAGES: Tuple[Language, ...] = (
    Language("en", "English", "English"),
    Language("pt", "Português (Brasil)", "Portuguese (Brazil)"),
    Language("ar", "العربية", "Arabic", rtl=True, script_font="arabic"),
    Language("es", "Español", "Spanish"),
    Language("fr", "Français", "French"),
    Language("de", "Deutsch", "German"),
    Language("tr", "Türkçe", "Turkish"),
    Language("ru", "Русский", "Russian"),
)

_BY_CODE: Dict[str, Language] = {lang.code: lang for lang in LANGUAGES}


def language_for(code: str) -> Language:
    """Return the Language for ``code``; unknown codes resolve to the source language."""
    return _BY_CODE.get(code, _BY_CODE[SOURCE_LANGUAGE])


def is_supported(code: str) -> bool:
    return code in _BY_CODE


def _compile_template(key: str) -> Optional[Tuple[re.Pattern, int]]:
    """Turn ``"Enviando {name}..."`` into (anchored regex with named groups, literal length)."""
    matches = list(_PLACEHOLDER.finditer(key))
    if not matches:
        return None
    pieces: List[str] = []
    cursor = 0
    seen = set()
    literal = 0
    for match in matches:
        chunk = key[cursor:match.start()]
        literal += len(chunk)
        pieces.append(re.escape(chunk))
        name = match.group(1)
        if name in seen:
            pieces.append(f"(?P={name})")
        else:
            seen.add(name)
            pieces.append(f"(?P<{name}>.+?)")
        cursor = match.end()
    tail = key[cursor:]
    literal += len(tail)
    pieces.append(re.escape(tail))
    return re.compile("^" + "".join(pieces) + "$", re.DOTALL), literal


def expand_catalog(catalog: Mapping[str, str]) -> Dict[str, str]:
    """Add dot-stripped aliases.

    Progress messages are shown as ``"<message> • 45%"`` with the message's trailing dots
    removed, so ``"Baixando payload..."`` must also be resolvable as ``"Baixando payload"``.
    """
    expanded = dict(catalog)
    for key, value in catalog.items():
        bare_key = _TRAILING_DOTS.sub("", key)
        if bare_key and bare_key != key:
            bare_value = _TRAILING_DOTS.sub("", value)
            # "aguarde ..." leaves a trailing space once the dots are gone: accept both forms.
            for alias in (bare_key, bare_key.strip()):
                if alias and alias not in expanded:
                    expanded[alias] = bare_value.strip() if alias == bare_key.strip() else bare_value
    return expanded


class Translator(Observable):
    """Observable translation table.

    Deriving from :class:`kivy.event.Observable` lets the KV engine bind to *any*
    attribute of the translator (``app.tr._``, ``app.tr.start`` ...); every observer is
    re-evaluated by :meth:`set_language`.
    """

    def __init__(self, catalogs: Mapping[str, Mapping[str, str]], language: str = SOURCE_LANGUAGE) -> None:
        super().__init__()
        self._catalogs: Dict[str, Dict[str, str]] = {code: expand_catalog(cat) for code, cat in catalogs.items()}
        self._observers: List[Tuple[Callable, tuple, dict]] = []
        self._listeners: List[Callable[[str], None]] = []
        self._templates: Dict[str, List[Tuple[re.Pattern, str]]] = {}
        self._language = language if language in _BY_CODE else SOURCE_LANGUAGE

    # ----- state ---------------------------------------------------------------
    @property
    def language(self) -> str:
        return self._language

    @property
    def info(self) -> Language:
        return language_for(self._language)

    @property
    def rtl(self) -> bool:
        return self.info.rtl

    @property
    def start(self) -> str:
        """Horizontal alignment of the beginning of a line of text."""
        return "right" if self.rtl else "left"

    @property
    def end(self) -> str:
        """Horizontal alignment of the end of a line of text."""
        return "left" if self.rtl else "right"

    # ----- lookup --------------------------------------------------------------
    def _catalog(self) -> Mapping[str, str]:
        return self._catalogs.get(self._language, {})

    def translate(self, text: str, _depth: int = 0) -> str:
        """Return the *logical* (unshaped) translation of ``text``.

        Resolution order: exact key, then ``{placeholder}`` templates, then the source text.
        """
        if not text or self._language == SOURCE_LANGUAGE:
            return text
        catalog = self._catalog()
        exact = catalog.get(text) or catalog.get(text.strip())
        if exact:
            return exact
        if _depth < 3:
            progress = _PROGRESS_SUFFIX.match(text)
            if progress and catalog.get(_PROGRESS_KEY):
                try:
                    return catalog[_PROGRESS_KEY].format(
                        message=self.translate(progress.group("message"), _depth + 1),
                        percent=progress.group("percent"),
                    )
                except (KeyError, IndexError, ValueError):
                    pass
            for pattern, target in self._template_index():
                match = pattern.match(text)
                if match:
                    values = {k: self.translate(v, _depth + 1) for k, v in match.groupdict().items()}
                    try:
                        return target.format(**values)
                    except (KeyError, IndexError, ValueError):
                        continue
        return text

    def shape(self, text: str) -> str:
        """Prepare logical text for the (shaping-less) renderer; identity for LTR languages."""
        if self.rtl:
            return rtl.to_visual(text, base_rtl=True)
        return text

    def _(self, text: str) -> str:
        """Translate and shape ``text``.  This is the hook bound from KV (``app.tr._(...)``)."""
        return self.shape(self.translate(text))

    def __call__(self, text: str, **fmt: object) -> str:
        """Translate, format and shape: ``tr("Preparando • {label}", label=x)``."""
        translated = self.translate(text)
        if fmt:
            try:
                translated = translated.format(**fmt)
            except (KeyError, IndexError, ValueError):
                try:
                    translated = text.format(**fmt)
                except (KeyError, IndexError, ValueError):
                    pass
        return self.shape(translated)

    def _template_index(self) -> List[Tuple[re.Pattern, str]]:
        cached = self._templates.get(self._language)
        if cached is None:
            ranked: List[Tuple[int, re.Pattern, str]] = []
            for key, target in self._catalog().items():
                compiled = _compile_template(key)
                if compiled is not None and target:
                    ranked.append((compiled[1], compiled[0], target))
            # More literal text first, so the most specific template wins.
            ranked.sort(key=lambda item: -item[0])
            cached = [(pattern, target) for _literal, pattern, target in ranked]
            self._templates[self._language] = cached
        return cached

    # ----- change notification ---------------------------------------------------
    def fbind(self, name, func, *largs, **kwargs):  # noqa: D401 - Kivy Observable protocol
        self._observers.append((func, largs, kwargs))
        return len(self._observers)

    def funbind(self, name, func, *largs, **kwargs):
        key = (func, largs, kwargs)
        if key in self._observers:
            self._observers.remove(key)

    def unbind_uid(self, name, uid):
        return None

    def add_listener(self, callback: Callable[[str], None]) -> None:
        """Python-side hook, called with the new language code after each switch."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def set_language(self, code: str) -> bool:
        """Switch language; returns False when ``code`` is unknown."""
        if code not in _BY_CODE:
            return False
        if code == self._language:
            return True
        self._language = code
        for func, largs, kwargs in list(self._observers):
            func(*largs, None, None)
        for callback in list(self._listeners):
            callback(code)
        return True
