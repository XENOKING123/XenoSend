"""Desktop (Windows) web UI for XenoSend.

The Windows build renders a modern web interface in a native WebView2 window
(via pywebview) instead of the phone-sized Kivy layout. All real work still runs
through the same services in ``app.services`` / ``app.controllers`` -- the web
layer only talks to :class:`app.desktop.bridge.DesktopBridge`.
"""
