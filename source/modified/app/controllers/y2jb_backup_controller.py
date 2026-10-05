import threading
from typing import Callable, Dict, Iterable, Optional

from app.catalogs.y2jb_backup_catalog import Y2JB_BACKUP_VARIANTS
from app.models.y2jb_backup import (
    Y2JBBackupProgress,
    Y2JBBackupResult,
    Y2JBBackupVariant,
)
from app.repositories.y2jb_release_repository import Y2JBReleaseRepository
from app.services.y2jb.y2jb_backup_service import Y2JBBackupService
from app.services.y2jb.y2jb_release_update_service import Y2JBReleaseUpdateService
from app.services.releases.release_version_policy import (
    is_valid_automatic_release_resolution,
)


class UnknownY2JBBackupVariantError(ValueError):
    pass


class Y2JBBackupController:
    def __init__(
        self,
        service: Y2JBBackupService,
        *,
        release_updater: Optional[Y2JBReleaseUpdateService] = None,
        release_repository: Optional[Y2JBReleaseRepository] = None,
    ):
        self._service = service
        self._release_updater = release_updater
        self._release_repository = release_repository
        self._base_variants = tuple(Y2JB_BACKUP_VARIANTS)
        loaded = (
            release_repository.load(self._base_variants)
            if release_repository is not None
            else self._base_variants
        )
        self._variants = {variant.key: variant for variant in loaded}
        self._catalog_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._release_check_completed = self._release_updater is None

    @property
    def refresh_complete(self) -> bool:
        with self._refresh_lock:
            return self._release_check_completed

    def begin_refresh_cycle(self) -> None:
        """Libera nova consulta sem descartar a última resolução utilizável."""
        with self._refresh_lock:
            self._release_check_completed = self._release_updater is None

    def variants(self) -> Iterable[Y2JBBackupVariant]:
        with self._catalog_lock:
            return tuple(self._variants.values())

    def get_variant(self, key: str) -> Y2JBBackupVariant:
        with self._catalog_lock:
            try:
                return self._variants[key]
            except KeyError as exc:
                raise UnknownY2JBBackupVariantError(key) from exc

    def current_release_version(self) -> str:
        versions = {variant.release_version for variant in self.variants() if variant.release_version}
        return next(iter(versions)) if len(versions) == 1 else ""

    def ensure_latest_release_checked(self) -> tuple[Y2JBBackupVariant, ...]:
        """Consulta uma vez por ciclo e substitui o catálogo completo atomicamente."""
        with self._refresh_lock:
            if self._release_check_completed:
                return tuple(self.variants())

            current = tuple(self.variants())
            resolved = current
            try:
                if self._release_updater is not None:
                    resolved = self._release_updater.resolve_latest(current)
            except Exception:
                return tuple(self.variants())

            if {v.key for v in resolved} != {v.key for v in self._base_variants}:
                return tuple(self.variants())

            current_by_key = {variant.key: variant for variant in current}
            base_by_key = {variant.key: variant for variant in self._base_variants}
            if any(
                not is_valid_automatic_release_resolution(
                    current_by_key[variant.key].url,
                    variant.url,
                )
                or not is_valid_automatic_release_resolution(
                    base_by_key[variant.key].url,
                    variant.url,
                )
                for variant in resolved
            ):
                self._release_check_completed = True
                return tuple(self.variants())

            with self._catalog_lock:
                self._variants = {variant.key: variant for variant in resolved}

            if self._release_repository is not None:
                try:
                    self._release_repository.save(self._base_variants, resolved)
                except (OSError, ValueError):
                    pass

            self._release_check_completed = True
            return tuple(self.variants())

    def run(
        self,
        key: str,
        *,
        is_android: bool,
        progress: Optional[Callable[[Y2JBBackupProgress], None]] = None,
    ) -> Y2JBBackupResult:
        self.ensure_latest_release_checked()
        variant = self.get_variant(key)
        return self._service.execute(
            variant=variant,
            is_android=is_android,
            progress=progress,
        )
