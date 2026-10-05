import json
import os
from pathlib import Path
from typing import Iterable

from app.models.youtube_update import YouTubeUpdateSource
from app.catalogs.youtube_update_catalog import derive_youtube_update_presentation
from app.services.releases.release_version_policy import (
    is_valid_automatic_release_resolution,
)


class YouTubeUpdateSourceRepository:
    FILE_NAME = "youtube_update_sources_override.json"
    SCHEMA_VERSION = 2

    def __init__(self, data_dir: Path):
        self._path = Path(data_dir) / self.FILE_NAME

    def load(
        self, base_sources: Iterable[YouTubeUpdateSource]
    ) -> tuple[YouTubeUpdateSource, ...]:
        base = tuple(base_sources)
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return base
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != self.SCHEMA_VERSION
        ):
            return base
        records = payload.get("sources")
        if not isinstance(records, dict):
            return base
        resolved = []
        for source in base:
            record = records.get(source.key)
            if not isinstance(record, dict):
                return base
            if str(record.get("base_url", "")).strip() != source.url:
                return base
            url = str(record.get("url", "")).strip()
            if not url:
                return base
            if not is_valid_automatic_release_resolution(source.url, url):
                return base
            try:
                name, version = derive_youtube_update_presentation(url)
            except ValueError:
                return base
            resolved.append(
                source.with_resolution(name=name, version=version, url=url)
            )
        return tuple(resolved)

    def save(
        self,
        base_sources: Iterable[YouTubeUpdateSource],
        resolved_sources: Iterable[YouTubeUpdateSource],
    ) -> None:
        base_by_key = {source.key: source for source in base_sources}
        resolved = tuple(resolved_sources)
        if set(base_by_key) != {source.key for source in resolved}:
            raise ValueError("resolved_catalog_mismatch")
        records = {}
        for source in resolved:
            base = base_by_key[source.key]
            if not is_valid_automatic_release_resolution(base.url, source.url):
                raise ValueError("resolved_release_not_newer_than_base")
            records[source.key] = {
                "base_url": base.url,
                "url": source.url,
            }
        payload = {"schema_version": self.SCHEMA_VERSION, "sources": records}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self._path)
