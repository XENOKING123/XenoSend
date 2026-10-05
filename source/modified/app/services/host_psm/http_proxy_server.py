from __future__ import annotations

import concurrent.futures
import re
import socket
import threading
from pathlib import Path
from urllib.parse import urlsplit


GUIDE_DOMAIN = "manuals.playstation.net"
INSTALLER_LOOPBACK_HOST = "127.0.0.1"
INSTALLER_RELAY_PORT = 18181
MAX_HEADER_BYTES = 32768
CONNECT_TIMEOUT_SECONDS = 8.0
SOCKET_TIMEOUT_SECONDS = 120.0
GUIDE_TUNNEL_TIMEOUT_SECONDS = None
GUIDE_KEEPALIVE_IDLE_SECONDS = 30
GUIDE_KEEPALIVE_INTERVAL_SECONDS = 10
GUIDE_KEEPALIVE_PROBES = 3


def _normalize_host(value: str) -> str:
    host = str(value or "").strip().rstrip(".").lower()
    if not host:
        raise ValueError("host vazio")
    return host


def _parse_host_port(value: str, default_port: int) -> tuple[str, int]:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("host ausente")
    if raw.startswith("["):
        close = raw.find("]")
        if close < 0:
            raise ValueError("host inválido")
        host = raw[1:close]
        port = default_port
        suffix = raw[close + 1:]
        if suffix:
            if not suffix.startswith(":"):
                raise ValueError("porta inválida")
            port = int(suffix[1:])
    else:
        host = raw
        port = default_port
        if raw.count(":") == 1:
            candidate_host, candidate_port = raw.rsplit(":", 1)
            if candidate_port.isdigit():
                host, port = candidate_host, int(candidate_port)
    if not 1 <= int(port) <= 65535:
        raise ValueError("porta fora do intervalo")
    return _normalize_host(host), int(port)


def _load_block_patterns(path: Path) -> tuple[re.Pattern[str], ...]:
    patterns = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    for raw in lines:
        token = raw.strip().lower()
        if not token or token.startswith("#"):
            continue
        if "*" in token:
            expression = re.escape(token).replace("\\*", ".*")
            patterns.append(re.compile(f"^{expression}$", re.IGNORECASE))
            continue
        if "." in token:
            patterns.append(
                re.compile(f"^(?:.+\\.)?{re.escape(token)}\\.?$", re.IGNORECASE)
            )
            continue
        patterns.append(re.compile(re.escape(token), re.IGNORECASE))
    return tuple(patterns)


class _HttpRequest:
    def __init__(self, method: str, target: str, version: str, headers: list[tuple[str, str]]) -> None:
        self.method = method.upper()
        self.target = target
        self.version = version
        self.headers = headers
        self.header_map = {name.lower(): value for name, value in headers}

    @classmethod
    def read(cls, stream) -> "_HttpRequest":
        buffer = bytearray()
        while b"\r\n\r\n" not in buffer:
            chunk = stream.recv(4096)
            if not chunk:
                raise OSError("requisição encerrada antes do cabeçalho")
            buffer.extend(chunk)
            if len(buffer) > MAX_HEADER_BYTES:
                raise OSError("cabeçalho HTTP excede o limite")
        header_bytes, remainder = bytes(buffer).split(b"\r\n\r\n", 1)
        lines = header_bytes.decode("iso-8859-1").split("\r\n")
        first = lines[0].split(" ", 2)
        if len(first) != 3:
            raise OSError("linha HTTP inválida")
        headers = []
        for line in lines[1:]:
            if not line:
                continue
            if ":" not in line:
                raise OSError("cabeçalho HTTP inválido")
            name, value = line.split(":", 1)
            headers.append((name.strip(), value.strip()))
        request = cls(first[0], first[1], first[2], headers)
        request.remainder = remainder
        return request


