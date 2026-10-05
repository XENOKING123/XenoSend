from app.ui.widgets.payload_selector import (
    PayloadFolderActionItem,
    PayloadSelectorModal,
    open_folder_row_text,
)


class YouTubeUpdateSelectorModal(PayloadSelectorModal):
    """Seletor dos updates download0.dat usando a geometria aprovada."""

    def _add_open_folder_entry(self, item_list, local_count: int) -> None:
        update_label = "update preparado" if local_count == 1 else "updates preparados"
        item = PayloadFolderActionItem(
            text=open_folder_row_text(self.OPEN_FOLDER_MARKER_GAP, local_count, update_label),
        )
        item.bind(on_release=lambda _item: self._open_folder())
        item_list.add_widget(item)
