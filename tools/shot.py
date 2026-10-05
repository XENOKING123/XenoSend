"""Launch the app from a source tree, optionally drive it, and save window screenshots.

usage: python shot.py <tree> <out_prefix> [--lang xx] [--theme name] [--wait SEC] [--actions a,b]

The tree must contain main.py and app/.  Runs the real SendPkgPayloadApp.  Screenshots land at
<out_prefix>_<n>.png.  Optional actions (comma separated): settings, lang=xx, theme=name.
"""
import argparse
import os
import sys

ap = argparse.ArgumentParser()
ap.add_argument("tree")
ap.add_argument("out")
ap.add_argument("--wait", type=float, default=4.0)
ap.add_argument("--actions", default="")
ap.add_argument("--lang", default="")
ap.add_argument("--theme", default="")
ap.add_argument("--size", default="380x720")
args = ap.parse_args()

args.out = os.path.abspath(args.out)  # resolve before chdir
tree = os.path.abspath(args.tree)
os.chdir(tree)
sys.path.insert(0, tree)
os.environ["KIVY_NO_ARGS"] = "1"
os.environ.setdefault("SENDPP_SHOT", "1")
if args.lang:
    os.environ["SENDPP_FORCE_LANG"] = args.lang
os.environ["SENDPP_FORCE_THEME"] = args.theme or "midnight"

import main as entry  # noqa: E402

w, h = args.size.split("x")
entry.DESKTOP_WINDOW_WIDTH = int(w)
entry.DESKTOP_WINDOW_HEIGHT = int(h)
entry._configure_desktop_window()

from kivy.clock import Clock  # noqa: E402
from kivy.config import Config  # noqa: E402

Config.set("graphics", "position", "custom")
if os.environ.get("SENDPP_SHOT_ONSCREEN"):
    Config.set("graphics", "left", "40")
    Config.set("graphics", "top", "40")
else:  # off-screen: nothing can click the window while it is under test
    Config.set("graphics", "left", "-3000")
    Config.set("graphics", "top", "40")

from app.bootstrap.app_factory import create_app  # noqa: E402

app = create_app()
from kivy.core.window import Window as _W
_W.bind(on_touch_down=lambda w, t: print("TOUCH_DOWN", t.pos, flush=True))
_W.bind(on_touch_up=lambda w, t: print("TOUCH_UP", t.pos, flush=True))
counter = {"n": 0}


def snap(_dt=0):
    from kivy.core.window import Window

    counter["n"] += 1
    path = f"{args.out}_{counter['n']}.png"
    Window.screenshot(name=path)  # appends a 4-digit counter
    # Window.screenshot appends a counter; report the final name
    modal = getattr(app, "_settings_modal", None)
    print("SNAP", path, "theme=", app.theme.key if app.theme else None, "lang=", app.tr.language if app.tr else None,
          "modal_open=", bool(modal is not None and modal._window is not None), flush=True)


def run_actions(_dt):
    t = 0.0
    for act in [a for a in args.actions.split(",") if a]:
        t += 1.0
        if act == "snap":
            Clock.schedule_once(snap, t)
        elif act == "settings":
            Clock.schedule_once(lambda _d: app.open_settings(), t)
        elif act == "trainers":
            Clock.schedule_once(lambda _d: app.root.open_trainer_browser(None), t)
        elif act == "trainer_detail":
            def open_first_trainer_detail(_d):
                modal = app.root._trainer_browser_modal
                if modal is None:
                    app.root.open_trainer_browser(None)
                    modal = app.root._trainer_browser_modal
                row = modal._item_list.children[-1]  # MDList children are reversed (last added = index 0)
                row.dispatch("on_release")
            Clock.schedule_once(open_first_trainer_detail, t)
        elif act.startswith("lang="):
            code = act.split("=", 1)[1]
            Clock.schedule_once(lambda _d, c=code: app.set_language(c), t)
        elif act.startswith("theme="):
            name = act.split("=", 1)[1]
            Clock.schedule_once(lambda _d, n=name: app.set_theme(n), t)
        elif act.startswith("ui_lang=") or act.startswith("ui_theme="):
            kind, val = act.split("=", 1)

            def click(_d, kind=kind, val=val):
                modal = getattr(app, "_settings_modal", None)
                if modal is None or modal._window is None:
                    app.open_settings()
                    modal = app._settings_modal
                rows = modal._language_rows if kind == "ui_lang" else modal._theme_rows
                row = next(r for r in rows if r.key == val)
                row.dispatch("on_release")  # exactly what a click on the row does
            Clock.schedule_once(click, t)
        elif act == "status":
            def fill(_d):
                from kivy.utils import get_color_from_hex as h
                r = app.root
                r.status_text, r.status_color = "PS5 encontrado em 192.168.4.41:9021", h("#79C98D")
                r.host_psm_status_text, r.host_psm_status_color = "Ativo • Proxy 192.168.4.20:8080 • abra o Guia do Usuário", h("#79C98D")
                r.pkg_status_text, r.pkg_status_color = "Enviando PKG • 47%", h("#B8BDC5")
                r.payload_status_text, r.payload_status_color = "Falha • Porta inválida. Use somente números.", h("#E47C73")
                r.youtube_update_status_text, r.youtube_update_status_color = "Baixando update • 12%", h("#B8BDC5")
                r.backup_status_text, r.backup_status_color = "Concluído • 12 arquivo(s)", h("#79C98D")
            Clock.schedule_once(fill, t)
        elif act == "dismiss":
            Clock.schedule_once(lambda _d: app._settings_modal.dismiss(), t)
        elif act == "close":
            Clock.schedule_once(lambda _d: app.stop(), t)


orig_on_start = app.on_start


def on_start(*a, **k):
    Clock.schedule_once(run_actions, args.wait)
    return orig_on_start(*a, **k)


app.on_start = on_start
app.run()
