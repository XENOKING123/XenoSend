"""Resolves and caches box-art thumbnails for trainer catalog games.

Backed by ``app/assets/xeno/covers.json`` (a ``{"titles": {"<normalized title>": "<url>"}}``
map on the Sony PlayStation CDN). Loaded lazily — importing/constructing this service must
never touch the filesystem or network by itself.

Cover art is purely cosmetic, so every public method **fails soft**: on any error (missing
title, unreachable CDN, disk I/O failure, ...) the method returns ``None`` instead of raising,
and the caller is expected to fall back to a placeholder.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Dict, Optional

import requests

COVERS_RELATIVE_PATH = Path("assets") / "xeno" / "covers.json"
_NO_IMAGE_SENTINEL = "no-image"
_REQUEST_TIMEOUT_SECONDS = 5.0


def _covers_path() -> Path:
    return Path(__file__).resolve().parents[2] / COVERS_RELATIVE_PATH


def _normalize_title(title: str) -> str:
    return str(title or "").strip().lower()


class CoverArtService:
    def __init__(self, data_dir: Path, session: Optional[requests.Session] = None) -> None:
        self._cache_dir = Path(data_dir) / "xeno_covers"
        self._session = session or requests.Session()
        self._lock = threading.Lock()
        self._titles: Optional[Dict[str, str]] = None

    # -- lazy load of the static title -> URL map ------------------------------------------
    def _load_titles(self) -> Dict[str, str]:
        if self._titles is not None:
            return self._titles
        with self._lock:
            if self._titles is not None:
                return self._titles
            try:
                payload = json.loads(_covers_path().read_text(encoding="utf-8"))
                raw_titles = payload.get("titles") if isinstance(payload, dict) else None
                titles = {
                    str(key): str(value)
                    for key, value in raw_titles.items()
                    if isinstance(key, str) and isinstance(value, str)
                } if isinstance(raw_titles, dict) else {}
            except (OSError, ValueError, AttributeError):
                titles = {}
            self._titles = titles
            return titles

    def resolve_url(self, title: str) -> Optional[str]:
        """URL for ``title`` on the Sony CDN, or ``None`` if unknown / has no art."""
        url = self._load_titles().get(_normalize_title(title))
        if not url or url.strip().lower() == _NO_IMAGE_SENTINEL:
            return None
        return url.strip()

    def cache_path_for_url(self, url: str) -> Path:
        digest = hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:16]
        return self._cache_dir / f"{digest}.png"

    def fetch(self, title: str) -> Optional[Path]:
        """Resolve + download (or reuse the cache for) ``title``'s cover. Never raises."""
        try:
            url = self.resolve_url(title)
            if not url:
                return None
            destination = self.cache_path_for_url(url)
            if destination.is_file() and destination.stat().st_size > 0:
                return destination
            response = self._session.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
            if response.status_code < 200 or response.status_code >= 300:
                return None
            content = response.content
            if not content:
                return None
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_suffix(destination.suffix + ".part")
            partial.write_bytes(content)
            partial.replace(destination)
            return destination
        except Exception:
            return None
