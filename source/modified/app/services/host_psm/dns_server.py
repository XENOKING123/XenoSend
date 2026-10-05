from __future__ import annotations

import ipaddress
import re
import socket
import socketserver
import struct
import threading
from pathlib import Path


GUIDE_DOMAIN = "manuals.playstation.net"
TYPE_A = b"\x00\x01"


class DnsFormatError(ValueError):
    pass


def _decode_name(data: bytes, offset: int, seen: set[int] | None = None) -> tuple[list[str], int]:
    seen = set() if seen is None else seen
    labels = []
    next_offset = offset
    jumped = False
    while True:
        if offset >= len(data):
            raise DnsFormatError("nome DNS truncado")
        length = data[offset]
        if length == 0:
            if not jumped:
                next_offset = offset + 1
            return labels, next_offset
        if (length & 0xC0) == 0xC0:
            if offset + 1 >= len(data):
                raise DnsFormatError("ponteiro DNS truncado")
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if pointer in seen or pointer >= len(data):
                raise DnsFormatError("ponteiro DNS inválido")
            seen.add(pointer)
            if not jumped:
                next_offset = offset + 2
            jumped = True
            offset = pointer
            continue
        if length & 0xC0 or length > 63:
            raise DnsFormatError("rótulo DNS inválido")
        start = offset + 1
        stop = start + length
        if stop > len(data):
            raise DnsFormatError("rótulo DNS truncado")
        labels.append(data[start:stop].decode("ascii"))
        offset = stop
        if not jumped:
            next_offset = offset


def _encode_name(domain: str) -> bytes:
    output = bytearray()
    for label in domain.rstrip(".").split("."):
        if not label:
            continue
        raw = label.encode("ascii")
        if len(raw) > 63:
            raise DnsFormatError("rótulo DNS inválido")
        output.append(len(raw))
        output.extend(raw)
    output.append(0)
    return bytes(output)


class _DnsQuery:
    def __init__(self, data: bytes) -> None:
        if len(data) < 12:
            raise DnsFormatError("cabeçalho DNS truncado")
        if int.from_bytes(data[4:6], "big") != 1:
            raise DnsFormatError("quantidade de perguntas não suportada")
        self.data = data
        self.id = data[:2]
        self.request_flags = int.from_bytes(data[2:4], "big")
        labels, offset = _decode_name(data, 12)
        if offset + 4 > len(data):
            raise DnsFormatError("pergunta DNS truncada")
        self.domain = ".".join(labels).rstrip(".").lower()
        self.qtype = data[offset : offset + 2]
        self.qclass = data[offset + 2 : offset + 4]
        self.question = _encode_name(self.domain) + self.qtype + self.qclass


def _packet(query: _DnsQuery, *, rcode: int = 0, answers: tuple[bytes, ...] = (), authoritative: bool = True) -> bytes:
    flags = (
        0x8000
        | (query.request_flags & 0x7800)
        | (query.request_flags & 0x0100)
        | 0x0080
    )
    if authoritative:
        flags |= 0x0400
    flags |= rcode & 0x000F

    header = (
        query.id
        + struct.pack(">H", flags)
        + b"\x00\x01"
        + struct.pack(">H", len(answers))
        + b"\x00\x00\x00\x00"
    )

    return header + query.question + b"".join(answers)


def _a_answer(query: _DnsQuery, ip: str) -> bytes:
    rdata = socket.inet_aton(str(ipaddress.IPv4Address(ip)))
    answer = (
        b"\xc0\x0c"
        + TYPE_A
        + b"\x00\x01"
        + struct.pack(">I", 1)
        + struct.pack(">H", 4)
        + rdata
    )
    return _packet(query, answers=(answer,))


def _nxdomain(query: _DnsQuery) -> bytes:
    return _packet(query, rcode=3)


def _nodata(query: _DnsQuery) -> bytes:
    return _packet(query)


def _servfail(query: _DnsQuery) -> bytes:
    return _packet(query, rcode=2, authoritative=False)


def _error_packet(data: bytes, rcode: int = 1) -> bytes | None:
    if len(data) < 2:
        return None
    request_flags = int.from_bytes(data[2:4], "big") if len(data) >= 4 else 0
    flags = 0x8000 | (request_flags & 0x7900) | (rcode & 0x000F)
    return data[:2] + struct.pack(">H", flags) + b"\x00\x00\x00\x00\x00\x00\x00\x00"


def _load_block_patterns(path: Path) -> tuple[re.Pattern[str], ...]:
    patterns = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()

    for raw in lines:
        token = raw.strip().lower()
        if not token or token.startswith("#"):
            continue
        if "*" in token:
            expression = re.escape(token).replace("\\*", ".*")
            patterns.append(re.compile(f"^{expression}$", re.IGNORECASE))
        elif "." in token:
            patterns.append(re.compile(f"^(?:.+\\.)?{re.escape(token)}\\.?$", re.IGNORECASE))
        else:
            patterns.append(re.compile(re.escape(token), re.IGNORECASE))
    return tuple(patterns)


class _ThreadedUdpServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    address_family = socket.AF_INET
    daemon_threads = True
    allow_reuse_address = False


class LocalDnsServer:
    def __init__(
        self,
        *,
        bind_ip: str,
        guide_ip: str,
        blocklist_path: Path,
        port: int = 53,
        upstream_ip: str = "8.8.8.8",
        block_playstation: bool = True,
        activity_callback=None,
    ) -> None:
        self.bind_ip = str(ipaddress.IPv4Address(bind_ip))
        self.guide_ip = str(ipaddress.IPv4Address(guide_ip))
        self.port = int(port)
        self.upstream_ip = str(ipaddress.IPv4Address(upstream_ip))
        self.block_playstation = bool(block_playstation)
        self.block_patterns = _load_block_patterns(Path(blocklist_path))
        self.activity_callback = activity_callback
        self._server = None
        self._thread = None

    def _matches_blocklist(self, domain: str) -> bool:
        return any(pattern.search(domain) for pattern in self.block_patterns)

    @staticmethod
    def _is_guide(domain: str) -> bool:
        return domain == GUIDE_DOMAIN or domain.endswith("." + GUIDE_DOMAIN)

    def _response(self, data: bytes, client_ip: str) -> bytes:
        query = _DnsQuery(data)
        domain = query.domain
        if self._is_guide(domain):
            if callable(self.activity_callback):
                self.activity_callback(client_ip)
            if query.qtype == TYPE_A:
                return _a_answer(query, self.guide_ip)
            return _nodata(query)
        if self._matches_blocklist(domain):
            return _nxdomain(query)
        if self.block_playstation and any(
            token in domain for token in ("playstation", "sonyentertainmentnetwork", "scea")
        ):
            return _nxdomain(query)

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream:
                upstream.settimeout(3.0)
                upstream.connect((self.upstream_ip, 53))
                upstream.send(data)
                response = upstream.recv(4096)
            if len(response) < 12 or response[:2] != query.id:
                raise OSError("resposta DNS upstream inválida")
            return response
        except OSError:
            return _servfail(query)

    def start(self) -> None:
        if self._server is not None:
            return

        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                data, sock = self.request
                try:
                    response = owner._response(data, str(self.client_address[0]))
                except (DnsFormatError, UnicodeDecodeError):
                    response = _error_packet(data)
                if response is not None:
                    sock.sendto(response, self.client_address)

        server = _ThreadedUdpServer((self.bind_ip, self.port), Handler)
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="sendpp-host-dns",
            daemon=True,
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
