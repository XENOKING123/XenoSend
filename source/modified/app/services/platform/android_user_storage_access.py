from typing import Callable, Optional

from kivy.clock import Clock
from kivy.utils import platform


ReadyCallback = Optional[Callable[[], None]]


class AndroidUserStorageAccess:
    """Runtime access gate for the public folders that contain user files."""

    def has_access(self) -> bool:
        if platform != "android":
            return True

        try:
            from jnius import autoclass

            Environment = autoclass("android.os.Environment")
            if hasattr(Environment, "isExternalStorageManager"):
                return bool(Environment.isExternalStorageManager())
        except Exception:
            pass

        try:
            from android.permissions import Permission, check_permission

            needed = [Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE]
            return all(check_permission(permission) for permission in needed)
        except Exception:
            return False

    def ensure(self, on_ready: ReadyCallback = None) -> bool:
        if self.has_access():
            return True
        if platform != "android":
            return True

        if self._open_all_files_settings():
            return False

        try:
            from android.permissions import Permission, request_permissions

            needed = [Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE]

            def _after(_permissions, _grants):
                if self.has_access():
                    self._schedule(on_ready)

            request_permissions(needed, _after)
            return False
        except Exception:
            return False

    @staticmethod
    def _open_all_files_settings() -> bool:
        try:
            from jnius import autoclass

            Environment = autoclass("android.os.Environment")
            if not hasattr(Environment, "isExternalStorageManager"):
                return False

            Settings = autoclass("android.provider.Settings")
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity

            intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
            intent.setData(Uri.parse("package:" + activity.getPackageName()))
            activity.startActivity(intent)
            return True
        except Exception:
            return False

    @staticmethod
    def _schedule(callback: ReadyCallback) -> None:
        if callback is not None:
            Clock.schedule_once(lambda _dt: callback(), 0)
