import socket
from pathlib import Path
from typing import Callable, Optional

from app.models.payload import PayloadProgress

ProgressCallback = Callable[[PayloadProgress], None]


class PayloadTcpSender:
    CONNECT_TIMEOUT_SECONDS = 5.0
    CHUNK_SIZE = 32768

    def __init__(self, socket_factory=None):
        self._socket_factory = socket_factory or socket.socket

    def send(
        self,
        *,
        host: str,
        port: int,
        payload_path: Path,
        progress: Optional[ProgressCallback] = None,
    ) -> int:
        path = Path(payload_path)
        if not path.is_file():
            raise RuntimeError(f"Arquivo de payload não encontrado: {path}")
        size = path.stat().st_size
        if size <= 0:
            raise RuntimeError("O arquivo de payload está vazio.")

        sock = self._socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.CONNECT_TIMEOUT_SECONDS)
            try:
                sock.connect((str(host), int(port)))
            except socket.timeout as exc:
                raise RuntimeError(f"Tempo esgotado ao conectar em {host}:{port}.") from exc
            except OSError as exc:
                raise RuntimeError(f"Falha ao conectar em {host}:{port}: {exc}") from exc
            sock.settimeout(None)
            self._emit(progress, "Enviando payload...", 0)
            sent = 0
            last_percent = -1
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    sock.sendall(chunk)
                    sent += len(chunk)
                    percent = min(100, int(sent * 100 / size))
                    if percent != last_percent:
                        last_percent = percent
                        self._emit(progress, "Enviando payload...", percent)
            self._emit(progress, "Payload enviado.", 100)
            return sent
        finally:
            try:
                sock.close()
            except Exception:
                pass

    @staticmethod
    def _emit(
        callback: Optional[ProgressCallback],
        message: str,
        percent: Optional[int],
    ) -> None:
        if callback is not None:
            callback(PayloadProgress(message=message, percent=percent))
