from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any, Optional
from urllib.parse import unquote, urlparse

try:
    import requests
except ImportError:
    requests = None

from app.catalogs.youtube_update_catalog import (
    build_youtube_update_source,
    normalize_youtube_update_url,
)
from app.models.youtube_update import (
    YOUTUBE_UPDATE_ALLOWED_EXTENSIONS,
    YouTubeUpdateSource,
)
from app.services.catalog.catalog_contract import KIND_YOUTUBE, normalize_catalog_items


class InvalidYouTubeUpdateCatalogError(ValueError):
    pass


class YouTubeUpdateCatalogUpdateService:
    """Baixa e valida o catálogo remoto v2 de Update Y2JB."""

    REQUEST_TIMEOUT = (3.05, 8)
    MAX_UPDATES = 200

    def __init__(self, catalog_url: str, session: Optional[Any] = None):
        self.catalog_url = str(catalog_url or "").strip()
        parsed = urlparse(self.catalog_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("youtube_update_catalog_url_invalid")
        if session is None:
            if requests is None:
                raise RuntimeError("youtube_update_catalog_requests_unavailable")
            session = requests.Session()
        self._session = session
        try:
            self._session.headers.update({"User-Agent": "PS5-Send-PKG-Payload"})
        except Exception:
            pass

    def resolve_remote_sources(self) -> tuple[YouTubeUpdateSource, ...]:
        response = self._session.get(self.catalog_url, timeout=self.REQUEST_TIMEOUT)
        response.raise_for_status()
        return self.parse_catalog(self._response_payload(response))

    @classmethod
    def parse_catalog(cls, payload: object) -> tuple[YouTubeUpdateSource, ...]:
        try:
            items = normalize_catalog_items(
                payload,
                expected_kind=KIND_YOUTUBE,
                url_normalizer=cls.normalize_youtube_catalog_url,
                max_items=cls.MAX_UPDATES,
            )
        except ValueError as exc:
            raise InvalidYouTubeUpdateCatalogError(str(exc)) from exc
        return tuple(
            build_youtube_update_source(
                item["url"],
                key=item["key"],
                name_override=item.get("name_override", ""),
            )
            for item in items
        )

    @staticmethod
    def _response_payload(response) -> object:
        try:
            return response.json()
        except Exception:
            body = str(getattr(response, "text", "") or "")
            return json.loads(body)

    @classmethod
    def normalize_youtube_catalog_url(cls, raw_url: object) -> str:
        if not isinstance(raw_url, str):
            raise ValueError("youtube_update_catalog_url_invalid")
        url = normalize_youtube_update_url(raw_url)
        parsed = urlparse(url)
        filename = unquote(PurePosixPath(parsed.path).name).strip().lower()
        if not filename.endswith(YOUTUBE_UPDATE_ALLOWED_EXTENSIONS):
            raise ValueError("youtube_update_catalog_extension_invalid")
        return url
