import threading
from pathlib import Path
from typing import Callable, Optional

from app.catalogs.pkg_catalog import KSTUFF_BASE_URL
from app.repositories.kstuff_release_repository import KstuffReleaseRepository
from app.services.download.http_download_service import HttpDownloadService
from app.services.pkg.kstuff_release_update_service import KstuffReleaseUpdateService
from app.services.releases.release_version_policy import is_valid_automatic_release_resolution


ProgressCallback = Callable[[object], None]


class KstuffDependencyService:
    """Keeps Kstuff Lite internal, cached and independently updateable."""

    def __init__(
        self,
        *,
        downloader: HttpDownloadService,
        release_updater: KstuffReleaseUpdateService,
        repository: KstuffReleaseRepository,
        base_url: str = KSTUFF_BASE_URL,
    ):
        self._downloader = downloader
        self._release_updater = release_updater
        self._repository = repository
        self._base_url = base_url.strip()
        self._resolved_url = repository.load(self._base_url)
        self._check_lock = threading.Lock()
        self._check_completed = False

    @property
    def resolved_url(self) -> str:
        return self._resolved_url

    @property
    def refresh_complete(self) -> bool:
        with self._check_lock:
            return self._check_completed

    def begin_refresh_cycle(self) -> None:
        """Libera nova consulta sem descartar a última URL utilizável."""
        with self._check_lock:
            self._check_completed = False

    def ensure_latest_checked(self) -> str:
        with self._check_lock:
            if self._check_completed:
                return self._resolved_url
            try:
                resolved = self._release_updater.resolve_latest(self._resolved_url)
            except Exception:
                return self._resolved_url
            if not (
                is_valid_automatic_release_resolution(self._resolved_url, resolved)
                and is_valid_automatic_release_resolution(self._base_url, resolved)
            ):
                self._check_completed = True
                return self._resolved_url
            self._resolved_url = resolved
            try:
                self._repository.save(self._base_url, self._resolved_url)
            except (OSError, ValueError):
                pass
            self._check_completed = True
            return self._resolved_url

    def prepare(
        self,
        *,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
    ) -> Path:
        url = self.ensure_latest_checked()
        return self._downloader.download(
            filename="kstuff.elf",
            url=url,
            is_android=is_android,
            progress=progress,
            display_name="Kstuff Lite",
        )
