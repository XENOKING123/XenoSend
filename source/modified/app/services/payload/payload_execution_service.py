from pathlib import Path
from typing import Callable, Optional

from app.models.payload import PayloadExecutionResult, PayloadProgress, PayloadSource
from app.services.payload.payload_file_service import PayloadFileService
from app.services.payload.payload_tcp_sender import PayloadTcpSender


ProgressCallback = Callable[[PayloadProgress], None]


class PayloadExecutionService:
    def __init__(self, file_service: PayloadFileService, sender: PayloadTcpSender):
        self._file_service = file_service
        self._sender = sender

    def execute_remote(
        self,
        *,
        source: PayloadSource,
        host: str,
        port: int,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
    ) -> PayloadExecutionResult:
        payload_path = self._file_service.prepare_remote(
            source=source,
            is_android=is_android,
            progress=progress,
        )
        return self._send(source.label, payload_path, host, port, progress)

    def execute_local(
        self,
        *,
        label: str,
        local_path: Path,
        host: str,
        port: int,
        progress: Optional[ProgressCallback] = None,
    ) -> PayloadExecutionResult:
        payload_path = self._file_service.validate_local(local_path)
        return self._send(label, payload_path, host, port, progress)

    def list_local_payloads(self, *, is_android: bool) -> tuple[Path, ...]:
        return self._file_service.list_local_payloads(is_android=is_android)

    def local_payload_directory(self, *, is_android: bool) -> Path:
        return self._file_service.local_payload_directory(is_android=is_android)

    @staticmethod
    def should_warn_js_port(path_or_url: str, port: int) -> bool:
        return str(path_or_url or '').lower().split('?', 1)[0].endswith('.js') and int(port) != 50000

    def _send(
        self,
        label: str,
        payload_path: Path,
        host: str,
        port: int,
        progress: Optional[ProgressCallback],
    ) -> PayloadExecutionResult:
        bytes_sent = self._sender.send(
            host=host,
            port=port,
            payload_path=payload_path,
            progress=progress,
        )
        return PayloadExecutionResult(
            label=label,
            local_path=Path(payload_path),
            bytes_sent=bytes_sent,
        )
