from collections.abc import Callable, Sequence

from kivy.factory import Factory
from kivy.properties import StringProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.metrics import dp
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.utils import get_color_from_hex
from kivymd.app import MDApp
from kivymd.uix.card import MDCard
from kivymd.uix.list import MDList

from app.i18n import get_translator
from app.models.payload import PayloadMenuEntry


def open_folder_row_text(marker_gap: str, local_count: int, noun: str) -> str:
    """Markup for the 'Open Folder — * N items' row, translated and shaped for display."""
    translator = get_translator()
    text = (
        "[color=#F38B1A]" + translator.translate("Abrir Pasta") + "[/color][color=#D7DADF] — "
        f"{marker_gap}"
        "[/color][color=#F38B1A]*[/color][color=#D7DADF] "
        f"{local_count} {translator.translate(noun)}[/color]"
    )
    return translator.shape(text)


def _surface_color():
    app = MDApp.get_running_app()
    theme = getattr(app, "theme", None)
    return list(theme.surface) if theme is not None else get_color_from_hex("#191C21")


class PayloadFolderActionItem(ButtonBehavior, AnchorLayout):
    """Clickable folder row; layout and divider are defined declaratively in KV."""

    text = StringProperty("")


class PayloadSelectorModal(ModalView):
    """Centered payload selector preserving the original catalog/local ordering."""

    WIDTH_RATIO = 0.9
    HEIGHT_RATIO = 0.8
    OPEN_FOLDER_MARKER_GAP = " "

    def __init__(
        self,
        entries: Sequence[PayloadMenuEntry],
        on_select: Callable[[PayloadMenuEntry], None],
        on_open_folder: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(
            size_hint=(self.WIDTH_RATIO, self.HEIGHT_RATIO),
            auto_dismiss=True,
            background_color=(0, 0, 0, 0),
            **kwargs,
        )
        self._on_select = on_select
        self._on_open_folder = on_open_folder

        surface = MDCard(
            orientation="vertical",
            size_hint=(1, 1),
            padding=0,
            spacing=0,
            radius=[dp(10), dp(10), dp(10), dp(10)],
            md_bg_color=_surface_color(),
            elevation=8,
        )

        scroll = ScrollView(
            do_scroll_x=False,
            do_scroll_y=True,
            bar_width=dp(2),
            bar_color=get_color_from_hex("#F38B1A"),
            bar_inactive_color=get_color_from_hex("#3A404A"),
        )

        item_list = MDList(size_hint_y=None, spacing=0)
        item_list.bind(minimum_height=item_list.setter("height"))
        self._item_list = item_list
        self.replace_entries(entries)

        scroll.add_widget(item_list)
        surface.add_widget(scroll)
        self.add_widget(surface)

    def replace_entries(self, entries: Sequence[PayloadMenuEntry]) -> None:
        """Atualiza o conteúdo do seletor aberto sem alterar sua geometria."""
        remote_entries = tuple(entry for entry in entries if entry.kind == "remote")
        local_entries = tuple(entry for entry in entries if entry.kind == "local")
        self._item_list.clear_widgets()
        for entry in remote_entries:
            self._add_entry(self._item_list, entry)
        self._add_open_folder_entry(self._item_list, len(local_entries))
        for entry in local_entries:
            self._add_entry(self._item_list, entry)

    def _add_open_folder_entry(self, item_list: MDList, local_count: int) -> None:
        payload_label = "payload" if local_count == 1 else "payloads"
        item = PayloadFolderActionItem(
            text=open_folder_row_text(self.OPEN_FOLDER_MARKER_GAP, local_count, payload_label)
        )
        item.bind(on_release=lambda _item: self._open_folder())
        item_list.add_widget(item)

    def _add_entry(self, item_list: MDList, entry: PayloadMenuEntry) -> None:
        if entry.kind == "local":
            display_text = f"[color=#F38B1A]*[/color] {entry.label}"
            item = Factory.PayloadLocalMenuItem(text=display_text)
        else:
            display_text = entry.label
            item = Factory.PayloadMenuItem(text=display_text)
        item.bind(on_release=lambda _item, selected=entry: self._select(selected))
        item_list.add_widget(item)

    def _open_folder(self) -> None:
        self.dismiss()
        self._on_open_folder()

    def _select(self, entry: PayloadMenuEntry) -> None:
        self.dismiss()
        self._on_select(entry)
