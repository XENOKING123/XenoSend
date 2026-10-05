import os
from pathlib import Path

from kivy.core.window import Window
from kivy.properties import ObjectProperty
from kivy.utils import platform
from kivymd.app import MDApp

from app import i18n
from app.app_meta import APP_NAME, APP_VERSION
from app.bootstrap.dependency_container import build_container
from app.ui.kv_loader import load_all_kv
from app.ui.main_screen import MainScreen
from app.ui.preferences import UiPreferences
from app.ui.theme import DEFAULT_THEME, PALETTES, ThemeManager
from app.ui.widgets.settings_modal import SettingsModal


class SendPkgPayloadApp(MDApp):
    title = APP_NAME
    app_version = APP_VERSION

    # Exposed to KV: ``app.tr._("text")`` for strings, ``app.theme.<colour>`` for colours.
    tr = ObjectProperty(None)
    theme = ObjectProperty(None)

    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Orange"

        self._preferences = UiPreferences(Path(self.user_data_dir))
        self._settings_modal = None
        self._init_language()
        self._init_theme()

        load_all_kv()
        container = build_container(Path(self.user_data_dir))
        return MainScreen(container=container)

    # ----- language / theme -------------------------------------------------------------
    def _init_language(self) -> None:
        # Always start in English until the user picks a language from Settings and it gets
        # saved. (Earlier builds followed the OS locale on first launch; that's gone now.)
        saved = self._preferences.get("language")
        code = saved if saved and i18n.is_supported(saved) else "en"
        forced = os.environ.get("SENDPP_FORCE_LANG")
        if forced and i18n.is_supported(forced):
            code = forced
        self.tr = i18n.get_translator()
        i18n.set_language(code)

    def _init_theme(self) -> None:
        key = os.environ.get("SENDPP_FORCE_THEME") or self._preferences.get("theme") or DEFAULT_THEME
        self.theme = ThemeManager(key if key in PALETTES else DEFAULT_THEME)

    def set_language(self, code: str) -> bool:
        """Switch the interface language live and remember the choice."""
        if not i18n.is_supported(code):
            return False
        font_changed = i18n.set_language(code)
        self._preferences.save(language=code)
        if font_changed:
            i18n.fonts.refresh_text_widgets(Window)
        return True

    def set_theme(self, key: str) -> bool:
        """Switch the background theme live and remember the choice."""
        if not self.theme.apply(key):
            return False
        self._preferences.save(theme=key)
        return True

    def open_settings(self) -> None:
        modal = self._settings_modal
        if modal is not None and modal._window is not None:
            return
        self._settings_modal = SettingsModal()
        self._settings_modal.open()

    # ----- lifecycle (unchanged from the original build) -----------------------------------
    def on_resume(self):
        root = self.root

        if (
            platform == "android"
            and root is not None
            and hasattr(root, "refresh_remote_checks_on_resume")
        ):
            root.refresh_remote_checks_on_resume()
        if root is not None and hasattr(root, "resume_pending_user_storage_menu"):
            root.resume_pending_user_storage_menu()
        if root is not None and hasattr(root, "resume_host_psm_session"):
            root.resume_host_psm_session()

    def on_pause(self):
        if platform == "android":
            return True
        root = self.root
        return bool(root is not None and getattr(root, "host_psm_running", False))

    def on_stop(self):
        root = self.root
        if root is not None and hasattr(root, "handle_app_stop"):
            root.handle_app_stop()
        elif root is not None and hasattr(root, "shutdown"):
            root.shutdown()
