from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any, Optional
from urllib.parse import unquote, urlparse

try:
    import requests
except ImportError:
    requests = None

from app.catalogs.pkg_catalog import build_pkg_source
from app.models.pkg import PKG_ALLOWED_EXTENSIONS, PkgSource
from app.services.catalog.catalog_contract import KIND_PKGS, normalize_catalog_items


class InvalidPkgCatalogError(ValueError):
    pass


class PkgCatalogUpdateService:
    """Baixa e valida o catálogo remoto v2 de PKGs."""

    REQUEST_TIMEOUT = (3.05, 8)
    MAX_PKGS = 200
    VERSION_ENDPOINT_PATTERN = re.compile(r"^(?:latest|v?\d+(?:[._-][a-z0-9]+)*)$", re.IGNORECASE)

    def __init__(self, catalog_url: str, session: Optional[Any] = None):
        self.catalog_url = str(catalog_url or "").strip()
        parsed = urlparse(self.catalog_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("pkg_catalog_url_invalid")
        if session is None:
            if requests is None:
                raise RuntimeError("pkg_catalog_requests_unavailable")
            session = requests.Session()
        self._session = session
        try:
            self._session.headers.update({"User-Agent": "PS5-Send-PKG-Payload"})
        except Exception:
            pass

    def resolve_remote_sources(self) -> tuple[PkgSource, ...]:
        response = self._session.get(self.catalog_url, timeout=self.REQUEST_TIMEOUT)
        response.raise_for_status()
        return self.parse_catalog(self._response_payload(response))

    @classmethod
    def parse_catalog(cls, payload: object) -> tuple[PkgSource, ...]:
        try:
            items = normalize_catalog_items(
                payload,
                expected_kind=KIND_PKGS,
                url_normalizer=cls.normalize_pkg_url,
                max_items=cls.MAX_PKGS,
            )
        except ValueError as exc:
            raise InvalidPkgCatalogError(str(exc)) from exc
        return tuple(
            build_pkg_source(
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
    def normalize_pkg_url(cls, raw_url: object) -> str:
        url = str(raw_url or "").strip()
        if not url:
            raise ValueError("pkg_catalog_url_invalid")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("pkg_catalog_url_invalid")
        filename = unquote(PurePosixPath(parsed.path).name).strip().lower()
        if not filename:
            raise ValueError("pkg_catalog_url_invalid")
        supported_endpoint = cls.VERSION_ENDPOINT_PATTERN.fullmatch(filename) is not None
        if not filename.endswith(PKG_ALLOWED_EXTENSIONS) and not supported_endpoint:
            raise ValueError("pkg_catalog_extension_invalid")
        return url
