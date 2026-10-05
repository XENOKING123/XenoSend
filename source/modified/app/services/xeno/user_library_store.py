"""User-owned trainer library: favorites, collections, custom/private cheat sets
and cheat files the user adds themselves.

Persisted as one JSON file (``user_library.json``) in the app data directory, with
copied cheat files and cover images kept under ``user_cheats/``. All access is
guarded by a lock and every write is atomic (temp file + replace) so a crash mid-
write can't corrupt the library. Reads fail soft to an empty library.

This is deliberately UI-agnostic so both the desktop web UI and the Kivy app can
share it.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from app.services.xeno.cheat_file_parser import SUPPORTED_EXTENSIONS, parse_cheat_file

_SCHEMA_VERSION = 1


def _norm_id(game_id: str) -> str:
    return str(game_id or "").strip().lower()


class UserLibraryStore:
    FILE_NAME = "user_library.json"
    FILES_DIRNAME = "user_cheats"

    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir)
        self._path = self._dir / self.FILE_NAME
        self._files_dir = self._dir / self.FILES_DIRNAME
        self._lock = threading.RLock()
        self._data = self._load()

    # ----------------------------------------------------------------- load/save
    def _blank(self) -> Dict:
        return {
            "version": _SCHEMA_VERSION,
            "favorites": [],
            "collections": [],
            "custom": [],
            "files": {},  # title_id_lower -> [ {name, path, format, cheats, note, created} ]
        }

    def _load(self) -> Dict:
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                return self._blank()
        except (OSError, ValueError):
            return self._blank()
        base = self._blank()
        for key in base:
            if key in data and isinstance(data[key], type(base[key])):
                base[key] = data[key]
        return base

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # ------------------------------------------------------------------ favorites
    def favorites(self) -> List[str]:
        with self._lock:
            return list(self._data["favorites"])

    def is_favorite(self, game_id: str) -> bool:
        return _norm_id(game_id) in set(self._data.get("favorites", []))

    def toggle_favorite(self, game_id: str) -> bool:
        key = _norm_id(game_id)
        if not key:
            return False
        with self._lock:
            favs = self._data["favorites"]
            if key in favs:
                favs.remove(key)
                new_state = False
            else:
                favs.append(key)
                new_state = True
            self._save()
            return new_state

    # ---------------------------------------------------------------- collections
    def collections(self) -> List[str]:
        with self._lock:
            return list(self._data["collections"])

    def add_collection(self, name: str) -> None:
        clean = str(name or "").strip()
        if not clean:
            return
        with self._lock:
            if clean not in self._data["collections"]:
                self._data["collections"].append(clean)
                self._save()

    def remove_collection(self, name: str) -> None:
        clean = str(name or "").strip()
        with self._lock:
            if clean in self._data["collections"]:
                self._data["collections"].remove(clean)
            for entry in self._data["custom"]:
                if entry.get("collection") == clean:
                    entry["collection"] = ""
            self._save()

    # -------------------------------------------------------------- custom cheats
    def custom_entries(self) -> List[Dict]:
        with self._lock:
            return [dict(e) for e in self._data["custom"]]

    def add_custom(
        self,
        *,
        title: str,
        author: str = "",
        image_src: str = "",
        collection: str = "",
        target_id: str = "",
        cheats: Optional[List[str]] = None,
        cheat_file_src: str = "",
    ) -> Dict:
        title = str(title or "").strip()
        if not title:
            raise ValueError("A title is required.")
        entry: Dict = {
            "id": "CUSTOM-" + uuid.uuid4().hex[:10],
            "title": title,
            "author": str(author or "").strip(),
            "collection": str(collection or "").strip(),
            "target_id": _norm_id(target_id),
            "image": "",
            "format": "manual",
            "cheats": [str(c).strip() for c in (cheats or []) if str(c).strip()],
            "file": "",
            "note": "",
            "created": int(time.time()),
        }
        if image_src:
            entry["image"] = self._copy_asset(image_src, prefix="img")
        if cheat_file_src:
            fmt, names, note, stored = self._ingest_cheat_file(cheat_file_src)
            entry["format"] = fmt
            entry["file"] = stored
            entry["note"] = note
            if names and not entry["cheats"]:
                entry["cheats"] = names
        with self._lock:
            if entry["collection"] and entry["collection"] not in self._data["collections"]:
                self._data["collections"].append(entry["collection"])
            self._data["custom"].insert(0, entry)
            self._save()
        return dict(entry)

    def remove_custom(self, entry_id: str) -> bool:
        with self._lock:
            before = len(self._data["custom"])
            self._data["custom"] = [e for e in self._data["custom"] if e.get("id") != entry_id]
            changed = len(self._data["custom"]) != before
            if changed:
                self._save()
            return changed

    # ------------------------------------------------- per-game imported files
    def files_for(self, game_id: str) -> List[Dict]:
        with self._lock:
            return [dict(f) for f in self._data["files"].get(_norm_id(game_id), [])]

    def add_file_for(self, game_id: str, src_path: str) -> Dict:
        key = _norm_id(game_id)
        if not key:
            raise ValueError("A target game id is required.")
        fmt, names, note, stored = self._ingest_cheat_file(src_path)
        record = {
            "name": Path(stored).name,
            "path": stored,
            "format": fmt,
            "cheats": names,
            "note": note,
            "created": int(time.time()),
        }
        with self._lock:
            self._data["files"].setdefault(key, []).append(record)
            self._save()
        return dict(record)

    def remove_file_for(self, game_id: str, name: str) -> bool:
        key = _norm_id(game_id)
        with self._lock:
            files = self._data["files"].get(key, [])
            kept = [f for f in files if f.get("name") != name]
            if len(kept) == len(files):
                return False
            if kept:
                self._data["files"][key] = kept
            else:
                self._data["files"].pop(key, None)
            self._save()
            return True

    # --------------------------------------------------------------------- assets
    def _copy_asset(self, src: str, *, prefix: str) -> str:
        src_path = Path(src)
        if not src_path.is_file():
            raise ValueError(f"File not found: {src}")
        self._files_dir.mkdir(parents=True, exist_ok=True)
        dest = self._files_dir / f"{prefix}-{uuid.uuid4().hex[:8]}{src_path.suffix.lower()}"
        shutil.copyfile(src_path, dest)
        return str(dest)

    def _ingest_cheat_file(self, src: str):
        src_path = Path(src)
        if not src_path.is_file():
            raise ValueError(f"File not found: {src}")
        if src_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported cheat file type: {src_path.suffix or '(none)'}")
        fmt, names, note = parse_cheat_file(src_path)
        stored = self._copy_asset(src, prefix="cheat")
        # keep the original filename stem so uploads to the console look sensible
        final = self._files_dir / f"{src_path.stem}{src_path.suffix.lower()}"
        try:
            if final.exists():
                final = Path(stored)  # name clash: keep the uuid name
            else:
                Path(stored).replace(final)
                stored = str(final)
        except OSError:
            pass
        return fmt, names, note, stored
