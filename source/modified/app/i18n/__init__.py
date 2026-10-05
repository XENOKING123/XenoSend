"""SendPP internationalisation.  Portuguese is the source language; see :mod:`app.i18n.translator`."""
from __future__ import annotations

import os
from typing import Optional

from app.i18n import fonts
from app.i18n.locales import load_catalogs
from app.i18n.translator import (
    LANGUAGES,
    SOURCE_LANGUAGE,
    Language,
    Translator,
    is_supported,
    language_for,
)

__all__ = [
    "LANGUAGES",
    "SOURCE_LANGUAGE",
    "Language",
    "Translator",
    "detect_system_language",
    "fonts",
    "get_translator",
    "is_supported",
    "language_for",
    "set_language",
    "toast",
    "tr",
]

_translator: Optional[Translator] = None


def get_translator() -> Translator:
    """Return the process-wide translator (created on first use, in the source language)."""
    global _translator
    if _translator is None:
        _translator = Translator(load_catalogs(), SOURCE_LANGUAGE)
        fonts.register_script_families()
    return _translator


def tr(text: str, **fmt: object) -> str:
    """Translate, format and shape ``text`` for display in the active language."""
    return get_translator()(text, **fmt)


def set_language(code: str) -> bool:
    """Switch the UI language.  Returns True when the text font mapping changed too.

    The font mapping is applied *before* observers re-render, so labels are drawn with the
    right glyphs the first time.
    """
    translator = get_translator()
    changed = fonts.apply_script_font(language_for(code).script_font)
    translator.set_language(code)
    return changed


def toast(text: str, *args, **kwargs):
    """Drop-in replacement for ``kivymd.toast.toast`` that translates its message."""
    from kivymd.toast import toast as _toast

    translator = get_translator()
    return _toast(translator.shape(translator.translate(text)), *args, **kwargs)


def _candidate_locale_codes():
    forced = os.environ.get("SENDPP_FORCE_LANG")
    if forced:
        yield forced
    try:  # Android
        from jnius import autoclass

        yield str(autoclass("java.util.Locale").getDefault().getLanguage())
    except Exception:
        pass
    try:  # Windows
        import ctypes

        buf = ctypes.create_unicode_buffer(85)
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
            yield buf.value
    except Exception:
        pass
    try:
        import locale

        value = locale.getlocale()[0]
        if value:
            yield value
    except Exception:
        pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            yield value


def detect_system_language(default: str = "en") -> str:
    """Pick the first supported language from the system locale, else ``default``."""
    for raw in _candidate_locale_codes():
        code = raw.replace("_", "-").split("-")[0].split(".")[0].lower()
        if is_supported(code):
            return code
    return default
