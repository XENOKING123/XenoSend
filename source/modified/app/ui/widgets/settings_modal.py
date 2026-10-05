"""Settings dialog: interface language and background theme.

Layout and styling live in ``main.kv`` (``<SettingsModal>`` / ``<SettingsOptionItem>``); this
module only builds the option rows and routes clicks to the running app.
"""
from __future__ import annotations

from kivy.properties import BooleanProperty, ListProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivymd.app import MDApp

from app.i18n import LANGUAGES, fonts, get_translator
from app.i18n import rtl as rtl_support
from app.ui.theme import PALETTES


class SettingsOptionItem(ButtonBehavior, BoxLayout):
    """One selectable row (a language or a theme)."""

    key = StringProperty("")
    text = StringProperty("")
    # Theme names are catalog keys and are translated live; language names are shown verbatim.
    translate = BooleanProperty(False)
    selected = BooleanProperty(False)
    font_family = StringProperty("")
    # Theme preview colours (alpha 0 hides the swatch on language rows).
    swatch_bg = ListProperty([0, 0, 0, 0])
    swatch_surface = ListProperty([0, 0, 0, 0])


class SettingsModal(ModalView):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._app = MDApp.get_running_app()
        self._language_rows = []
        self._theme_rows = []
        self._build_language_rows()
        self._build_theme_rows()

    # -- rows -----------------------------------------------------------------------------
    def _build_language_rows(self) -> None:
        container = self.ids.language_list
        container.clear_widgets()
        current = get_translator().language
        for language in LANGUAGES:
            label = language.native_name
            family = fonts.LATIN_FAMILY
            if language.rtl:
                # The renderer here cannot join/reorder Arabic itself, and Roboto has no Arabic glyphs.
                label = rtl_support.to_visual(label, base_rtl=True)
                family = fonts.ARABIC_FAMILY
            row = SettingsOptionItem(
                key=language.code, text=label, selected=language.code == current, font_family=family
            )
            row.bind(on_release=self._on_language)
            container.add_widget(row)
            self._language_rows.append(row)

    def _build_theme_rows(self) -> None:
        container = self.ids.theme_list
        container.clear_widgets()
        current = self._app.theme.key
        from kivy.utils import get_color_from_hex

        for palette in PALETTES.values():
            row = SettingsOptionItem(
                key=palette.key,
                text=palette.title,
                translate=True,
                selected=palette.key == current,
                swatch_bg=get_color_from_hex(palette.bg_top),
                swatch_surface=get_color_from_hex(palette.surface),
            )
            row.bind(on_release=self._on_theme)
            container.add_widget(row)
            self._theme_rows.append(row)

    # -- actions --------------------------------------------------------------------------
    def _on_language(self, row: SettingsOptionItem) -> None:
        self._app.set_language(row.key)
        for item in self._language_rows:
            item.selected = item.key == row.key

    def _on_theme(self, row: SettingsOptionItem) -> None:
        self._app.set_theme(row.key)
        for item in self._theme_rows:
            item.selected = item.key == row.key
