from app.ui.widgets.payload_selector import (
    PayloadFolderActionItem,
    PayloadSelectorModal,
    open_folder_row_text,
)

class PkgSelectorModal(PayloadSelectorModal):
    """PKG selector using the already-approved payload selector geometry."""

    def _add_open_folder_entry(self, item_list, local_count: int) -> None:
        pkg_label = "PKG" if local_count == 1 else "PKGs"
        item = PayloadFolderActionItem(
            text=open_folder_row_text(self.OPEN_FOLDER_MARKER_GAP, local_count, pkg_label),
        )
        item.bind(on_release=lambda _item: self._open_folder())
        item_list.add_widget(item)
