"""Right-to-left text support for Kivy builds whose SDL_ttf has no shaping or bidi.

The SDL2 text provider bundled with Kivy here draws Arabic as isolated, left-to-right
letters.  Two things are therefore done in Python before the text reaches a Label:

1. **Shaping** - ``arabic_reshaper`` rewrites letters to their contextual presentation
   forms (initial / medial / final / ligature), which the bundled font contains.
2. **Reordering** - a compact implementation of the Unicode Bidirectional Algorithm
   (UAX #9, rules W1-W7, N1-N2, I1-I2, L1-L2, L4) converts the logical string into the
   *visual* order so that a plain left-to-right renderer shows it correctly.

Kivy markup (``[color=#fff]PKG[/color]``) is treated as an indivisible token so tags are
never reversed or split.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List

try:  # pure-Python, MIT licensed; absence degrades to unshaped text rather than failing
    from arabic_reshaper import ArabicReshaper as _ArabicReshaper

    # The bundled Tajawal font has the base letters (which draw as isolated forms) and the
    # initial/medial/final presentation forms, but not the isolated presentation forms.
    _reshaper = _ArabicReshaper(configuration={"use_unshaped_instead_of_isolated": True})
except Exception:  # pragma: no cover - exercised only on broken installs
    _reshaper = None

_MIRROR = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<", "«": "»", "»": "«"}

_PUA_BASE = 0xE000
_R_STAND_INS = [chr(code) for code in range(0x05D0, 0x05EB)]  # Hebrew letters: strong R, untouched by the reshaper
_TAG = (r"b|i|u|s|font|size|color|ref|anchor|sub|sup|font_context|font_family|font_features|"
        r"text_language")
# A balanced pair `[tag=..]inner[/tag]` or a lone tag.
_MARKUP = re.compile(r"\[(?P<tag>%s)(?P<arg>=[^\]]*)?\](?P<inner>.*?)\[/(?P=tag)\]|\[/?(?:%s)(?:=[^\]]*)?\]" % (_TAG, _TAG),
                     re.DOTALL)
_RTL_CHARS = re.compile("[֐-ࣿיִ-﷿ﹰ-﻿]")


def contains_rtl(text: str) -> bool:
    return bool(_RTL_CHARS.search(text))


def _classes(text: str) -> List[str]:
    return [unicodedata.bidirectional(ch) or "ON" for ch in text]


def _levels(text: str, base: int) -> List[int]:
    """Resolve embedding levels for a single paragraph with the given base level."""
    n = len(text)
    types = _classes(text)
    sor = "R" if base % 2 else "L"

    # W1: non-spacing marks take the type of the previous character.
    prev = sor
    for i, t in enumerate(types):
        if t == "NSM":
            types[i] = prev
        else:
            prev = t
    # W2: European numbers after Arabic letters become Arabic numbers.  W3: AL -> R.
    last_strong = sor
    for i, t in enumerate(types):
        if t in ("L", "R", "AL"):
            last_strong = t
        elif t == "EN" and last_strong == "AL":
            types[i] = "AN"
    types = ["R" if t == "AL" else t for t in types]
    # W4: a single separator between two numbers of the same kind joins them.
    for i in range(1, n - 1):
        if types[i] == "ES" and types[i - 1] == "EN" and types[i + 1] == "EN":
            types[i] = "EN"
        elif types[i] == "CS" and types[i - 1] == types[i + 1] and types[i - 1] in ("EN", "AN"):
            types[i] = types[i - 1]
    # W5: a run of European terminators next to a European number becomes European numbers.
    i = 0
    while i < n:
        if types[i] == "ET":
            j = i
            while j < n and types[j] == "ET":
                j += 1
            if (i > 0 and types[i - 1] == "EN") or (j < n and types[j] == "EN"):
                for k in range(i, j):
                    types[k] = "EN"
            i = j
        else:
            i += 1
    # W6: leftover separators and terminators are neutral.
    types = ["ON" if t in ("ES", "ET", "CS") else t for t in types]
    # W7: European numbers following strong L are L.
    last_strong = sor
    for i, t in enumerate(types):
        if t in ("L", "R"):
            last_strong = t
        elif t == "EN" and last_strong == "L":
            types[i] = "L"
    embed = "R" if base % 2 else "L"

    def strong_dir(t: str) -> str:
        return "R" if t in ("R", "EN", "AN") else "L"

    # N0: paired brackets take the direction of what they enclose (UAX #9, simplified).
    openers = {"(": ")", "[": "]", "{": "}"}
    stack: List[tuple] = []
    pairs: List[tuple] = []
    for i, ch in enumerate(text):
        if types[i] != "ON":
            continue
        if ch in openers:
            stack.append((i, openers[ch]))
        elif ch in (")", "]", "}"):
            for depth in range(len(stack) - 1, -1, -1):
                if stack[depth][1] == ch:
                    pairs.append((stack[depth][0], i))
                    del stack[depth:]
                    break
    for start, end in sorted(pairs):
        inside = {strong_dir(types[k]) for k in range(start + 1, end) if types[k] in ("L", "R", "EN", "AN")}
        if not inside:
            continue
        if embed in inside:
            direction = embed
        else:
            preceding = sor
            for k in range(start - 1, -1, -1):
                if types[k] in ("L", "R", "EN", "AN"):
                    preceding = strong_dir(types[k])
                    break
            direction = preceding if preceding != embed else embed
        types[start] = types[end] = direction

    # N1/N2: neutrals take the direction of their surroundings, else the embedding direction.

    i = 0
    while i < n:
        if types[i] in ("WS", "ON", "B", "S", "BN", "LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"):
            j = i
            while j < n and types[j] in ("WS", "ON", "B", "S", "BN", "LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI",
                                         "FSI", "PDI"):
                j += 1
            before = strong_dir(types[i - 1]) if i > 0 else sor
            after = strong_dir(types[j]) if j < n else sor
            resolved = before if before == after else embed
            for k in range(i, j):
                types[k] = resolved
            i = j
        else:
            i += 1
    # I1/I2: implicit levels.
    levels: List[int] = []
    for t in types:
        if base % 2 == 0:
            levels.append(base if t == "L" else base + 1 if t == "R" else base + 2)
        else:
            levels.append(base + 1 if t in ("L", "EN", "AN") else base)
    # L1: trailing whitespace goes back to the paragraph level.
    orig = [unicodedata.bidirectional(ch) for ch in text]
    k = n - 1
    while k >= 0 and orig[k] in ("WS", "B", "S"):
        levels[k] = base
        k -= 1
    return levels


def reorder(text: str, base_rtl: bool = True) -> str:
    """Return ``text`` in visual order (UAX #9 L2 + L4 mirroring)."""
    if not text:
        return text
    base = 1 if base_rtl else 0
    levels = _levels(text, base)
    chars = list(text)
    for i, ch in enumerate(chars):
        if levels[i] % 2 and ch in _MIRROR:
            chars[i] = _MIRROR[ch]
    top = max(levels)
    low_odd = min((lv for lv in levels if lv % 2), default=top + 1)
    for level in range(top, low_odd - 1, -1):
        i = 0
        while i < len(chars):
            if levels[i] >= level:
                j = i
                while j < len(chars) and levels[j] >= level:
                    j += 1
                chars[i:j] = reversed(chars[i:j])
                levels[i:j] = reversed(levels[i:j])
                i = j
            else:
                i += 1
    return "".join(chars)


def _shape_plain(text: str, base_rtl: bool) -> str:
    if _reshaper is not None and contains_rtl(text):
        text = _reshaper.reshape(text)
    return reorder(text, base_rtl=base_rtl)


def to_visual(text: str, base_rtl: bool = True) -> str:
    """Shape and reorder ``text`` for display; markup tags are preserved verbatim."""
    if not text or not (base_rtl or contains_rtl(text)):
        return text
    # Each markup block becomes one stand-in character: a Hebrew letter (strong R) when the block
    # holds Arabic text, otherwise a private-use character (strong L).  The block's own text is
    # already in visual order, so it must travel through the reordering as an atomic unit.
    blocks: Dict[str, str] = {}
    r_stand_ins = iter(_R_STAND_INS)

    def stash(match: "re.Match[str]") -> str:
        inner_rtl = False
        if match.group("tag"):
            raw_inner = match.group("inner")
            inner_rtl = contains_rtl(raw_inner)
            inner = _shape_plain(raw_inner, base_rtl) if inner_rtl else raw_inner
            piece = "[%s%s]%s[/%s]" % (match.group("tag"), match.group("arg") or "", inner, match.group("tag"))
        else:
            piece = match.group(0)
        stand_in = next(r_stand_ins, None) if inner_rtl else None
        if stand_in is None:
            stand_in = chr(_PUA_BASE + len(blocks))
        blocks[stand_in] = piece
        return stand_in

    protected = _MARKUP.sub(stash, text)
    visual = _shape_plain(protected, base_rtl)
    if not blocks:
        return visual
    return "".join(blocks.get(ch, ch) for ch in visual)
