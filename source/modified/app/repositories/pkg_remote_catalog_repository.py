from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from app.models.pkg import PkgSource
from app.services.catalog.catalog_contract import (
    CATALOG_APP,
    CATALOG_SCHEMA_VERSION,
    KIND_PKGS,
    catalog_document,
)
from app.services.pkg.pkg_catalog_update_service import (
    InvalidPkgCatalogError,
    PkgCatalogUpdateService,
)


class PkgRemoteCatalogRepository:
    FILE_NAME = "pkg_catalog_cache.json"
    SCHEMA_VERSION = CATALOG_SCHEMA_VERSION

    def __init__(self, data_dir: Path):
        self._path = Path(data_dir) / self.FILE_NAME

    def load(self, catalog_url: str) -> tuple[PkgSource, ...]:
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
                "kind": KIND_PKGS,
                "items": items,
            }
            return PkgCatalogUpdateService.parse_catalog(document)
        except (InvalidPkgCatalogError, TypeError, ValueError):
            return ()

    def save(self, catalog_url: str, sources: Iterable[PkgSource]) -> None:
        rows = []
        for source in sources:
            row = {"key": source.key, "url": source.url}
            if source.name_override.strip():
                row["name_override"] = source.name_override.strip()
            rows.append(row)
        if not rows:
            raise ValueError("empty_remote_pkg_catalog")
        validated = catalog_document(KIND_PKGS, rows)["items"]
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "catalog_url": str(catalog_url or "").strip(),
            "items": validated,
        }
        self._write(payload)

    def _write(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self._path)
