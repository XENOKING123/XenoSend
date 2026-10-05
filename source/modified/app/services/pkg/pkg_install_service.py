import time
from pathlib import Path
from typing import Callable, Optional

from app.models.pkg import PkgInstallResult, PkgProgress, PkgSource
from app.services.payload.payload_tcp_sender import PayloadTcpSender
from app.services.pkg.kstuff_dependency_service import KstuffDependencyService
from app.services.pkg.pkg_file_service import PkgFileService
from app.services.pkg.pkg_installer_client import PkgInstallerClient


ProgressCallback = Callable[[PkgProgress], None]


class PkgInstallService:
    KSTUFF_SETTLE_SECONDS = 2.5

    def __init__(
        self,
        *,
        file_service: PkgFileService,
        kstuff: KstuffDependencyService,
        payload_sender: PayloadTcpSender,
        installer: PkgInstallerClient,
        sleep=time.sleep,
    ):
        self._file_service = file_service
        self._kstuff = kstuff
        self._payload_sender = payload_sender
        self._installer = installer
        self._sleep = sleep

    def local_pkg_directory(self, *, is_android: bool) -> Path:
        return self._file_service.local_pkg_directory(is_android=is_android)

    def list_local_pkgs(self, *, is_android: bool) -> tuple[Path, ...]:
        return self._file_service.list_local_pkgs(is_android=is_android)

    def install_remote(
        self,
        *,
        source: PkgSource,
        host: str,
        loader_port: int,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
    ) -> PkgInstallResult:
        path = self._file_service.download_remote(
            source=source,
            is_android=is_android,
            progress=self._download_progress_adapter(progress),
        )
        return self._install_path(
            label=source.label,
            pkg_path=path,
            host=host,
            loader_port=loader_port,
            is_android=is_android,
            progress=progress,
        )

    def install_local(
        self,
        *,
        label: str,
        pkg_path: Path,
        host: str,
        loader_port: int,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
    ) -> PkgInstallResult:
        path = Path(pkg_path)
        if not path.is_file() or path.suffix.lower() != ".pkg":
            raise RuntimeError("Arquivo PKG local inválido ou indisponível.")
        return self._install_path(
            label=label,
            pkg_path=path,
            host=host,
            loader_port=loader_port,
            is_android=is_android,
            progress=progress,
        )

    def _install_path(
        self,
        *,
        label: str,
        pkg_path: Path,
        host: str,
        loader_port: int,
        is_android: bool,
        progress: Optional[ProgressCallback],
    ) -> PkgInstallResult:
        self._emit(progress, "Preparando suporte para fPKG...", None)
        kstuff_path = self._kstuff.prepare(
            is_android=is_android,
            progress=self._download_progress_adapter(progress),
        )

        self._emit(progress, "Aplicando suporte para fPKG...", None)
        self._payload_sender.send(
            host=host,
            port=loader_port,
            payload_path=kstuff_path,
            progress=None,
        )

        self._sleep(self.KSTUFF_SETTLE_SECONDS)

        self._installer.ensure_running(
            host=host,
            loader_port=loader_port,
            progress=progress,
        )

        self._installer.upload(
            host=host,
            pkg_path=pkg_path,
            display_name=pkg_path.name,
            progress=progress,
        )

        status = self._installer.wait_for_result(host=host, progress=progress)
        return PkgInstallResult(
            label=label,
            local_path=pkg_path,
            content_id=str(status.get("contentId") or "").strip(),
            installer_via=str(status.get("via") or "").strip(),
        )

    @staticmethod
    def _download_progress_adapter(progress: Optional[ProgressCallback]):
        if progress is None:
            return None

        def adapter(event) -> None:
            progress(PkgProgress(message=str(event.message), percent=event.percent))

        return adapter

    @staticmethod
    def _emit(callback: Optional[ProgressCallback], message: str, percent) -> None:
        if callback is not None:
            callback(PkgProgress(message=message, percent=percent))
