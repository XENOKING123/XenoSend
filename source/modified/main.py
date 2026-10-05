from pathlib import Path
import os
import sys
import traceback


def _crash_log_path() -> Path:
    base = Path(os.environ.get("ANDROID_PRIVATE") or Path.home())
    return base / "ps5_send_pkg_payload_startup_error.txt"


def _write_bootstrap_error(stage: str, exc: BaseException) -> None:
    try:
        path = _crash_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"{stage}: {type(exc).__name__}: {exc}\n\n{traceback.format_exc()}",
            encoding="utf-8",
        )
    except Exception:
        pass


DESKTOP_WINDOW_WIDTH = 380
DESKTOP_WINDOW_HEIGHT = 720


def _configure_desktop_window() -> None:
    if os.name != "nt":
        return
    try:
        from kivy.config import Config

        Config.set("graphics", "width", str(DESKTOP_WINDOW_WIDTH))
        Config.set("graphics", "height", str(DESKTOP_WINDOW_HEIGHT))
        Config.set("graphics", "resizable", "1")
        icon = Path(__file__).resolve().parent / "app" / "assets" / "xeno" / "brand" / "xeno_icon_256.png"
        if not icon.is_file():
            icon = Path(__file__).resolve().parent / "app" / "ui" / "assets" / "icon" / "icon.png"
        if icon.is_file():
            Config.set("kivy", "window_icon", str(icon))
    except Exception as exc:
        _write_bootstrap_error("configure_desktop_window", exc)


def _run_desktop_web_ui() -> bool:
    """Windows: launch the web UI in a native window. Returns False to fall back
    to the Kivy UI if the web stack is unavailable."""
    if os.name != "nt" or os.environ.get("XENO_FORCE_KIVY"):
        return False
    try:
        import webview  # noqa: F401  (presence check)
    except Exception:
        return False
    from app.desktop.run_desktop import run

    run()
    return True


if __name__ == "__main__":
    try:
        if not _run_desktop_web_ui():
            _configure_desktop_window()
            from app.bootstrap.app_factory import create_app

            create_app().run()
    except Exception as exc:
        _write_bootstrap_error("main_bootstrap", exc)
        raise
