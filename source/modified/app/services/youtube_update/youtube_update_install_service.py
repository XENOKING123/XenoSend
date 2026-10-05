from __future__ import annotations

import ftplib
import socket
import time
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

from app.models.payload import PayloadProgress, PayloadSource
from app.models.youtube_update import (
    YOUTUBE_UPDATE_TARGET_DIR,
    YOUTUBE_UPDATE_TARGET_NAME,
    YouTubeUpdateProgress,
    YouTubeUpdateResult,
    YouTubeUpdateSource,
)
from app.services.payload.payload_tcp_sender import PayloadTcpSender
from app.services.youtube_update.youtube_update_file_service import YouTubeUpdateFileService

if TYPE_CHECKING:
    from app.services.payload.payload_file_service import PayloadFileService


ProgressCallback = Callable[[YouTubeUpdateProgress], None]


class YouTubeUpdateInstallService:
    FTP_PORT = 2121
    FTP_START_TIMEOUT_SECONDS = 30.0
    FTP_PROBE_TIMEOUT_SECONDS = 0.5
    FTP_BLOCK_SIZE = 65536

    def __init__(
        self,
        *,
        file_service: YouTubeUpdateFileService,
        ftpsrv_file_service: 'PayloadFileService',
        payload_sender: PayloadTcpSender,
        ftp_factory=None,
        socket_create_connection=None,
        sleep=time.sleep,
        monotonic=time.monotonic,
    ):
        self._file_service = file_service
        self._ftpsrv_file_service = ftpsrv_file_service
        self._payload_sender = payload_sender
        self._ftp_factory = ftp_factory or ftplib.FTP
        self._socket_create_connection = socket_create_connection or socket.create_connection
        self._sleep = sleep
        self._monotonic = monotonic

    def local_update_directory(self, *, is_android: bool) -> Path:
        return self._file_service.local_update_directory(is_android=is_android)

    def list_local_updates(self, *, is_android: bool) -> tuple[Path, ...]:
        return self._file_service.list_local_updates(is_android=is_android)

    def install_remote(
        self,
        *,
        source: YouTubeUpdateSource,
        ftpsrv_source: PayloadSource,
        host: str,
        loader_port: int,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
    ) -> YouTubeUpdateResult:
        self._ensure_ftpsrv(
            source=ftpsrv_source,
            host=host,
            loader_port=loader_port,
            is_android=is_android,
            progress=progress,
        )
        download0_path = self._file_service.prepare_remote(
            source=source,
            is_android=is_android,
            progress=progress,
        )
        return self._upload_prepared_update(
            label=source.label,
            local_path=download0_path,
            remote_dir=source.remote_dir,
            remote_name=source.remote_name,
            host=host,
            progress=progress,
        )

    def install_local(
        self,
        *,
        label: str,
        local_path: Path,
        ftpsrv_source: PayloadSource,
        host: str,
        loader_port: int,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
    ) -> YouTubeUpdateResult:
        self._ensure_ftpsrv(
            source=ftpsrv_source,
            host=host,
            loader_port=loader_port,
            is_android=is_android,
            progress=progress,
        )
        download0_path = self._file_service.prepare_local(
            path=Path(local_path),
            is_android=is_android,
            progress=progress,
        )
        return self._upload_prepared_update(
            label=str(label or Path(local_path).stem).strip(),
            local_path=download0_path,
            remote_dir=YOUTUBE_UPDATE_TARGET_DIR,
            remote_name=YOUTUBE_UPDATE_TARGET_NAME,
            host=host,
            progress=progress,
        )

    def _upload_prepared_update(
        self,
        *,
        label: str,
        local_path: Path,
        remote_dir: str,
        remote_name: str,
        host: str,
        progress: Optional[ProgressCallback],
    ) -> YouTubeUpdateResult:
        uploaded = self._upload_download0(
            host=host,
            remote_dir=remote_dir,
            remote_name=remote_name,
            local_path=local_path,
            progress=progress,
        )
        return YouTubeUpdateResult(
            label=label,
            local_path=Path(local_path),
            remote_path=f"{str(remote_dir).rstrip('/')}/{remote_name}",
            bytes_uploaded=uploaded,
        )

    def _ensure_ftpsrv(
        self,
        *,
        source: PayloadSource,
        host: str,
        loader_port: int,
        is_android: bool,
        progress: Optional[ProgressCallback],
    ) -> None:
        if self._is_port_open(host, self.FTP_PORT, timeout=self.FTP_PROBE_TIMEOUT_SECONDS):
            self._emit(progress, 'FTPsrv já ativo.', 100)
            return

        self._emit(progress, 'Preparando FTPsrv...', None)
        ftpsrv_path = self._ftpsrv_file_service.prepare_remote(
            source=source,
            is_android=is_android,
            progress=self._payload_progress_adapter(progress, 'FTPsrv'),
        )

        self._emit(progress, 'Subindo FTPsrv via loader...', None)
        self._payload_sender.send(
            host=host,
            port=loader_port,
            payload_path=ftpsrv_path,
            progress=self._payload_progress_adapter(progress, 'FTPsrv'),
        )

        self._emit(progress, 'Aguardando FTPsrv...', None)
        deadline = self._monotonic() + self.FTP_START_TIMEOUT_SECONDS
        while self._monotonic() < deadline:
            if self._is_port_open(host, self.FTP_PORT, timeout=self.FTP_PROBE_TIMEOUT_SECONDS):
                self._emit(progress, 'FTPsrv ativo.', 100)
                return
            self._sleep(0.5)
        raise RuntimeError('FTPsrv não respondeu na porta 2121.')

    def _upload_download0(
        self,
        *,
        host: str,
        remote_dir: str,
        remote_name: str,
        local_path: Path,
        progress: Optional[ProgressCallback],
    ) -> int:
        path = Path(local_path)
        if not path.is_file():
            raise RuntimeError(f'Arquivo não encontrado: {path}')
        total = path.stat().st_size
        if total <= 0:
            raise RuntimeError('download0.dat está vazio.')

        self._emit(progress, 'Copiando download0.dat para o PS5...', 0)
        ftp = self._ftp_factory()
        uploaded = 0
        last_bucket = -1

        def on_chunk(data: bytes) -> None:
            nonlocal uploaded, last_bucket
            uploaded += len(data)
            percent = min(100, int(uploaded * 100 / total))
            bucket = percent // 5
            if bucket != last_bucket:
                last_bucket = bucket
                self._emit(progress, 'Copiando download0.dat para o PS5...', percent)

        try:
            ftp.connect(host, self.FTP_PORT, timeout=10)
            try:
                ftp.login()
            except Exception:
                ftp.login('anonymous', 'anonymous@')
            ftp.set_pasv(True)
            self._ensure_ftp_dir(ftp, remote_dir)
            try:
                ftp.delete(remote_name)
            except Exception:
                pass
            with path.open('rb') as handle:
                ftp.storbinary(
                    f'STOR {remote_name}',
                    handle,
                    blocksize=self.FTP_BLOCK_SIZE,
                    callback=on_chunk,
                )
        finally:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass

        self._emit(progress, 'Update do YouTube aplicado.', 100)
        return uploaded

    def _is_port_open(self, host: str, port: int, timeout: float) -> bool:
        try:
            with self._socket_create_connection((str(host), int(port)), timeout=float(timeout)):
                return True
        except Exception:
            return False

    @staticmethod
    def _ensure_ftp_dir(ftp, remote_dir: str) -> None:
        path = str(remote_dir or '').strip('/')
        try:
            ftp.cwd('/')
        except Exception:
            pass
        for part in path.split('/'):
            if not part:
                continue
            try:
                ftp.cwd(part)
            except Exception:
                try:
                    ftp.mkd(part)
                except Exception:
                    pass
                ftp.cwd(part)

    @staticmethod
    def _payload_progress_adapter(progress: Optional[ProgressCallback], label: str):
        if progress is None:
            return None

        def adapter(event: PayloadProgress) -> None:
            message = str(event.message or '').replace('payload', label).replace('Payload', label)
            progress(YouTubeUpdateProgress(message=message, percent=event.percent))

        return adapter

    @staticmethod
    def _emit(callback: Optional[ProgressCallback], message: str, percent: Optional[int]) -> None:
        if callback is not None:
            callback(YouTubeUpdateProgress(message=message, percent=percent))
