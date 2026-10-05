from kivy.core.window import Window
from kivy.properties import BooleanProperty
from kivy.utils import platform
from kivymd.uix.button import MDIconButton, MDRaisedButton


class _DesktopHoverBehavior:
    """Expose a stable hover state without depending on optional KivyMD APIs."""

    hovered = BooleanProperty(False)

    def __init__(self, **kwargs):
        self._mouse_binding_active = False
        super().__init__(**kwargs)
        self.bind(parent=self._on_parent_changed, disabled=self._on_disabled_changed)
        if self.parent is not None:
            self._bind_mouse_position()

    def _on_parent_changed(self, _instance, parent) -> None:
        if parent is None:
            self.hovered = False
            self._unbind_mouse_position()
            return
        self._bind_mouse_position()

    def _on_disabled_changed(self, _instance, disabled: bool) -> None:
        if disabled:
            self.hovered = False

    def _bind_mouse_position(self) -> None:
        if platform == "android" or self._mouse_binding_active:
            return
        Window.bind(mouse_pos=self._on_mouse_position)
        self._mouse_binding_active = True

    def _unbind_mouse_position(self) -> None:
        if not self._mouse_binding_active:
            return
        Window.unbind(mouse_pos=self._on_mouse_position)
        self._mouse_binding_active = False

    def _on_mouse_position(self, _window, position) -> None:
        is_hovered = False
        if not self.disabled and self.get_root_window() is not None:
            widget_position = self.to_widget(*position)
            is_hovered = self.collide_point(*widget_position)
        if self.hovered != is_hovered:
            self.hovered = is_hovered


class PremiumRaisedButton(_DesktopHoverBehavior, MDRaisedButton):
    """Raised action with desktop hover and native pressed state."""

    def on_kv_post(self, base_widget) -> None:
        super().on_kv_post(base_widget)
        self._sync_hover_text_weight()

    def on_hovered(self, _instance, _hovered: bool) -> None:
        self._sync_hover_text_weight()

    def _sync_hover_text_weight(self) -> None:
        label = self.ids.get("lbl_txt")
        if label is not None:
            label.bold = bool(self.hovered)


class PremiumIconButton(_DesktopHoverBehavior, MDIconButton):
    """Icon action with desktop hover and native pressed state."""
