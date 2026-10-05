from __future__ import annotations

import threading
from pathlib import Path, PurePosixPath
from typing import Dict, Optional
from urllib.parse import unquote, urlparse

from app.catalogs.youtube_update_catalog import (
    REMOTE_YOUTUBE_UPDATE_CATALOG_URL,
    YOUTUBE_UPDATE_SOURCES,
)
from app.models.connection_settings import ConnectionSettings
from app.models.payload import PayloadSource
from app.models.youtube_update import (
    YouTubeUpdateMenuEntry,
    YouTubeUpdateProgress,
    YouTubeUpdateResult,
    YouTubeUpdateSource,
)
from app.repositories.connection_settings_repository import ConnectionSettingsRepository
from app.repositories.youtube_update_remote_catalog_repository import (
    YouTubeUpdateRemoteCatalogRepository,
)
from app.repositories.youtube_update_source_repository import (
    YouTubeUpdateSourceRepository,
)
from app.services.platform.local_folder_opener import LocalFolderOpener
from app.services.releases.release_version_policy import (
    enforce_automatic_source_floor,
    enforce_catalog_source_floor,
)
from app.services.youtube_update.youtube_update_catalog_update_service import (
    YouTubeUpdateCatalogUpdateService,
)
from app.services.youtube_update.youtube_update_release_update_service import (
    YouTubeUpdateReleaseUpdateService,
)


class InvalidYouTubeUpdateConnectionError(ValueError):
    pass


class UnknownYouTubeUpdateError(KeyError):
    pass