class HttpProxyServer:
    def __init__(
        self,
        *,
        bind_ip: str,
        guide_backend_ip: str,
        guide_backend_port: int,
        blocklist_path: Path,
        port: int = 8080,
        block_playstation: bool = True,
        activity_callback=None,
        thread_daemon: bool = True,
    ) -> None:
        self.bind_ip = _normalize_host(bind_ip)
        self.port = int(port)
        self.guide_backend_ip = _normalize_host(guide_backend_ip)
        self.guide_backend_port = int(guide_backend_port)
        self.block_playstation = bool(block_playstation)
        self.block_patterns = _load_block_patterns(Path(blocklist_path))
        self.activity_callback = activity_callback
        self.thread_daemon = bool(thread_daemon)
        self._listener = None
        self._accept_thread = None
        self._workers = None
        self._running = threading.Event()
        self._active = set()
        self._active_lock = threading.Lock()

    @staticmethod
    def _is_guide(host: str) -> bool:
        return host == GUIDE_DOMAIN or host.endswith("." + GUIDE_DOMAIN)

    def _blocked(self, host: str) -> bool:
        if self._is_guide(host):
            return False
        if any(pattern.search(host) for pattern in self.block_patterns):
            return True
        return self.block_playstation and any(
            token in host for token in ("playstation", "sonyentertainmentnetwork", "scea")
        )

    def _track(self, sock: socket.socket) -> None:
        with self._active_lock:
            self._active.add(sock)

    def _untrack(self, sock: socket.socket) -> None:
        with self._active_lock:
            self._active.discard(sock)

    @staticmethod
    def _close(sock: socket.socket | None) -> None:
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def start(self) -> None:
        if self._listener is not None:
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self.bind_ip, self.port))
            listener.listen(32)
            listener.settimeout(1.0)
        except Exception:
            listener.close()
            raise
        self._listener = listener
        self._workers = concurrent.futures.ThreadPoolExecutor(
            max_workers=16, thread_name_prefix="sendpp-proxy"
        )
        self._running.set()
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="sendpp-host-proxy",
            daemon=self.thread_daemon,
        )
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        try:
            while self._running.is_set():
                listener = self._listener
                if listener is None:
                    break
                try:
                    client, _address = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                client.settimeout(SOCKET_TIMEOUT_SECONDS)
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._track(client)
                workers = self._workers
                if workers is None:
                    self._close(client)
                    self._untrack(client)
                    continue
                try:
                    workers.submit(self._handle_client, client)
                except RuntimeError:
                    self._close(client)
                    self._untrack(client)
        finally:
            self._running.clear()

    def _connect(self, host: str, port: int) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(CONNECT_TIMEOUT_SECONDS)
            sock.connect((host, port))
            sock.settimeout(SOCKET_TIMEOUT_SECONDS)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._track(sock)
            return sock
        except Exception:
            self._close(sock)
            raise

    @staticmethod
    def _send_response(sock: socket.socket, status: int, reason: str, body: str) -> None:
        payload = body.encode("utf-8")
        response = (
            f"HTTP/1.1 {status} {reason}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(payload)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii") + payload
        sock.sendall(response)

    @staticmethod
    def _send_guide_redirect(sock: socket.socket, location: str) -> None:
        response = (
            "HTTP/1.1 302 Found\r\n"
            f"Location: {location}\r\n"
            "Content-Length: 0\r\n"
            "Cache-Control: no-store, no-cache, must-revalidate, max-age=0\r\n"
            "Pragma: no-cache\r\n"
            "Expires: 0\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        sock.sendall(response)

    def _handle_client(self, client: socket.socket) -> None:
        upstream = None
        try:
            request = _HttpRequest.read(client)
            source_ip = str(client.getpeername()[0])
            if request.method == "CONNECT":
                host, port = _parse_host_port(request.target, 443)
                if self._blocked(host):
                    self._send_response(client, 403, "Forbidden", "Target blocked")
                    return
                if port not in (80, 443):
                    self._send_response(client, 403, "Forbidden", "Port not allowed")
                    return
                guide = self._is_guide(host)
                if guide and port != 443:
                    self._send_response(client, 403, "Forbidden", "Invalid Guide port")
                    return
                destination_host = self.guide_backend_ip if guide else host
                destination_port = self.guide_backend_port if guide else port
                upstream = self._connect(destination_host, destination_port)
                if guide:
                    self._configure_guide_tunnel(
                        client,
                        upstream,
                    )
                if guide and callable(self.activity_callback):
                    self.activity_callback(source_ip)
                client.sendall(
                    b"HTTP/1.1 200 Connection Established\r\nProxy-Agent: SENDPP-Host-PSM\r\n\r\n"
                )
                self._tunnel(client, upstream, initial_client=request.remainder)
                return

            scheme, host, port, path = self._parse_http_target(request)
            if self._blocked(host):
                self._send_response(client, 403, "Forbidden", "Target blocked")
                return
            if scheme != "http":
                self._send_response(client, 400, "Bad Request", "Use CONNECT for HTTPS")
                return

            installer_target = host == INSTALLER_LOOPBACK_HOST and port == INSTALLER_RELAY_PORT
            installer_relay = installer_target and request.method == "GET"
            if installer_target and not installer_relay:
                self._send_response(client, 403, "Forbidden", "Invalid installer request")
                return
            if not installer_relay and port not in (80, 443):
                self._send_response(client, 403, "Forbidden", "Port not allowed")
                return

            if self._is_guide(host):
                if callable(self.activity_callback):
                    self.activity_callback(source_ip)
                self._send_guide_redirect(client, f"https://{GUIDE_DOMAIN}{path}")
                return

            destination_host = source_ip if installer_relay else host
            destination_port = INSTALLER_RELAY_PORT if installer_relay else port
            upstream = self._connect(destination_host, destination_port)
            if self._is_guide(host):
                self._configure_guide_tunnel(
                    client,
                    upstream,
                )
            self._forward_request(upstream, request, path)
            self._tunnel(client, upstream, initial_client=request.remainder)
        except (OSError, ValueError):
            try:
                self._send_response(client, 502, "Bad Gateway", "Target unavailable")
            except OSError:
                pass
        finally:
            if upstream is not None:
                self._untrack(upstream)
                self._close(upstream)
            self._untrack(client)
            self._close(client)

    @staticmethod
    def _parse_http_target(request: _HttpRequest) -> tuple[str, str, int, str]:
        target = request.target
        if target.startswith("http://") or target.startswith("https://"):
            parsed = urlsplit(target)
            scheme = parsed.scheme.lower()
            host = _normalize_host(parsed.hostname or "")
            port = parsed.port or (443 if scheme == "https" else 80)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            return scheme, host, port, path
        host_header = request.header_map.get("host", "")
        host, port = _parse_host_port(host_header, 80)
        path = target if target.startswith("/") else "/" + target
        return "http", host, port, path

    @staticmethod
    def _forward_request(upstream: socket.socket, request: _HttpRequest, path: str) -> None:
        lines = [f"{request.method} {path} {request.version}\r\n"]
        for name, value in request.headers:
            lowered = name.lower()
            if lowered in {"proxy-connection", "proxy-authorization", "connection"}:
                continue
            lines.append(f"{name}: {value}\r\n")
        lines.append("Connection: close\r\n\r\n")
        upstream.sendall("".join(lines).encode("iso-8859-1"))

    @classmethod
    def _configure_guide_tunnel(cls, *sockets: socket.socket) -> None:
        for sock in sockets:
            sock.settimeout(GUIDE_TUNNEL_TIMEOUT_SECONDS)
            cls._enable_tcp_keepalive(sock)

    @staticmethod
    def _enable_tcp_keepalive(sock: socket.socket) -> None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            return
        for name, value in (
            ("TCP_KEEPIDLE", GUIDE_KEEPALIVE_IDLE_SECONDS),
            ("TCP_KEEPINTVL", GUIDE_KEEPALIVE_INTERVAL_SECONDS),
            ("TCP_KEEPCNT", GUIDE_KEEPALIVE_PROBES),
        ):
            option = getattr(socket, name, None)
            if option is None:
                continue
            try:
                sock.setsockopt(socket.IPPROTO_TCP, option, int(value))
            except OSError:
                continue

        ioctl = getattr(sock, "ioctl", None)
        windows_keepalive = getattr(socket, "SIO_KEEPALIVE_VALS", None)
        if callable(ioctl) and windows_keepalive is not None:
            try:
                ioctl(
                    windows_keepalive,
                    (
                        1,
                        int(GUIDE_KEEPALIVE_IDLE_SECONDS * 1000),
                        int(GUIDE_KEEPALIVE_INTERVAL_SECONDS * 1000),
                    ),
                )
            except OSError:
                return

    def _tunnel(self, client: socket.socket, upstream: socket.socket, initial_client: bytes = b"") -> None:
        if initial_client:
            upstream.sendall(initial_client)

        def upload() -> None:
            try:
                while True:
                    data = client.recv(16384)
                    if not data:
                        break
                    upstream.sendall(data)
            except OSError:
                pass
            try:
                upstream.shutdown(socket.SHUT_WR)
            except OSError:
                pass

        thread = threading.Thread(
            target=upload,
            name="sendpp-proxy-upload",
            daemon=self.thread_daemon,
        )
        thread.start()
        try:
            while True:
                data = upstream.recv(16384)
                if not data:
                    break
                client.sendall(data)
        except OSError:
            pass
        finally:
            try:
                client.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            thread.join(timeout=1.0)

    def stop(self) -> None:
        self._running.clear()
        listener = self._listener
        self._listener = None
        self._close(listener)
        with self._active_lock:
            active = list(self._active)
            self._active.clear()
        for sock in active:
            self._close(sock)
        thread = self._accept_thread
        self._accept_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        workers = self._workers
        self._workers = None
        if workers is not None:
            workers.shutdown(wait=False, cancel_futures=True)
