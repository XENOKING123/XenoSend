"""Background themes for SendPP.

The original look was a single flat slate palette hard-coded in ``main.kv``.  Colours now come
from :class:`ThemeManager`, an observable object exposed to KV as ``app.theme``, so a theme
change repaints the whole UI live.  The brand accent (orange) and the status colours are the
same in every theme; themes only change the background / surface family.

The page background is a vertical gradient rendered from a small texture, which looks much
smoother than a flat fill and costs one textured rectangle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from kivy.core.window import Window
from kivy.event import EventDispatcher
from kivy.graphics.texture import Texture
from kivy.properties import ColorProperty, ObjectProperty, StringProperty
from kivy.utils import get_color_from_hex


@dataclass(frozen=True)
class Palette:
    key: str
    title: str  # Portuguese catalog key of the display name (see app/i18n/locales)
    bg_top: str
    bg_bottom: str
    header: str
    footer: str
    # Header bar gradient (top -> bottom). For most palettes this is the same colour
    # twice, so the header renders as a flat fill identical to the old look; "xeno"
    # uses a real navy -> teal gradient to match the brand's banner treatment.
    header_gradient_top: str
    header_gradient_bottom: str
    surface: str
    surface_active: str
    surface_border: str
    input: str
    control: str
    control_hover: str
    control_pressed: str
    text_primary: str
    text_muted: str


# Shared by every theme (brand + status colours from the original design).
ACCENT = "#F38B1A"
ACCENT_HOVER = "#FF9D33"
ACCENT_PRESSED = "#D97712"
BUTTON_TEXT = "#111318"
SUCCESS = "#79C98D"
DANGER = "#E47C73"

PALETTES: Dict[str, Palette] = {
    p.key: p
    for p in (
        Palette(
            key="midnight", title="Meia-noite",
            bg_top="#16203D", bg_bottom="#090D1B",
            header="#0C1124", footer="#070A15",
            header_gradient_top="#0C1124", header_gradient_bottom="#0C1124",
            surface="#18213C", surface_active="#1E2A4D", surface_border="#2C3960",
            input="#0F1630", control="#232E50", control_hover="#2D3A63", control_pressed="#384878",
            text_primary="#F2F5FF", text_muted="#8E9AC0",
        ),
        Palette(
            key="graphite", title="Grafite",
            bg_top="#1B1E23", bg_bottom="#0E1013",
            header="#111317", footer="#0A0B0E",
            header_gradient_top="#111317", header_gradient_bottom="#111317",
            surface="#1F2227", surface_active="#262A31", surface_border="#31363E",
            input="#15171B", control="#2B2F36", control_hover="#353A43", control_pressed="#3F4550",
            text_primary="#F4F6F8", text_muted="#8D939C",
        ),
        Palette(
            key="ocean", title="Oceano",
            bg_top="#0F3340", bg_bottom="#061519",
            header="#09202A", footer="#050F13",
            header_gradient_top="#09202A", header_gradient_bottom="#09202A",
            surface="#113743", surface_active="#16444F", surface_border="#215562",
            input="#0A2630", control="#1B4856", control_hover="#245B6C", control_pressed="#2D6E82",
            text_primary="#EAFBFF", text_muted="#80B3C0",
        ),
        Palette(
            key="amoled", title="AMOLED",
            bg_top="#000000", bg_bottom="#000000",
            header="#000000", footer="#000000",
            header_gradient_top="#000000", header_gradient_bottom="#000000",
            surface="#0D0D10", surface_active="#15151A", surface_border="#27272E",
            input="#07070A", control="#1B1B21", control_hover="#24242B", control_pressed="#2E2E37",
            text_primary="#F4F6F8", text_muted="#7E828A",
        ),
        Palette(
            key="classic", title="Clássico",
            bg_top="#1B2129", bg_bottom="#1B2129",
            header="#15181D", footer="#121419",
            header_gradient_top="#15181D", header_gradient_bottom="#15181D",
            surface="#191C21", surface_active="#1E232B", surface_border="#2B3038",
            input="#1B2129", control="#252A32", control_hover="#2D3440", control_pressed="#343D4A",
            text_primary="#F4F6F8", text_muted="#858D98",
        ),
        Palette(
            key="xeno", title="Xeno",
            # Deep navy/near-black with a teal-tinted top, matching the Xeno brand's
            # navy -> teal gradient treatment (see app/assets/xeno/brand).
            bg_top="#15283A", bg_bottom="#05080D",
            header="#070C14", footer="#04070B",
            header_gradient_top="#0A1522", header_gradient_bottom="#1F5E78",
            surface="#101B26", surface_active="#16222F", surface_border="#2A4556",
            input="#0A121B", control="#16222F", control_hover="#1E303F", control_pressed="#27404F",
            text_primary="#F0F7FF", text_muted="#7D93A6",
        ),
    )
}

DEFAULT_THEME = "xeno"


def gradient_texture(top: List[float], bottom: List[float], steps: int = 192) -> Texture:
    """A 1 x ``steps`` vertical gradient texture (Kivy textures are bottom-up)."""
    texture = Texture.create(size=(1, steps), colorfmt="rgba")
    data = bytearray()
    for row in range(steps):
        t = row / (steps - 1)  # 0 = bottom edge, 1 = top edge
        data.extend(
            int(round((bottom[i] + (top[i] - bottom[i]) * t) * 255)) for i in range(4)
        )
    texture.blit_buffer(bytes(data), colorfmt="rgba", bufferfmt="ubyte")
    texture.mag_filter = "linear"
    texture.min_filter = "linear"
    return texture


class ThemeManager(EventDispatcher):
    """Observable colour set; every attribute below is bindable from KV as ``app.theme.<name>``."""

    key = StringProperty(DEFAULT_THEME)
    background = ColorProperty()
    bg_top = ColorProperty()
    bg_bottom = ColorProperty()
    bg_texture = ObjectProperty(None, allownone=True)
    header = ColorProperty()
    header_gradient_top = ColorProperty()
    header_gradient_bottom = ColorProperty()
    header_texture = ObjectProperty(None, allownone=True)
    footer = ColorProperty()
    surface = ColorProperty()
    surface_active = ColorProperty()
    surface_border = ColorProperty()
    input = ColorProperty()
    control = ColorProperty()
    control_hover = ColorProperty()
    control_pressed = ColorProperty()
    text_primary = ColorProperty()
    text_muted = ColorProperty()
    accent = ColorProperty(get_color_from_hex(ACCENT))
    accent_hover = ColorProperty(get_color_from_hex(ACCENT_HOVER))
    accent_pressed = ColorProperty(get_color_from_hex(ACCENT_PRESSED))
    button_text = ColorProperty(get_color_from_hex(BUTTON_TEXT))
    success = ColorProperty(get_color_from_hex(SUCCESS))
    danger = ColorProperty(get_color_from_hex(DANGER))

    def __init__(self, key: str = DEFAULT_THEME, **kwargs) -> None:
        super().__init__(**kwargs)
        self.apply(key)

    @property
    def palettes(self) -> Tuple[Palette, ...]:
        return tuple(PALETTES.values())

    def apply(self, key: str) -> bool:
        palette = PALETTES.get(key)
        if palette is None:
            return False
        top = get_color_from_hex(palette.bg_top)
        bottom = get_color_from_hex(palette.bg_bottom)
        self.key = palette.key
        self.bg_top, self.bg_bottom, self.background = top, bottom, bottom
        self.header = get_color_from_hex(palette.header)
        htop = get_color_from_hex(palette.header_gradient_top)
        hbottom = get_color_from_hex(palette.header_gradient_bottom)
        self.header_gradient_top, self.header_gradient_bottom = htop, hbottom
        self.header_texture = gradient_texture(list(htop), list(hbottom))
        self.footer = get_color_from_hex(palette.footer)
        self.surface = get_color_from_hex(palette.surface)
        self.surface_active = get_color_from_hex(palette.surface_active)
        self.surface_border = get_color_from_hex(palette.surface_border)
        self.input = get_color_from_hex(palette.input)
        self.control = get_color_from_hex(palette.control)
        self.control_hover = get_color_from_hex(palette.control_hover)
        self.control_pressed = get_color_from_hex(palette.control_pressed)
        self.text_primary = get_color_from_hex(palette.text_primary)
        self.text_muted = get_color_from_hex(palette.text_muted)
        self.bg_texture = gradient_texture(list(top), list(bottom))
        Window.clearcolor = bottom
        return True
