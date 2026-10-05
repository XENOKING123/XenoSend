from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Dict, Optional, TYPE_CHECKING

from app.catalogs.payload_catalog import PAYLOAD_SOURCES
from app.models.connection_settings import ConnectionSettings
from app.models.payload import (
    PayloadExecutionResult,
    PayloadMenuEntry,
    PayloadProgress,
    PayloadSource,
)
from app.repositories.connection_settings_repository import ConnectionSettingsRepository
from app.repositories.payload_remote_catalog_repository import PayloadRemoteCatalogRepository
from app.repositories.payload_source_repository import PayloadSourceRepository
from app.services.payload.payload_catalog_update_service import PayloadCatalogUpdateService
from app.services.platform.local_folder_opener import LocalFolderOpener
from app.services.releases.release_version_policy import (
    enforce_automatic_source_floor,
    enforce_catalog_source_floor,
)

if TYPE_CHECKING:
    from app.services.payload.payload_execution_service import PayloadExecutionService
    from app.services.payload.payload_release_update_service import PayloadReleaseUpdateService


class UnknownPayloadError(KeyError):
    pass


class InvalidPayloadConnectionError(ValueError):
    pass


class PayloadController:
    def __init__(
        self,
        service: PayloadExecutionService,
        settings_repository: ConnectionSettingsRepository,
        *,
        release_updater: Optional[PayloadReleaseUpdateService] = None,
        source_repository: Optional[PayloadSourceRepository] = None,
        catalog_updater: Optional[PayloadCatalogUpdateService] = None,
        catalog_repository: Optional[PayloadRemoteCatalogRepository] = None,
        folder_opener: Optional[LocalFolderOpener] = None,
    ):
        self._service = service
        self._settings_repository = settings_repository
        self._release_updater = release_updater
        self._source_repository = source_repository
        self._catalog_updater = catalog_updater
        self._catalog_repository = catalog_repository
        self._folder_opener = folder_opener or LocalFolderOpener()
        self._catalog_lock = threading.RLock()
        self._base_sources = self._load_base_sources()
        loaded = self._load_resolved_sources(self._base_sources)
        self._sources: Dict[str, PayloadSource] = {source.key: source for source in loaded}
        self._refresh_lock = threading.Lock()
        self._catalog_check_completed = self._catalog_updater is None
        self._release_check_completed = self._release_updater is None

    @property
    def refresh_complete(self) -> bool:
        with self._refresh_lock:
            return self._catalog_check_completed and self._release_check_completed

    def begin_refresh_cycle(self) -> None:
        """Libera uma nova leitura remota sem alterar o catálogo já utilizável."""
        with self._refresh_lock:
            self._catalog_check_completed = self._catalog_updater is None
            self._release_check_completed = self._release_updater is None

    def ensure_latest_sources_checked(self) -> tuple[PayloadSource, ...]:
        with self._refresh_lock:
            if self._catalog_check_completed and self._release_check_completed:
                return self.sources()
            base_sources = self._base_sources
            if not self._catalog_check_completed and self._catalog_updater is not None:
                try:
                    remote_sources = self._catalog_updater.resolve_remote_sources()
                except Exception:
                    remote_sources = ()
                else:
                    self._catalog_check_completed = True
                    if remote_sources:
                        base_sources = self._protect_catalog_sources(remote_sources)
                        base_sources = enforce_catalog_source_floor(
                            self._base_sources,
                            base_sources,
                        )
                        if self._catalog_repository is not None:
                            try:
                                self._catalog_repository.save(self._catalog_updater.catalog_url, base_sources)
                            except (OSError, ValueError):
                                pass
            if not self._same_base_sources(base_sources, self._base_sources):
                with self._catalog_lock:
                    self._base_sources = base_sources
                    loaded = self._load_resolved_sources(base_sources)
                    self._sources = {source.key: source for source in loaded}
                self._release_check_completed = self._release_updater is None
            if not self._release_check_completed and self._release_updater is not None:
                current = self.sources()
                try:
                    outcome = self._release_updater.resolve_latest_with_status(current)
                    resolved = enforce_automatic_source_floor(current, outcome.items)
                    resolved = enforce_automatic_source_floor(self._base_sources, resolved)
                except Exception:
                    pass
                else:
                    with self._catalog_lock:
                        self._sources = {source.key: source for source in resolved}
                    if self._source_repository is not None:
                        try:
                            self._source_repository.save(self._base_sources, resolved)
                        except (OSError, ValueError):
                            pass
                    self._release_check_completed = outcome.complete
            return self.sources()

    def sources(self) -> tuple[PayloadSource, ...]:
        with self._catalog_lock:
            return tuple(self._sources[source.key] for source in self._base_sources)

    def open_local_payload_folder(self, *, is_android: bool) -> Path:
        folder = self._service.local_payload_directory(is_android=is_android)
        self._folder_opener.open(folder, is_android=is_android)
        return folder

    def menu_entries(self, *, is_android: bool) -> tuple[PayloadMenuEntry, ...]:
        entries = [
            PayloadMenuEntry(
                key=f"remote:{source.key}",
                label=source.label,
                kind="remote",
                source_key=source.key,
            )
            for source in self.sources()
        ]

        for path in self._service.list_local_payloads(is_android=is_android):
            entries.append(
                PayloadMenuEntry(
                    key=f"local:{path}",
                    label=path.stem,
                    kind="local",
                    local_path=path,
                )
            )

        return tuple(entries)

    def execute(
        self,
        entry: PayloadMenuEntry,
        *,
        host: str,
        raw_port: str,
        is_android: bool,
        progress: Optional[Callable[[PayloadProgress], None]] = None,
    ) -> PayloadExecutionResult:
        host_value, port = self._validate_connection(host, raw_port)
        self._settings_repository.save(ConnectionSettings(host=host_value, port=port))

        if entry.kind == "remote":
            self.ensure_latest_sources_checked()
            source = self._get_source(entry.source_key)
            return self._service.execute_remote(
                source=source,
                host=host_value,
                port=port,
                is_android=is_android,
                progress=progress,
            )
        if entry.kind == "local" and entry.local_path is not None:
            return self._service.execute_local(
                label=entry.label,
                local_path=entry.local_path,
                host=host_value,
                port=port,
                progress=progress,
            )
        raise UnknownPayloadError(entry.key)

    def warning_for(self, entry: PayloadMenuEntry, raw_port: str) -> str:
        try:
            port = self._parse_port(raw_port)
        except InvalidPayloadConnectionError:
            return ""

        if entry.kind == "remote":
            source = self._get_source(entry.source_key)
            target = source.url
        else:
            target = str(entry.local_path or "")

        if self._service.should_warn_js_port(target, port):
            return "Payload .js normalmente usa a porta 50000."
        return ""

    def _get_source(self, key: str) -> PayloadSource:
        with self._catalog_lock:
            try:
                return self._sources[key]
            except KeyError as exc:
                raise UnknownPayloadError(key) from exc

    def _load_base_sources(self) -> tuple[PayloadSource, ...]:
        embedded_sources = tuple(PAYLOAD_SOURCES)
        if self._catalog_updater is None or self._catalog_repository is None:
            return embedded_sources
        cached_sources = self._catalog_repository.load(self._catalog_updater.catalog_url)
        if cached_sources:
            return self._protect_catalog_sources(cached_sources)
        return embedded_sources

    def _load_resolved_sources(self, base_sources: tuple[PayloadSource, ...]) -> tuple[PayloadSource, ...]:
        if self._source_repository is None:
            return base_sources
        loaded = self._source_repository.load(base_sources)
        return enforce_automatic_source_floor(base_sources, loaded)

    @staticmethod
    def _protect_catalog_sources(
        sources: tuple[PayloadSource, ...],
    ) -> tuple[PayloadSource, ...]:
        return enforce_catalog_source_floor(PAYLOAD_SOURCES, sources)

    @staticmethod
    def _same_base_sources(
        left: tuple[PayloadSource, ...],
        right: tuple[PayloadSource, ...],
    ) -> bool:
        return tuple((source.key, source.url, source.name_override) for source in left) == tuple(
            (source.key, source.url, source.name_override) for source in right
        )

    @classmethod
    def _validate_connection(cls, host: str, raw_port: str) -> tuple[str, int]:
        host_value = str(host or "").strip()
        if not host_value:
            raise InvalidPayloadConnectionError("host_required")
        return host_value, cls._parse_port(raw_port)

    @staticmethod
    def _parse_port(raw_port: str) -> int:
        value = str(raw_port or "").strip() or "9021"
        try:
            port = int(value)
        except ValueError as exc:
            raise InvalidPayloadConnectionError("port_invalid") from exc
        if not 1 <= port <= 65535:
            raise InvalidPayloadConnectionError("port_out_of_range")
        return port
