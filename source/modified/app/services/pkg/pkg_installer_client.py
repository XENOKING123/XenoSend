import socket
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

import requests

from app.catalogs.pkg_catalog import (
    PKG_INSTALLER_MIN_VERSION,
    PKG_INSTALLER_PORT,
    PKG_INSTALL_STATUS_TIMEOUT_SECONDS,
    PKG_UPLOAD_CHUNK_SIZE,
)
from app.models.pkg import PkgProgress
from app.services.payload.payload_tcp_sender import PayloadTcpSender
from app.services.pkg.pkg_file_service import PkgFileService
from app.services.pkg.pkg_installer_asset_provider import PkgInstallerAssetProvider


ProgressCallback = Callable[[PkgProgress], None]


class PkgInstallerClient:
    SERVICE_NAME = "ps5-send-pkg-payload-installer"

    def __init__(
        self,
        *,
        payload_sender: PayloadTcpSender,
        asset_provider: PkgInstallerAssetProvider,
        session: Optional[requests.Session] = None,
        sleep=time.sleep,
        monotonic=time.monotonic,
        socket_factory=socket.socket,
    ):
        self._payload_sender = payload_sender
        self._asset_provider = asset_provider
        self._session = session or requests.Session()
        self._sleep = sleep
        self._monotonic = monotonic
        self._socket_factory = socket_factory

    def ensure_running(
        self,
        *,
        host: str,
        loader_port: int,
        progress: Optional[ProgressCallback] = None,
    ) -> None:
        health = self.health(host, timeout=2.0)
        if health["ok"]:
            self._emit(progress, "Instalador de PKG já está ativo.", None)
            return

        if health["owned"]:
            self._emit(progress, "Atualizando instalador de PKG interno...", None)
            try:
                self._session.get(
                    f"http://{host}:{PKG_INSTALLER_PORT}/shutdown",
                    timeout=2.0,
                )
            except Exception:
                pass
            for _ in range(20):
                self._sleep(0.25)
                if not self._is_port_open(host, PKG_INSTALLER_PORT, timeout=0.3):
                    break

        if self._is_port_open(host, PKG_INSTALLER_PORT, timeout=0.5):
            raise RuntimeError(
                f"A porta {PKG_INSTALLER_PORT} já está em uso por outro serviço no PS5."
            )

        self._emit(progress, "Iniciando instalador de PKG...", None)
        self._payload_sender.send(
            host=host,
            port=loader_port,
            payload_path=self._asset_provider.get(),
            progress=None,
        )

        for _ in range(30):
            self._sleep(0.5)
            if self.health(host, timeout=2.0)["ok"]:
                self._emit(progress, "Instalador de PKG pronto.", None)
                return
        raise RuntimeError("O instalador de PKG não respondeu no PS5.")

    def health(self, host: str, *, timeout: float = 3.0) -> dict:
        try:
            response = self._session.get(
                f"http://{host}:{PKG_INSTALLER_PORT}/health",
                timeout=timeout,
            )
            if not (200 <= int(getattr(response, "status_code", 0) or 0) < 300):
                return {"ok": False, "owned": False, "version": 0, "has_upload": False}
            data = response.json()
        except Exception:
            return {"ok": False, "owned": False, "version": 0, "has_upload": False}
        if not isinstance(data, dict):
            return {"ok": False, "owned": False, "version": 0, "has_upload": False}
        owned = str(data.get("service") or "") == self.SERVICE_NAME
        features = data.get("features")
        has_upload = isinstance(features, (list, tuple)) and "upload" in {str(item) for item in features}
        try:
            version = int(data.get("version") or 0)
        except (TypeError, ValueError):
            version = 0
        return {
            "ok": owned and has_upload and version >= PKG_INSTALLER_MIN_VERSION,
            "owned": owned,
            "version": version,
            "has_upload": has_upload,
        }

    def upload(
        self,
        *,
        host: str,
        pkg_path: Path,
        display_name: str,
        progress: Optional[ProgressCallback] = None,
    ) -> dict:
        path = Path(pkg_path)
        if not path.is_file():
            raise RuntimeError(f"PKG local indisponível: {path}")
        total_size = path.stat().st_size
        if total_size <= 0:
            raise RuntimeError("O PKG está vazio.")

        upload_name = PkgFileService.upload_name(display_name, path)
        url = f"http://{host}:{PKG_INSTALLER_PORT}/upload?name={quote(upload_name, safe='')}"
        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(total_size),
            "Connection": "close",
        }

        self._emit(progress, "Enviando PKG...", 0)

        body = self._upload_body(path, total_size, progress)
        try:
            response = self._session.post(
                url,
                data=body,
                headers=headers,
                timeout=(10, 120),
            )
            text = str(getattr(response, "text", "") or "")
            if not (200 <= int(getattr(response, "status_code", 0) or 0) < 300):
                raise RuntimeError(f"HTTP {response.status_code}: {text[:300]}")
            try:
                data = response.json()
            except Exception:
                data = None
        except Exception as exc:
            raise RuntimeError(f"Falha ao enviar o PKG para o PS5: {exc}") from exc
        if not isinstance(data, dict) or data.get("service") != self.SERVICE_NAME:
            raise RuntimeError("Resposta inválida do instalador de PKG.")
        self._emit(progress, "PKG enviado ao instalador.", 100)
        return data

    def wait_for_result(
        self,
        *,
        host: str,
        progress: Optional[ProgressCallback] = None,
        timeout: float = PKG_INSTALL_STATUS_TIMEOUT_SECONDS,
    ) -> dict:
        deadline = self._monotonic() + max(float(timeout), 1.0)
        last_state = ""
        while self._monotonic() < deadline:
            data = self._get_json(host, "/status", timeout=8.0)
            state = str(data.get("state") or "").strip()
            ok = bool(data.get("ok", False))
            if state != last_state:
                if state in {"uploaded", "started", "running", "installing"}:
                    self._emit(progress, "Instalando PKG no PS5, aguarde ...", None)
                last_state = state
            if ok and state == "done":
                self._emit(progress, "Instalação concluída.", 100)
                return data
            if not ok or state == "error":
                diagnostic = str(
                    data.get("diagnostic")
                    or data.get("error")
                    or data.get("result")
                    or ""
                ).strip()
                raise RuntimeError(f"Instalação do PKG falhou: {diagnostic or data}")
            self._sleep(1.0)
        raise RuntimeError("A instalação do PKG não terminou dentro do tempo esperado.")

    def _get_json(self, host: str, path: str, *, timeout: float) -> dict:
        try:
            response = self._session.get(
                f"http://{host}:{PKG_INSTALLER_PORT}{path}",
                timeout=timeout,
            )
            text = str(getattr(response, "text", "") or "")
            if not (200 <= int(getattr(response, "status_code", 0) or 0) < 300):
                raise RuntimeError(f"HTTP {response.status_code}: {text[:300]}")
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"Falha ao consultar o instalador de PKG: {exc}") from exc

        return data if isinstance(data, dict) else {}

    class _UploadBody:
        def __init__(self, owner, path: Path, total_size: int, progress):
            self._owner = owner
            self._path = Path(path)
            self._total_size = int(total_size)
            self._progress = progress

        def __len__(self):
            return self._total_size

        def __iter__(self):
            sent = 0
            last_bucket = -1
            with self._path.open("rb") as handle:
                while True:
                    chunk = handle.read(PKG_UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    sent += len(chunk)
                    percent = min(100, int(sent * 100 / self._total_size))
                    bucket = percent // 5
                    if bucket != last_bucket:
                        last_bucket = bucket
                        self._owner._emit(self._progress, "Enviando PKG...", percent)
                    yield chunk

    def _upload_body(
        self,
        path: Path,
        total_size: int,
        progress: Optional[ProgressCallback],
    ):
        return self._UploadBody(self, path, total_size, progress)

    def _is_port_open(self, host: str, port: int, *, timeout: float) -> bool:
        sock = self._socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            return sock.connect_ex((str(host), int(port))) == 0
        except OSError:
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass

    @staticmethod
    def _emit(callback: Optional[ProgressCallback], message: str, percent) -> None:
        if callback is not None:
            callback(PkgProgress(message=message, percent=percent))
