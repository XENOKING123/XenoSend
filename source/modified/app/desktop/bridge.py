"""The js_api object the web UI calls. Every method is defensive: it returns a
JSON-serialisable dict and never raises into the WebView. Long-running work runs
on a worker thread and streams progress back through ``window.evaluate_js``.
"""
from __future__ import annotations

import json
import re
import threading
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from app import app_meta
from app.services.update.update_check_service import UpdateCheckService
from app.services.xeno.user_library_store import UserLibraryStore


_GITHUB_REPO_RE = re.compile(r"github\.com/([^/]+)/([^/]+)", re.IGNORECASE)


def _repo_of(url: str) -> str:
    """owner/repo for a github URL, else the host, else 'other'."""
    try:
        m = _GITHUB_REPO_RE.search(url or "")
        if m:
            return f"{m.group(1)}/{m.group(2)}"
        host = urlparse(url or "").netloc
        return host or "other"
    except Exception:
        return "other"


def _ok(**data: Any) -> Dict[str, Any]:
    out = {"ok": True}
    out.update(data)
    return out


def _err(message: str, **data: Any) -> Dict[str, Any]:
    out = {"ok": False, "error": str(message)}
    out.update(data)
    return out


class DesktopBridge:
    IS_ANDROID = False

    def __init__(self, container: Any, data_dir: Path) -> None:
        self._c = container
        self._data_dir = Path(data_dir)
        self._window = None
        self._update_service = UpdateCheckService()
        self._refresh_started = False
        self._lib = UserLibraryStore(self._data_dir)

    # ------------------------------------------------------------------ window
    def attach_window(self, window: Any) -> None:
        self._window = window

    def _emit(self, event: str, payload: Any) -> None:
        win = self._window
        if win is None:
            return
        try:
            win.evaluate_js(f"window.__xenoEvent({json.dumps(event)}, {json.dumps(payload)})")
        except Exception:
            pass

    def _spawn(self, target: Callable[[], None]) -> None:
        threading.Thread(target=self._guard(target), daemon=True).start()

    @staticmethod
    def _guard(target: Callable[[], None]) -> Callable[[], None]:
        def runner() -> None:
            try:
                target()
            except Exception:
                traceback.print_exc()
        return runner

    # -------------------------------------------------------------------- meta
    def get_meta(self) -> Dict[str, Any]:
        return _ok(
            app_name="XenoSend",
            version=app_meta.APP_VERSION,
            default_port=app_meta.DEFAULT_LOADER_PORT,
        )

    THEMES = ("xeno", "gold", "crimson", "emerald", "violet")

    def get_prefs(self) -> Dict[str, Any]:
        try:
            data = json.loads((self._data_dir / "ui_prefs.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        theme = data.get("theme") if data.get("theme") in self.THEMES else "xeno"
        return _ok(theme=theme, display_name=str(data.get("display_name") or "")[:24])

    def set_prefs(self, theme: str, display_name: str) -> Dict[str, Any]:
        try:
            theme = theme if theme in self.THEMES else "xeno"
            name = re.sub(r"[\x00-\x1f<>]", "", str(display_name or "")).strip()[:24]
            path = self._data_dir / "ui_prefs.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"theme": theme, "display_name": name}), encoding="utf-8")
            tmp.replace(path)
            return _ok(theme=theme, display_name=name)
        except Exception as exc:
            return _err(exc)

    def get_connection(self) -> Dict[str, Any]:
        try:
            settings = self._c.discovery_controller.load_last_connection()
            return _ok(ip=settings.host or "", port=settings.port)
        except Exception as exc:
            return _err(exc, ip="", port=app_meta.DEFAULT_LOADER_PORT)

    def discover(self, port: str) -> Dict[str, Any]:
        try:
            result = self._c.discovery_controller.discover(str(port), self.IS_ANDROID)
            return _ok(
                found=result.found,
                ip=result.found_ip,
                port=result.port,
                local_ip=result.local_ip,
                cidr=result.network_cidr,
                elapsed=round(result.elapsed_seconds, 2),
            )
        except Exception as exc:
            return _err(exc)

    # ---------------------------------------------------------------- payloads
    def list_payloads(self) -> Dict[str, Any]:
        """Payload menu entries grouped by GitHub source for the Library page."""
        try:
            entries = self._c.payload_controller.menu_entries(is_android=self.IS_ANDROID)
            sources = {s.key: s for s in self._c.payload_controller.sources()}
            groups: Dict[str, Dict[str, Any]] = {}
            flat: List[Dict[str, Any]] = []
            for e in entries:
                if e.kind == "remote":
                    src = sources.get(e.source_key)
                    url = src.url if src else ""
                    repo = _repo_of(url)
                    version = src.version if src else ""
                else:
                    url = str(e.local_path or "")
                    repo = "Local files"
                    version = ""
                row = {
                    "key": e.key,
                    "label": e.label,
                    "kind": e.kind,
                    "repo": repo,
                    "version": version,
                    "url": url,
                }
                flat.append(row)
                groups.setdefault(repo, {"repo": repo, "items": []})["items"].append(row)
            ordered = sorted(groups.values(), key=lambda g: (g["repo"] == "Local files", g["repo"].lower()))
            return _ok(groups=ordered, count=len(flat))
        except Exception as exc:
            return _err(exc)

    def check_payload_updates(self) -> Dict[str, Any]:
        def work() -> None:
            try:
                self._c.payload_controller.begin_refresh_cycle()
                self._c.payload_controller.ensure_latest_sources_checked()
                self._emit("payloads:updated", self.list_payloads())
            except Exception as exc:
                self._emit("payloads:error", {"error": str(exc)})
        self._spawn(work)
        return _ok(started=True)

    def send_payload(self, key: str, host: str, port: str) -> Dict[str, Any]:
        entries = {e.key: e for e in self._c.payload_controller.menu_entries(is_android=self.IS_ANDROID)}
        entry = entries.get(key)
        if entry is None:
            return _err("unknown payload", key=key)

        def progress(p: Any) -> None:
            self._emit("send:progress", {"message": p.message, "percent": p.percent})

        def work() -> None:
            try:
                result = self._c.payload_controller.execute(
                    entry, host=host, raw_port=str(port),
                    is_android=self.IS_ANDROID, progress=progress,
                )
                self._emit("send:done", {"label": result.label, "bytes": result.bytes_sent})
            except Exception as exc:
                self._emit("send:error", {"error": str(exc)})
        self._spawn(work)
        return _ok(started=True)

    def open_payload_folder(self) -> Dict[str, Any]:
        try:
            path = self._c.payload_controller.open_local_payload_folder(is_android=self.IS_ANDROID)
            return _ok(path=str(path))
        except Exception as exc:
            return _err(exc)

    # -------------------------------------------------------------------- pkg
    def list_pkgs(self) -> Dict[str, Any]:
        """PKG titles grouped by GitHub source, same shape as list_payloads."""
        try:
            entries = self._c.pkg_controller.menu_entries(is_android=self.IS_ANDROID)
            sources = {s.key: s for s in self._c.pkg_controller.sources()}
            groups: Dict[str, Dict[str, Any]] = {}
            flat: List[Dict[str, Any]] = []
            for e in entries:
                if e.kind == "remote":
                    src = sources.get(e.source_key)
                    url = src.url if src else ""
                    repo = _repo_of(url)
                    version = src.version if src else ""
                else:
                    url = str(e.local_path or "")
                    repo = "Local files"
                    version = ""
                row = {"key": e.key, "label": e.label, "kind": e.kind, "repo": repo, "version": version, "url": url}
                flat.append(row)
                groups.setdefault(repo, {"repo": repo, "items": []})["items"].append(row)
            ordered = sorted(groups.values(), key=lambda g: (g["repo"] == "Local files", g["repo"].lower()))
            return _ok(groups=ordered, count=len(flat))
        except Exception as exc:
            return _err(exc)

    def check_pkg_updates(self) -> Dict[str, Any]:
        def work() -> None:
            try:
                self._c.pkg_controller.begin_refresh_cycle()
                self._c.pkg_controller.ensure_dependencies_checked()
                self._emit("pkg:updated", self.list_pkgs())
            except Exception as exc:
                self._emit("pkg:error", {"error": str(exc)})
        self._spawn(work)
        return _ok(started=True)

    def install_pkg(self, key: str, host: str, port: str) -> Dict[str, Any]:
        entries = {e.key: e for e in self._c.pkg_controller.menu_entries(is_android=self.IS_ANDROID)}
        entry = entries.get(key)
        if entry is None:
            return _err("unknown pkg", key=key)

        def progress(p: Any) -> None:
            self._emit("pkg:progress", {"message": p.message, "percent": p.percent})

        def work() -> None:
            try:
                result = self._c.pkg_controller.install(
                    entry, host=host, raw_port=str(port), is_android=self.IS_ANDROID, progress=progress,
                )
                self._emit("pkg:done", {"label": result.label,
                                        "content_id": getattr(result, "content_id", ""),
                                        "via": getattr(result, "installer_via", "")})
            except Exception as exc:
                self._emit("pkg:error", {"error": str(exc)})
        self._spawn(work)
        return _ok(started=True)

    def open_pkg_folder(self) -> Dict[str, Any]:
        try:
            path = self._c.pkg_controller.open_local_pkg_folder(is_android=self.IS_ANDROID)
            return _ok(path=str(path))
        except Exception as exc:
            return _err(exc)

    # --------------------------------------------------------------------- host
    def host_status(self) -> Dict[str, Any]:
        """Get current host (ReLapse exploit server) status."""
        try:
            snap = self._c.host_psm_service.snapshot()
            return _ok(phase=snap.phase, running=snap.running, local_ip=snap.local_ip,
                       endpoint=snap.endpoint, host_label=snap.host_label, client_ip=snap.client_ip)
        except Exception as exc:
            return _err(exc)

    def host_start(self) -> Dict[str, Any]:
        """Start the local exploit host server."""
        def work() -> None:
            try:
                snap = self._c.host_psm_service.start()
                self._emit("host:started", {"running": snap.running, "local_ip": snap.local_ip,
                                            "endpoint": snap.endpoint})
            except Exception as exc:
                self._emit("host:error", {"error": str(exc)})
        self._spawn(work)
        return _ok(started=True)

    def host_stop(self) -> Dict[str, Any]:
        """Stop the local exploit host server."""
        def work() -> None:
            try:
                snap = self._c.host_psm_service.stop()
                self._emit("host:stopped", {"running": snap.running})
            except Exception as exc:
                self._emit("host:error", {"error": str(exc)})
        self._spawn(work)
        return _ok(started=True)

    # ---------------------------------------------------------------- youtube
    def list_youtube_updates(self) -> Dict[str, Any]:
        try:
            entries = self._c.youtube_update_controller.menu_entries(is_android=self.IS_ANDROID)
            sources = {s.key: s for s in self._c.youtube_update_controller.sources()}
            rows = []
            for e in entries:
                if e.kind == "remote":
                    src = sources.get(e.source_key)
                    rows.append({"key": e.key, "label": e.label, "kind": "remote", "version": src.version if src else ""})
                else:
                    rows.append({"key": e.key, "label": e.label, "kind": "local", "version": ""})
            return _ok(rows=rows, count=len(rows))
        except Exception as exc:
            return _err(exc)

    def install_youtube_update(self, key: str, host: str, port: str) -> Dict[str, Any]:
        entries = {e.key: e for e in self._c.youtube_update_controller.menu_entries(is_android=self.IS_ANDROID)}
        entry = entries.get(key)
        if entry is None:
            return _err("unknown youtube update", key=key)
        def progress(p: Any) -> None:
            self._emit("youtube:progress", {"message": p.message, "percent": p.percent})
        def work() -> None:
            try:
                result = self._c.youtube_update_controller.install(entry, host=host, raw_port=str(port), is_android=self.IS_ANDROID, progress=progress)
                self._emit("youtube:done", {"label": result.label})
            except Exception as exc:
                self._emit("youtube:error", {"error": str(exc)})
        self._spawn(work)
        return _ok(started=True)

    def activate_youtube_account(self, host: str, port: str) -> Dict[str, Any]:
        def progress(p: Any) -> None:
            self._emit("youtube:progress", {"message": p.message, "percent": p.percent})
        def work() -> None:
            try:
                self._c.youtube_update_controller.activate_current_account(
                    host=host, raw_port=str(port), progress=progress)
                self._emit("youtube:activated", {})
            except Exception as exc:
                self._emit("youtube:error", {"error": str(exc)})
        self._spawn(work)
        return _ok(started=True)

    # -------------------------------------------------------------------- y2jb
    def list_y2jb_variants(self) -> Dict[str, Any]:
        try:
            rows = [{"key": v.key, "firmware": v.firmware_label, "package": v.package_label,
                     "version": v.release_version} for v in self._c.y2jb_backup_controller.variants()]
            return _ok(rows=rows)
        except Exception as exc:
            return _err(exc)

    def run_y2jb_backup(self, key: str) -> Dict[str, Any]:
        def progress(p: Any) -> None:
            self._emit("y2jb:progress", {"message": p.message, "percent": p.percent})
        def work() -> None:
            try:
                r = self._c.y2jb_backup_controller.run(key, is_android=self.IS_ANDROID, progress=progress)
                self._emit("y2jb:done", {"usb_path": r.usb_path, "files": r.copied_files})
            except Exception as exc:
                self._emit("y2jb:error", {"error": str(exc)})
        self._spawn(work)
        return _ok(started=True)

    # ---------------------------------------------------------------- trainers
    @staticmethod
    def _as_file_url(path: str) -> str:
        """A local image/file path becomes a file:// URL the WebView can load;
        anything already URL-ish (http/file) passes through."""
        p = str(path or "")
        if not p:
            return ""
        if p.startswith(("http://", "https://", "file://")):
            return p
        try:
            fp = Path(p)
            return fp.as_uri() if fp.exists() else ""
        except Exception:
            return ""

    def _trainer_row(self, g: Any) -> Dict[str, Any]:
        fmt = g.best_format()
        return {
            "id": g.id,
            "title": g.title or g.id,
            "version": g.version,
            "cheats_total": g.cheats_total,
            "creators": list(g.creators),
            "formats": sorted(g.formats.keys()),
            "cheats": list(fmt.cheats) if fmt else [],
            "cover": self._cover_url(g.title),
            "favorite": self._lib.is_favorite(g.id),
            "custom": False,
            "author": g.creators[0] if g.creators else "",
        }

    def _custom_row(self, e: Dict[str, Any]) -> Dict[str, Any]:
        cheats = list(e.get("cheats") or [])
        return {
            "id": e.get("id", ""),
            "title": e.get("title") or e.get("id", ""),
            "version": "",
            "cheats_total": len(cheats),
            "creators": [e["author"]] if e.get("author") else [],
            "formats": [e.get("format", "manual")],
            "cheats": cheats,
            "cover": self._as_file_url(e.get("image", "")),
            "favorite": self._lib.is_favorite(e.get("id", "")),
            "custom": True,
            "author": e.get("author", ""),
            "collection": e.get("collection", ""),
            "target_id": e.get("target_id", ""),
            "note": e.get("note", ""),
        }

    def _filter_custom(self, query: str, collection: str) -> List[Dict[str, Any]]:
        needle = str(query or "").strip().lower()
        coll = str(collection or "").strip()
        out = []
        for e in self._lib.custom_entries():
            if coll and e.get("collection", "") != coll:
                continue
            if needle and needle not in f"{e.get('title','')} {e.get('author','')}".lower():
                continue
            out.append(e)
        return out

    def list_trainers(self, query: str = "", offset: int = 0, limit: int = 60,
                      scope: str = "all", collection: str = "") -> Dict[str, Any]:
        """Paged trainer list. ``scope`` is 'all', 'favorites' or 'custom'; custom
        entries sort ahead of catalog games. Only the requested page is materialised."""
        try:
            cat = self._c.trainer_catalog
            offset, limit = int(offset), int(limit)

            if scope == "custom":
                custom = self._filter_custom(query, collection)
                catalog: tuple = ()
            elif scope == "favorites":
                custom = [e for e in self._filter_custom(query, "") if self._lib.is_favorite(e.get("id", ""))]
                games = cat.search(query) if query else cat.all_games()
                catalog = tuple(g for g in games if self._lib.is_favorite(g.id))
            else:  # all
                custom = self._filter_custom(query, "")
                catalog = tuple(cat.search(query)) if query else cat.all_games()

            nc = len(custom)
            total = nc + len(catalog)
            rows: List[Dict[str, Any]] = []
            for i in range(offset, min(offset + limit, total)):
                if i < nc:
                    rows.append(self._custom_row(custom[i]))
                else:
                    rows.append(self._trainer_row(catalog[i - nc]))
            return _ok(total=total, offset=offset, rows=rows)
        except Exception as exc:
            return _err(exc, rows=[], total=0)

    # ------------------------------------------------- favorites / collections
    def toggle_favorite(self, game_id: str) -> Dict[str, Any]:
        try:
            return _ok(id=game_id, favorite=self._lib.toggle_favorite(game_id))
        except Exception as exc:
            return _err(exc)

    def list_collections(self) -> Dict[str, Any]:
        try:
            cols = self._lib.collections()
            counts: Dict[str, int] = {c: 0 for c in cols}
            for e in self._lib.custom_entries():
                c = e.get("collection", "")
                if c:
                    counts[c] = counts.get(c, 0) + 1
            return _ok(collections=[{"name": c, "count": counts.get(c, 0)} for c in cols])
        except Exception as exc:
            return _err(exc, collections=[])

    def create_collection(self, name: str) -> Dict[str, Any]:
        try:
            self._lib.add_collection(name)
            return _ok()
        except Exception as exc:
            return _err(exc)

    def remove_collection(self, name: str) -> Dict[str, Any]:
        try:
            self._lib.remove_collection(name)
            return _ok()
        except Exception as exc:
            return _err(exc)

    # ------------------------------------------------------------- custom cheats
    def add_custom_cheats(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """payload: {title, author?, image?, collection?, target_id?, cheats?[], cheat_file?}."""
        try:
            p = payload or {}
            cheats = p.get("cheats")
            if isinstance(cheats, str):
                cheats = [line.strip() for line in cheats.splitlines() if line.strip()]
            entry = self._lib.add_custom(
                title=p.get("title", ""),
                author=p.get("author", ""),
                image_src=p.get("image", ""),
                collection=p.get("collection", ""),
                target_id=p.get("target_id", ""),
                cheats=cheats or [],
                cheat_file_src=p.get("cheat_file", ""),
            )
            return _ok(entry=self._custom_row(entry))
        except Exception as exc:
            return _err(exc)

    def remove_custom(self, entry_id: str) -> Dict[str, Any]:
        try:
            return _ok(removed=self._lib.remove_custom(entry_id))
        except Exception as exc:
            return _err(exc)

    # ---------------------------------------------- per-game imported cheat files
    def trainer_files(self, game_id: str) -> Dict[str, Any]:
        try:
            return _ok(files=self._lib.files_for(game_id))
        except Exception as exc:
            return _err(exc, files=[])

    def add_trainer_file(self, game_id: str, file_path: str) -> Dict[str, Any]:
        try:
            return _ok(file=self._lib.add_file_for(game_id, file_path))
        except Exception as exc:
            return _err(exc)

    def remove_trainer_file(self, game_id: str, name: str) -> Dict[str, Any]:
        try:
            return _ok(removed=self._lib.remove_file_for(game_id, name))
        except Exception as exc:
            return _err(exc)

    # ------------------------------------------------------------- file picker
    def pick_file(self, kind: str = "cheat") -> Dict[str, Any]:
        """Open a native file dialog; returns the chosen path (or cancelled)."""
        try:
            import webview
            if kind == "image":
                types = ("Image files (*.png;*.jpg;*.jpeg;*.webp;*.gif)", "All files (*.*)")
            else:
                types = ("Cheat files (*.json;*.shn;*.mc4)", "All files (*.*)")
            win = self._window
            if win is None:
                return _err("no window")
            result = win.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=types)
            if not result:
                return _ok(cancelled=True, path="")
            return _ok(path=str(result[0]))
        except Exception as exc:
            return _err(exc)

    def _cover_url(self, title: str) -> str:
        try:
            return self._c.cover_art_service.resolve_url(title) or ""
        except Exception:
            return ""

    def showcase_covers(self, limit: int = 40) -> Dict[str, Any]:
        """Games with a resolvable cover, for the Home marquee."""
        try:
            out: List[Dict[str, Any]] = []
            for g in self._c.trainer_catalog.all_games():
                url = self._cover_url(g.title)
                if url:
                    out.append({"id": g.id, "title": g.title or g.id, "cover": url,
                                "cheats_total": g.cheats_total})
                if len(out) >= int(limit):
                    break
            return _ok(covers=out)
        except Exception as exc:
            return _err(exc, covers=[])

    # ---------------------------------------------------- installed games (live)
    def list_installed_games(self, host: str) -> Dict[str, Any]:
        """Games CheatRunner reports as installed on the console (``/api/games``)."""
        host = str(host or "").strip()
        if not host:
            return _err("No PS5 IP set.", rows=[])
        try:
            client = self._c.cheatrunner_client
            if not client.is_up(host):
                return _err(f"CheatRunner not reachable at {host}:9999.", rows=[], unreachable=True)
            games = client.list_games(host)
            cat = self._c.trainer_catalog
            rows = []
            for g in games:
                catalog = cat.by_id(g.title_id) if g.title_id else None
                rows.append({
                    "id": g.title_id,
                    "title": g.name or (catalog.title if catalog else g.title_id),
                    "version": g.version,
                    "running": bool(g.running),
                    "has_cheat": bool(g.has_cheat),
                    "is_app": bool(g.is_app),
                    "in_catalog": catalog is not None,
                    "cover": self._cover_url(catalog.title) if catalog else "",
                    "favorite": self._lib.is_favorite(g.title_id),
                    "added_files": len(self._lib.files_for(g.title_id)),
                })
            return _ok(rows=rows)
        except Exception as exc:
            return _err(exc, rows=[])

    def upload_trainer_file_to_console(self, host: str, game_id: str, name: str) -> Dict[str, Any]:
        """Push one previously-added cheat file for a game up to CheatRunner."""
        host = str(host or "").strip()
        if not host:
            return _err("No PS5 IP set.")
        match = next((f for f in self._lib.files_for(game_id) if f.get("name") == name), None)
        if match is None:
            return _err("That cheat file is no longer in your library.")

        def work() -> None:
            try:
                self._c.cheatrunner_client.upload_cheat_file(host, match["path"], filename_hint=name)
                self._emit("cheatfile:uploaded", {"game_id": game_id, "name": name})
            except Exception as exc:
                self._emit("cheatfile:error", {"game_id": game_id, "name": name, "error": str(exc)})
        self._spawn(work)
        return _ok(started=True)

    # --------------------------------------------------- live trainer (attach)
    @staticmethod
    def _cheat_payload(cheats) -> List[Dict[str, Any]]:
        return [{"index": c.index, "name": c.name, "enabled": bool(c.enabled)} for c in cheats]

    def attach_trainer(self, host: str, title_id: str) -> Dict[str, Any]:
        host = str(host or "").strip()
        if not host:
            return _err("No PS5 IP set.")
        try:
            client = self._c.cheatrunner_client
            if not client.is_up(host):
                return _err(f"CheatRunner not reachable at {host}:9999.", unreachable=True)
            result = client.attach(host, title_id)
            cheats = client.cheat_state(host, title_id) if result.ok else ()
            return _ok(attached=result.ok, launched=result.launched,
                       cheats=self._cheat_payload(cheats), message=result.message)
        except Exception as exc:
            return _err(exc)

    def trainer_cheat_state(self, host: str, title_id: str) -> Dict[str, Any]:
        try:
            cheats = self._c.cheatrunner_client.cheat_state(str(host or "").strip(), title_id)
            return _ok(cheats=self._cheat_payload(cheats))
        except Exception as exc:
            return _err(exc, cheats=[])

    def toggle_trainer_cheat(self, host: str, title_id: str, index: int, on: bool) -> Dict[str, Any]:
        try:
            client = self._c.cheatrunner_client
            client.toggle_cheat(str(host or "").strip(), title_id, int(index), bool(on))
            cheats = client.cheat_state(str(host or "").strip(), title_id)
            return _ok(cheats=self._cheat_payload(cheats))
        except Exception as exc:
            return _err(exc)

    def disable_all_trainer(self, host: str, title_id: str) -> Dict[str, Any]:
        try:
            client = self._c.cheatrunner_client
            client.disable_all(str(host or "").strip(), title_id)
            cheats = client.cheat_state(str(host or "").strip(), title_id)
            return _ok(cheats=self._cheat_payload(cheats))
        except Exception as exc:
            return _err(exc)

    # -------------------------------------------------------------- auto-loader
    def auto_load(self, host: str, port: str) -> Dict[str, Any]:
        try:
            port_int = self._c.discovery_controller.parse_port(str(port))
        except Exception as exc:
            return _err(exc)

        def on_step(label: str, index: int, total: int) -> None:
            self._emit("autoload:step", {"label": label, "index": index, "total": total})

        def progress(p: Any) -> None:
            msg = getattr(p, "message", None)
            pct = getattr(p, "percent", None)
            self._emit("autoload:progress", {"message": msg if msg else str(p), "percent": pct})

        def work() -> None:
            try:
                self._c.auto_loader_service.run(
                    host=host, port=port_int, is_android=self.IS_ANDROID,
                    on_step=on_step, progress=progress,
                )
                self._emit("autoload:done", {})
            except Exception as exc:
                self._emit("autoload:error", {"error": str(exc)})
        self._spawn(work)
        return _ok(started=True)

    # ---------------------------------------------------------------- app update
    def check_app_update(self) -> Dict[str, Any]:
        def work() -> None:
            try:
                info = self._update_service.check()
                if info is None:
                    self._emit("appupdate:none", {})
                else:
                    self._emit("appupdate:available", {
                        "version": getattr(info, "tag", ""),
                        "url": getattr(info, "url", ""),
                    })
            except Exception as exc:
                self._emit("appupdate:error", {"error": str(exc)})
        self._spawn(work)
        return _ok(started=True)
