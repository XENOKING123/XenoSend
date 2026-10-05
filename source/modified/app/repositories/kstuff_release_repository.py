import json
import os
from pathlib import Path

from app.services.releases.release_version_policy import (
    is_valid_automatic_release_resolution,
)


class KstuffReleaseRepository:
    FILE_NAME = "kstuff_release_source.json"
    SCHEMA_VERSION = 1

    def __init__(self, data_dir: Path):
        self._path = Path(data_dir) / self.FILE_NAME

    def load(self, base_url: str) -> str:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return base_url
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != self.SCHEMA_VERSION
        ):
            return base_url
        if str(payload.get("base_url", "")).strip() != base_url.strip():
            return base_url
        resolved_url = str(payload.get("resolved_url", "")).strip()
        if not is_valid_automatic_release_resolution(base_url, resolved_url):
            return base_url
        return resolved_url

    def save(self, base_url: str, resolved_url: str) -> None:
        if not is_valid_automatic_release_resolution(base_url, resolved_url):
            raise ValueError("resolved_release_not_newer_than_base")
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "base_url": base_url.strip(),
            "resolved_url": resolved_url.strip(),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self._path)
