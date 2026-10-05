from __future__ import annotations

import functools
import os
import re
import ssl
import tempfile
import threading
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import unquote, urlsplit, urlunsplit


DEFAULT_MAX_POST_BYTES = 256 * 1024 * 1024
LOCALE_PREFIX = re.compile(r"^/document/[A-Za-z0-9_-]{2,8}/ps5(?:/|$)")


def replace_locale_path(raw_path: str) -> str:
    parsed = urlsplit(raw_path)
    mapped = LOCALE_PREFIX.sub("/", parsed.path, count=1)
    return urlunsplit(("", "", mapped, parsed.query, ""))


def capture_relative_name(raw_path: str, timestamp: str | None = None) -> str | None:
    mapped = replace_locale_path(raw_path)
    relative = unquote(urlsplit(mapped).path).lstrip("/")
    if relative == "a":
        return (timestamp or datetime.now().strftime("%Y%m%d-%H%M%S-%f")) + ".json"
    if relative.startswith("T_"):
        return relative + ".bin"
    return None


def safe_output_path(webroot: Path, relative_name: str) -> Path:
    normalized = relative_name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        raise ValueError("caminho de captura inválido")
    root = webroot.resolve()
    candidate = root.joinpath(*pure.parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("destino fora da pasta host") from exc
    return candidate


class _RequestHandler(SimpleHTTPRequestHandler):
    server_version = "SENDPP-LocalHost/1.0"

    def log_message(self, _format: str, *_args) -> None:
        return None

    def end_headers(self) -> None:
        if getattr(self, "_no_store_response", False):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def _notify(self) -> None:
        callback = getattr(self.server, "activity_callback", None)
        if callable(callback):
            callback(str(self.client_address[0] or ""))

    def _send_text(self, status: int, message: str) -> None:
        payload = message.encode("utf-8", errors="replace")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def _content_length(self) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise ValueError("Content-Length ausente")
        try:
            size = int(raw)
        except ValueError as exc:
            raise ValueError("Content-Length inválido") from exc
        if size < 0:
            raise ValueError("Content-Length negativo")
        return size

    def _discard_body(self, size: int) -> None:
        remaining = size
        while remaining:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                raise ConnectionError("corpo POST terminou antes do Content-Length")
            remaining -= len(chunk)

    def _save_body(self, destination: Path, size: int) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{destination.name}.",
                suffix=".part",
                dir=str(destination.parent),
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                remaining = size
                while remaining:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        raise ConnectionError("corpo POST terminou antes do Content-Length")
                    temporary.write(chunk)
                    remaining -= len(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def do_GET(self) -> None:
        self._notify()
        self.path = replace_locale_path(self.path)
        self._no_store_response = True
        try:
            if self.headers.get("If-Modified-Since") is not None:
                del self.headers["If-Modified-Since"]
            super().do_GET()
        finally:
            self._no_store_response = False

    def do_HEAD(self) -> None:
        self._notify()
        self.path = replace_locale_path(self.path)
        self._no_store_response = True
        try:
            if self.headers.get("If-Modified-Since") is not None:
                del self.headers["If-Modified-Since"]
            super().do_HEAD()
        finally:
            self._no_store_response = False

    def do_POST(self) -> None:
        self._notify()
        try:
            size = self._content_length()
        except ValueError as exc:
            self._send_text(411, f"Requisição recusada: {exc}\n")
            return

        limit = int(getattr(self.server, "max_post_bytes", DEFAULT_MAX_POST_BYTES))
        if size > limit:
            self._send_text(413, f"Payload excede o limite de {limit} bytes.\n")
            return

        relative_name = capture_relative_name(self.path)
        if relative_name is None:
            try:
                self._discard_body(size)
            except ConnectionError as exc:
                self._send_text(400, f"POST incompleto: {exc}\n")
                return
            self._send_text(204, "")
            return

        try:
            destination = safe_output_path(Path(self.server.webroot), relative_name)
            self._save_body(destination, size)
        except (ValueError, OSError, ConnectionError) as exc:
            self._send_text(400, f"Falha ao salvar captura: {exc}\n")
            return

        self._send_text(201, f"Captura salva: {destination.name}\n")


class _HttpsServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class HttpsHostServer:
    def __init__(
        self,
        *,
        bind_ip: str,
        port: int,
        webroot: Path,
        pem_path: Path,
        activity_callback: Callable[[str], None] | None = None,
        thread_daemon: bool = True,
    ) -> None:
        self.bind_ip = str(bind_ip)
        self.port = int(port)
        self.webroot = Path(webroot).resolve()
        self.pem_path = Path(pem_path).resolve()
        self.activity_callback = activity_callback
        self.thread_daemon = bool(thread_daemon)
        self._server = None
        self._thread = None

    @property
    def bound_port(self) -> int:
        server = self._server
        return int(server.server_address[1]) if server is not None else -1

    def start(self) -> None:
        if self._server is not None:
            return
        if not self.webroot.is_dir():
            raise RuntimeError("Pasta interna do Host PSM não está disponível.")
        if not self.pem_path.is_file():
            raise RuntimeError("Certificado interno do Host PSM não está disponível.")

        handler = functools.partial(_RequestHandler, directory=str(self.webroot))
        server = _HttpsServer((self.bind_ip, self.port), handler)
        server.webroot = str(self.webroot)
        server.max_post_bytes = DEFAULT_MAX_POST_BYTES
        server.activity_callback = self.activity_callback
        server.daemon_threads = self.thread_daemon
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=str(self.pem_path))
            server.socket = context.wrap_socket(server.socket, server_side=True)
        except Exception:
            server.server_close()
            raise

        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="sendpp-host-https",
            daemon=self.thread_daemon,
        )
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        try:
            server.shutdown()
        finally:
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
