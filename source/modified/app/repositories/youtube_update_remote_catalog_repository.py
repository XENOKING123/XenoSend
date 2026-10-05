from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from app.models.youtube_update import YouTubeUpdateSource
from app.services.catalog.catalog_contract import (
    CATALOG_APP,
    CATALOG_SCHEMA_VERSION,
    KIND_YOUTUBE,
    catalog_document,
)
from app.services.youtube_update.youtube_update_catalog_update_service import (
    InvalidYouTubeUpdateCatalogError,
    YouTubeUpdateCatalogUpdateService,
)


class YouTubeUpdateRemoteCatalogRepository:
    FILE_NAME = "youtube_update_catalog_cache.json"
    SCHEMA_VERSION = CATALOG_SCHEMA_VERSION

    def __init__(self, data_dir: Path):
        self._path = Path(data_dir) / self.FILE_NAME

    def load(self, catalog_url: str) -> tuple[YouTubeUpdateSource, ...]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return ()
        if not isinstance(payload, dict):
            return ()
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            return ()
        if str(payload.get("catalog_url", "") or "").strip() != str(catalog_url or "").strip():
            return ()
        items = payload.get("items")
        if not isinstance(items, list):
            return ()
        try:
            document = {
                "schema_version": CATALOG_SCHEMA_VERSION,
                "app": CATALOG_APP,
                "kind": KIND_YOUTUBE,
                "items": items,
            }
            return YouTubeUpdateCatalogUpdateService.parse_catalog(document)
        except (InvalidYouTubeUpdateCatalogError, TypeError, ValueError):
            return ()

    def save(self, catalog_url: str, sources: Iterable[YouTubeUpdateSource]) -> None:
        rows = []
        for source in sources:
            row = {"key": source.key, "url": source.url}
            if source.name_override.strip():
                row["name_override"] = source.name_override.strip()
            rows.append(row)
        if not rows:
            raise ValueError("empty_remote_youtube_update_catalog")
        validated = catalog_document(KIND_YOUTUBE, rows)["items"]
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "catalog_url": str(catalog_url or "").strip(),
            "items": validated,
        }
        self._write(payload)

    def _write(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self._path)