class YouTubeUpdateController:
    def __init__(
        self,
        service,
        settings_repository: ConnectionSettingsRepository,
        *,
        payload_controller,
        catalog_updater: Optional[YouTubeUpdateCatalogUpdateService] = None,
        catalog_repository: Optional[YouTubeUpdateRemoteCatalogRepository] = None,
        release_updater: Optional[YouTubeUpdateReleaseUpdateService] = None,
        source_repository: Optional[YouTubeUpdateSourceRepository] = None,
        folder_opener: Optional[LocalFolderOpener] = None,
        account_activation_service=None,
    ):
        self._service = service
        self._settings_repository = settings_repository
        self._payload_controller = payload_controller
        self._account_activation_service = account_activation_service
        self._catalog_updater = catalog_updater
        self._catalog_repository = catalog_repository
        self._release_updater = release_updater
        self._source_repository = source_repository
        self._folder_opener = folder_opener or LocalFolderOpener()
        self._catalog_lock = threading.RLock()
        self._base_sources = self._load_base_sources()
        loaded = self._load_resolved_sources(self._base_sources)
        self._sources = {source.key: source for source in loaded}
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

    @property
    def catalog_url(self) -> str:
        return self._catalog_updater.catalog_url if self._catalog_updater is not None else REMOTE_YOUTUBE_UPDATE_CATALOG_URL

    def ensure_latest_sources_checked(self) -> tuple[YouTubeUpdateSource, ...]:
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

    def sources(self) -> tuple[YouTubeUpdateSource, ...]:
        with self._catalog_lock:
            return tuple(self._sources[source.key] for source in self._base_sources)

    def menu_entries(self, *, is_android: bool) -> tuple[YouTubeUpdateMenuEntry, ...]:
        entries = [
            YouTubeUpdateMenuEntry(
                key=f"remote:{source.key}",
                label=source.label,
                kind="remote",
                source_key=source.key,
            )
            for source in self.sources()
        ]
        for path in self._service.list_local_updates(is_android=is_android):
            entries.append(
                YouTubeUpdateMenuEntry(
                    key=f"local:{path}",
                    label=path.stem,
                    kind="local",
                    local_path=path,
                )
            )
        return tuple(entries)

    def open_local_update_folder(self, *, is_android: bool) -> Path:
        folder = self._service.local_update_directory(is_android=is_android)
        self._folder_opener.open(folder, is_android=is_android)
        return folder

    def install(
        self,
        entry: YouTubeUpdateMenuEntry,
        *,
        host: str,
        raw_port: str,
        is_android: bool,
        progress=None,
    ) -> YouTubeUpdateResult:
        host_value, loader_port = self._validate_connection(host, raw_port)
        self._settings_repository.save(ConnectionSettings(host=host_value, port=loader_port))
        self.ensure_latest_sources_checked()

        ftpsrv_source = self._find_official_ftpsrv_source()
        if entry.kind == "remote":
            source = self._get_source(entry.source_key)
            return self._service.install_remote(
                source=source,
                ftpsrv_source=ftpsrv_source,
                host=host_value,
                loader_port=loader_port,
                is_android=is_android,
                progress=progress,
            )
        if entry.kind == "local" and entry.local_path is not None:
            return self._service.install_local(
                label=entry.label,
                local_path=entry.local_path,
                ftpsrv_source=ftpsrv_source,
                host=host_value,
                loader_port=loader_port,
                is_android=is_android,
                progress=progress,
            )
        raise UnknownYouTubeUpdateError(entry.key)

    def activate_current_account(
        self,
        *,
        host: str,
        raw_port: str,
        progress=None,
    ):
        if self._account_activation_service is None:
            raise RuntimeError("Serviço interno de ativação não está configurado.")
        host_value, loader_port = self._validate_connection(host, raw_port)
        self._settings_repository.save(ConnectionSettings(host=host_value, port=loader_port))
        return self._account_activation_service.activate_current_account(
            host=host_value,
            loader_port=loader_port,
            progress=progress,
        )

    def _get_source(self, key: str) -> YouTubeUpdateSource:
        with self._catalog_lock:
            try:
                return self._sources[key]
            except KeyError as exc:
                raise UnknownYouTubeUpdateError(key) from exc

    def _find_official_ftpsrv_source(self) -> PayloadSource:
        try:
            sources = self._payload_controller.ensure_latest_sources_checked()
        except Exception:
            sources = self._payload_controller.sources()

        for source in sources:
            if self._is_official_ftpsrv(source.url):
                return source
        raise RuntimeError("FTPsrv oficial não encontrado no catálogo de payloads.")

    @staticmethod
    def _is_official_ftpsrv(url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        path_parts = [unquote(part).strip().lower() for part in parsed.path.split("/") if part.strip()]
        if len(path_parts) < 5:
            return False
        owner = path_parts[0]
        repo = path_parts[1]
        asset = PurePosixPath(parsed.path).name.lower()
        return owner == "ps5-payload-dev" and repo == "ftpsrv" and asset.endswith(".elf")

    def _load_base_sources(self) -> tuple[YouTubeUpdateSource, ...]:
        embedded_sources = tuple(YOUTUBE_UPDATE_SOURCES)
        if self._catalog_updater is None or self._catalog_repository is None:
            return embedded_sources
        cached_sources = self._catalog_repository.load(self._catalog_updater.catalog_url)
        if cached_sources:
            return self._protect_catalog_sources(cached_sources)
        return embedded_sources

    def _load_resolved_sources(self, base_sources: tuple[YouTubeUpdateSource, ...]) -> tuple[YouTubeUpdateSource, ...]:
        if self._source_repository is None:
            return base_sources
        loaded = self._source_repository.load(base_sources)
        return enforce_automatic_source_floor(base_sources, loaded)

    @staticmethod
    def _protect_catalog_sources(
        sources: tuple[YouTubeUpdateSource, ...],
    ) -> tuple[YouTubeUpdateSource, ...]:
        return enforce_catalog_source_floor(YOUTUBE_UPDATE_SOURCES, sources)

    @staticmethod
    def _same_base_sources(
        left: tuple[YouTubeUpdateSource, ...],
        right: tuple[YouTubeUpdateSource, ...],
    ) -> bool:
        return tuple((source.key, source.url, source.name_override) for source in left) == tuple(
            (source.key, source.url, source.name_override) for source in right
        )

    @classmethod
    def _validate_connection(cls, host: str, raw_port: str) -> tuple[str, int]:
        host_value = str(host or "").strip()
        if not host_value:
            raise InvalidYouTubeUpdateConnectionError("host_required")
        value = str(raw_port or "").strip() or "9021"
        try:
            port = int(value)
        except ValueError as exc:
            raise InvalidYouTubeUpdateConnectionError("port_invalid") from exc
        if not 1 <= port <= 65535:
            raise InvalidYouTubeUpdateConnectionError("port_out_of_range")
        return host_value, port
