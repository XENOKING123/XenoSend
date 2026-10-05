import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from app.models.y2jb_backup import Y2JBBackupVariant
from app.services.releases.github_release_service import GitHubReleaseService
from app.services.releases.release_version_policy import (
    is_valid_automatic_release_resolution,
)


class Y2JBReleaseRepository:
    """Persists resolved release URLs while tying them to the code's base catalog."""

    FILE_NAME = "y2jb_release_sources.json"
    SCHEMA_VERSION = 1

    def __init__(self, data_dir: Path):
        self._path = Path(data_dir) / self.FILE_NAME

    def load(
        self,
        base_variants: Iterable[Y2JBBackupVariant],
    ) -> tuple[Y2JBBackupVariant, ...]:
        base = tuple(base_variants)
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return base
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != self.SCHEMA_VERSION
        ):
            return base
        records = payload.get("variants")
        if not isinstance(records, dict):
            return base

        resolved = []
        for variant in base:
            record = records.get(variant.key)
            if not isinstance(record, dict):
                return base
            if str(record.get("base_url", "")).strip() != variant.url:
                return base
            if str(record.get("base_filename", "")).strip() != variant.filename:
                return base

            url = str(record.get("url", "")).strip()
            filename = str(record.get("filename", "")).strip()
            version = str(record.get("release_version", "")).strip()
            package_label = str(record.get("package_label", "")).strip()
            if not (url and filename and version and package_label):
                return base
            if not is_valid_automatic_release_resolution(variant.url, url):
                return base
            release = GitHubReleaseService.parse_download_url(url)
            if (
                release is None
                or release.asset != filename
                or release.tag != version
            ):
                return base

            resolved.append(
                replace(
                    variant,
                    url=url,
                    filename=filename,
                    release_version=version,
                    package_label=package_label,
                )
            )
        return tuple(resolved)

    def save(
        self,
        base_variants: Iterable[Y2JBBackupVariant],
        resolved_variants: Iterable[Y2JBBackupVariant],
    ) -> None:
        base_by_key = {variant.key: variant for variant in base_variants}
        resolved = tuple(resolved_variants)
        if set(base_by_key) != {variant.key for variant in resolved}:
            raise ValueError("resolved_catalog_mismatch")

        records = {}
        resolved_release_tags = set()
        for variant in resolved:
            base = base_by_key[variant.key]
            if not is_valid_automatic_release_resolution(base.url, variant.url):
                raise ValueError("resolved_release_not_newer_than_base")
            release = GitHubReleaseService.parse_download_url(variant.url)

            if (
                release is None
                or release.asset != variant.filename
                or release.tag != variant.release_version
            ):
                raise ValueError("resolved_release_metadata_mismatch")
            resolved_release_tags.add(release.tag)

            records[variant.key] = {
                "base_url": base.url,
                "base_filename": base.filename,
                "url": variant.url,
                "filename": variant.filename,
                "release_version": variant.release_version,
                "package_label": variant.package_label,
            }

        if len(resolved_release_tags) != 1:
            raise ValueError("resolved_release_catalog_incoherent")

        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "variants": records,
        }

        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        os.replace(temporary, self._path)
