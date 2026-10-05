"""Launch the XenoSend desktop (Windows) web UI in a native WebView2 window.

Reuses the same data directory as the Kivy build (``%APPDATA%/sendpkgpayload``)
so connection settings and caches are shared, and the same service container.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 820
MIN_WIDTH = 1040
MIN_HEIGHT = 680
BACKGROUND = "#050d18"


def _data_dir() -> Path:
    """Match Kivy's Windows user_data_dir for the SendPkgPayloadApp class."""
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / "sendpkgpayload"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _web_dir() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "app" / "desktop" / "web"
    return Path(__file__).resolve().parent / "web"


def run() -> None:
    import webview

    from app.bootstrap.dependency_container import build_container
    from app.desktop.bridge import DesktopBridge

    data_dir = _data_dir()
    container = build_container(data_dir)
    bridge = DesktopBridge(container, data_dir)

    index = _web_dir() / "index.html"
    window = webview.create_window(
        "XenoSend",
        url=str(index),
        js_api=bridge,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        background_color=BACKGROUND,
        text_select=False,
    )
    bridge.attach_window(window)

    debug = bool(os.environ.get("XENO_DEBUG"))
    webview.start(debug=debug)


if __name__ == "__main__":
    sys.exit(run())
