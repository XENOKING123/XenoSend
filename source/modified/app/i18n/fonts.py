"""Font handling for scripts the stock Roboto cannot draw (Arabic).

KivyMD registers the ``Roboto*`` families at import time and every label refers to them by
*name*; Kivy resolves the file only when a label's texture is rendered.  Switching to a
right-to-left language therefore re-points those names at Tajawal (Latin + Arabic, SIL OFL),
and switching back restores the original registrations.  A separate ``Tajawal`` family is
always registered so the language picker can print "العربية" while another language is active.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

from kivy.core.text import LabelBase
from kivy.uix.label import Label

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
ARABIC_FAMILY = "Tajawal"
# Always the real Roboto, whatever the "Roboto" name currently points at.  The language picker needs
# it because Tajawal (active in Arabic mode) has no Cyrillic glyphs for "Русский".
LATIN_FAMILY = "SendppRoboto"

_ROBOTO_FAMILIES = ("Roboto", "RobotoThin", "RobotoLight", "RobotoMedium", "RobotoBlack")

_original: Dict[str, Tuple[str, ...]] = {}
_active_script: Optional[str] = None


def _font(name: str) -> str:
    return str(FONT_DIR / name)


def available() -> bool:
    return all((FONT_DIR / name).is_file() for name in ("Tajawal-Regular.ttf", "Tajawal-Medium.ttf", "Tajawal-Bold.ttf"))


def register_script_families() -> None:
    """Register the standalone Tajawal and stock-Roboto families (idempotent)."""
    from kivymd import fonts_path

    LabelBase.register(
        name=LATIN_FAMILY,
        fn_regular=fonts_path + "Roboto-Regular.ttf",
        fn_bold=fonts_path + "Roboto-Bold.ttf",
    )
    if not available():
        return
    LabelBase.register(
        name=ARABIC_FAMILY,
        fn_regular=_font("Tajawal-Regular.ttf"),
        fn_bold=_font("Tajawal-Bold.ttf"),
    )


def apply_script_font(script_font: Optional[str]) -> bool:
    """Point the Roboto family names at the font for ``script_font`` (None restores Roboto).

    Returns True when the active mapping changed (callers then refresh visible labels).
    """
    global _active_script
    if script_font == _active_script:
        return False
    if not _original:
        for name in _ROBOTO_FAMILIES:
            if name in LabelBase._fonts:
                _original[name] = LabelBase._fonts[name]
    if script_font == "arabic" and available():
        regular, medium, bold = _font("Tajawal-Regular.ttf"), _font("Tajawal-Medium.ttf"), _font("Tajawal-Bold.ttf")
        # tuple order used by Kivy: (regular, italic, bold, bolditalic)
        LabelBase._fonts["Roboto"] = (regular, regular, bold, bold)
        LabelBase._fonts["RobotoThin"] = (regular, regular, regular, regular)
        LabelBase._fonts["RobotoLight"] = (regular, regular, regular, regular)
        LabelBase._fonts["RobotoMedium"] = (medium, medium, bold, bold)
        LabelBase._fonts["RobotoBlack"] = (bold, bold, bold, bold)
        _active_script = "arabic"
    else:
        for name, files in _original.items():
            LabelBase._fonts[name] = files
        _active_script = None
    return True


def refresh_text_widgets(root) -> None:
    """Re-render every Label below ``root`` so a font swap becomes visible immediately."""
    if root is None:
        return
    # The Window itself is not a widget: walk each of its top-level children (screen, open modals).
    tops = [root] if hasattr(root, "walk") else list(getattr(root, "children", ()))
    for top in tops:
        for widget in top.walk(restrict=False):
            if isinstance(widget, Label):
                try:
                    widget.texture_update()
                except Exception:  # a widget mid-teardown must not break the refresh
                    pass
