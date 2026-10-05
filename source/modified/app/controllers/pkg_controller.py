from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

from app.catalogs.pkg_catalog import PKG_SOURCES
from app.models.connection_settings import ConnectionSettings
from app.models.pkg import PkgInstallResult, PkgMenuEntry, PkgProgress, PkgSource
from app.repositories.connection_settings_repository import ConnectionSettingsRepository
from app.repositories.pkg_remote_catalog_repository import PkgRemoteCatalogRepository
from app.repositories.pkg_source_repository import PkgSourceRepository
from app.services.pkg.pkg_catalog_update_service import PkgCatalogUpdateService
from app.services.platform.local_folder_opener import LocalFolderOpener
from app.services.releases.release_version_policy import (
    enforce_automatic_source_floor,
    enforce_catalog_source_floor,
)

if TYPE_CHECKING:
    from app.services.pkg.kstuff_dependency_service import KstuffDependencyService
    from app.services.pkg.pkg_install_service import PkgInstallService
    from app.services.pkg.pkg_release_update_service import PkgReleaseUpdateService


class InvalidPkgConnectionError(ValueError):
    pass


class UnknownPkgError(KeyError):
    pass


class PkgController:
    def __init__(
        self,
        service: PkgInstallService,
        settings_repository: ConnectionSettingsRepository,
        *,
        kstuff: KstuffDependencyService,
        release_updater: Optional[PkgReleaseUpdateService] = None,
        source_repository: Optional[PkgSourceRepository] = None,
        catalog_updater: Optional[PkgCatalogUpdateService] = None,
        catalog_repository: Optional[PkgRemoteCatalogRepository] = None,
        folder_opener: Optional[LocalFolderOpener] = None,
    ):
        self._service = service
        self._settings_repository = settings_repository
        self._kstuff = kstuff
        self._release_updater = release_updater
        self._source_repository = source_repository
        self._catalog_updater = catalog_updater
        self._catalog_repository = catalog_repository
        self._folder_opener = folder_opener or LocalFolderOpener()
        self._base_sources = self._load_base_sources()
        loaded = self._load_resolved_sources(self._base_sources)
        self._sources: Dict[str, PkgSource] = {source.key: source for source in loaded}
        self._catalog_lock = threading.RLock()
        self._check_lock = threading.Lock()
        self._catalog_check_completed = self._catalog_updater is None
        self._release_check_completed = self._release_updater is None

    @property
    def refresh_complete(self) -> bool:
        with self._check_lock:
            return (
                self._catalog_check_completed
                and self._release_check_completed
                and self._kstuff.refresh_complete
            )

    def begin_refresh_cycle(self) -> None:
        """Libera uma nova leitura remota sem alterar o catálogo já utilizável."""
        with self._check_lock:
            self._catalog_check_completed = self._catalog_updater is None
            self._release_check_completed = self._release_updater is None
            self._kstuff.begin_refresh_cycle()

    def ensure_dependencies_checked(self) -> tuple[PkgSource, ...]:
        with self._check_lock:
            if (
                self._catalog_check_completed
                and self._release_check_completed
                and self._kstuff.refresh_complete
            ):
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
                                self._catalog_repository.save(
                                    self._catalog_updater.catalog_url, base_sources
                                )
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
                    resolved = enforce_automatic_source_floor(
                        self._base_sources, resolved
                    )
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

            if not self._kstuff.refresh_complete:
                self._kstuff.ensure_latest_checked()
            return self.sources()

    def sources(self) -> tuple[PkgSource, ...]:
        with self._catalog_lock:
            return tuple(self._sources[source.key] for source in self._base_sources)

    def _load_base_sources(self) -> tuple[PkgSource, ...]:
        embedded_sources = tuple(PKG_SOURCES)
        if self._catalog_updater is None or self._catalog_repository is None:
            return embedded_sources
        cached_sources = self._catalog_repository.load(self._catalog_updater.catalog_url)
        if cached_sources:
            return self._protect_catalog_sources(cached_sources)
        return embedded_sources

    def _load_resolved_sources(self, base_sources: tuple[PkgSource, ...]) -> tuple[PkgSource, ...]:
        loaded = (
            self._source_repository.load(base_sources)
            if self._source_repository
            else base_sources
        )
        return enforce_automatic_source_floor(base_sources, loaded)

    @staticmethod
    def _protect_catalog_sources(
        sources: tuple[PkgSource, ...],
    ) -> tuple[PkgSource, ...]:
        return enforce_catalog_source_floor(PKG_SOURCES, sources)

    @staticmethod
    def _same_base_sources(left: tuple[PkgSource, ...], right: tuple[PkgSource, ...]) -> bool:
        return tuple(
            (source.key, source.url, source.name_override) for source in left
        ) == tuple(
            (source.key, source.url, source.name_override)
            for source in right
        )

    def menu_entries(self, *, is_android: bool) -> tuple[PkgMenuEntry, ...]:
        entries = [
            PkgMenuEntry(
                key=f"remote:{source.key}",
                label=source.label,
                kind="remote",
                source_key=source.key,
            )
            for source in self.sources()
        ]
        for path in self._service.list_local_pkgs(is_android=is_android):
            entries.append(
                PkgMenuEntry(
                    key=f"local:{path}",
                    label=path.stem,
                    kind="local",
                    local_path=path,
                )
            )
        return tuple(entries)

    def open_local_pkg_folder(self, *, is_android: bool) -> Path:
        folder = self._service.local_pkg_directory(is_android=is_android)
        self._folder_opener.open(folder, is_android=is_android)
        return folder

    def install(
        self,
        entry: PkgMenuEntry,
        *,
        host: str,
        raw_port: str,
        is_android: bool,
        progress=None,
    ) -> PkgInstallResult:
        host_value, loader_port = self._validate_connection(host, raw_port)
        self._settings_repository.save(
            ConnectionSettings(host=host_value, port=loader_port)
        )
        self.ensure_dependencies_checked()

        if entry.kind == "remote":
            source = self._get_source(entry.source_key)
            return self._service.install_remote(
                source=source,
                host=host_value,
                loader_port=loader_port,
                is_android=is_android,
                progress=progress,
            )

        if entry.kind == "local" and entry.local_path is not None:
            return self._service.install_local(
                label=entry.label,
                pkg_path=entry.local_path,
                host=host_value,
                loader_port=loader_port,
                is_android=is_android,
                progress=progress,
            )

        raise UnknownPkgError(entry.key)

    def _get_source(self, key: str) -> PkgSource:
        with self._catalog_lock:
            try:
                return self._sources[key]
            except KeyError as exc:
                raise UnknownPkgError(key) from exc

    @classmethod
    def _validate_connection(cls, host: str, raw_port: str) -> tuple[str, int]:
        host_value = str(host or "").strip()
        if not host_value:
            raise InvalidPkgConnectionError("host_required")
        value = str(raw_port or "").strip() or "9021"
        try:
            port = int(value)
        except ValueError as exc:
            raise InvalidPkgConnectionError("port_invalid") from exc
        if not 1 <= port <= 65535:
            raise InvalidPkgConnectionError("port_out_of_range")
        return host_value, port
