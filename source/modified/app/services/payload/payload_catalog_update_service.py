from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any, Optional
from urllib.parse import unquote, urlparse

try:
    import requests
except ImportError:
    requests = None

from app.catalogs.payload_catalog import build_payload_source
from app.models.payload import (
    PAYLOAD_ALLOWED_EXTENSIONS,
    PAYLOAD_ARCHIVE_EXTENSIONS,
    PayloadSource,
)
from app.services.catalog.catalog_contract import KIND_PAYLOADS, normalize_catalog_items
from app.services.payload.payload_url_presentation import normalize_payload_url


class InvalidPayloadCatalogError(ValueError):
    pass


class PayloadCatalogUpdateService:
    """Baixa e valida o catálogo remoto v2 de Payloads."""

    REQUEST_TIMEOUT = (3.05, 8)
    MAX_PAYLOADS = 200

    def __init__(self, catalog_url: str, session: Optional[Any] = None):
        self.catalog_url = normalize_payload_url(catalog_url)
        if session is None:
            if requests is None:
                raise RuntimeError('payload_catalog_requests_unavailable')
            session = requests.Session()
        self._session = session
        try:
            self._session.headers.update({'User-Agent': 'PS5-Send-PKG-Payload'})
        except Exception:
            pass

    def resolve_remote_sources(self) -> tuple[PayloadSource, ...]:
        response = self._session.get(self.catalog_url, timeout=self.REQUEST_TIMEOUT)
        response.raise_for_status()
        return self.parse_catalog(self._response_payload(response))

    @classmethod
    def parse_catalog(cls, payload: object) -> tuple[PayloadSource, ...]:
        try:
            items = normalize_catalog_items(
                payload,
                expected_kind=KIND_PAYLOADS,
                url_normalizer=cls.normalize_payload_catalog_url,
                max_items=cls.MAX_PAYLOADS,
            )
        except ValueError as exc:
            raise InvalidPayloadCatalogError(str(exc)) from exc
        return tuple(
            build_payload_source(
                item['url'],
                key=item['key'],
                name_override=item.get('name_override', ''),
            )
            for item in items
        )

    @staticmethod
    def _response_payload(response) -> object:
        try:
            return response.json()
        except Exception:
            body = str(getattr(response, 'text', '') or '')
            return json.loads(body)

    @classmethod
    def normalize_payload_catalog_url(cls, raw_url: object) -> str:
        if not isinstance(raw_url, str):
            raise ValueError('payload_catalog_url_invalid')
        url = normalize_payload_url(raw_url)
        cls._require_supported_payload_url(url)
        return url

    @staticmethod
    def _require_supported_payload_url(url: str) -> None:
        parsed = urlparse(url)
        filename = unquote(PurePosixPath(parsed.path).name).strip().lower()
        supported = PAYLOAD_ALLOWED_EXTENSIONS + PAYLOAD_ARCHIVE_EXTENSIONS
        if not filename.endswith(supported):
            raise ValueError('payload_catalog_extension_invalid')
