import ipaddress
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from app.models.discovery_result import DiscoveryResult


class LocalIPv4UnavailableError(RuntimeError):
    pass


class LocalNetworkDiscoveryService:
    """Descoberta do loader do PS5 na sub-rede IPv4 local /24."""

    PROBE_TIMEOUT_SECONDS = 0.18
    ANDROID_WORKERS = 48
    DESKTOP_WORKERS = 64

    def __init__(
        self,
        local_ip_provider: Optional[Callable[[], str]] = None,
        port_probe: Optional[Callable[[str, int, float], bool]] = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._local_ip_provider = local_ip_provider or self.get_local_ipv4
        self._port_probe = port_probe or self.is_port_open
        self._monotonic = monotonic

    @staticmethod
    def get_local_ipv4() -> str:
        """Mantém a estratégia comprovada no app original para descobrir a interface padrão."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0] or "").strip()
        except OSError:
            return ""
        finally:
            sock.close()

    @staticmethod
    def is_port_open(ip: str, port: int, timeout: float) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect((ip, port))
            return True
        except OSError:
            return False

    def discover(self, port: int, is_android: bool) -> DiscoveryResult:
        local_ip = str(self._local_ip_provider() or "").strip()
        try:
            local_addr = ipaddress.IPv4Address(local_ip)
        except ipaddress.AddressValueError as exc:
            raise LocalIPv4UnavailableError from exc

        octets = str(local_addr).split(".")
        base = ".".join(octets[:3])
        network_cidr = f"{base}.0/24"
        candidates = [
            f"{base}.{last}"
            for last in range(1, 255)
            if f"{base}.{last}" != local_ip
        ]

        started = self._monotonic()
        stop_event = threading.Event()
        winner_lock = threading.Lock()
        workers = self.ANDROID_WORKERS if is_android else self.DESKTOP_WORKERS
        found_ip = ""

        def probe(candidate: str) -> str:
            if stop_event.is_set():
                return ""
            if not self._port_probe(candidate, port, self.PROBE_TIMEOUT_SECONDS):
                return ""
            with winner_lock:
                if stop_event.is_set():
                    return ""
                stop_event.set()
                return candidate

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(probe, candidate) for candidate in candidates]
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception:
                    result = ""
                if result:
                    found_ip = result
                    break
            for future in futures:
                if not future.done():
                    future.cancel()

        elapsed = max(0.0, self._monotonic() - started)
        return DiscoveryResult(
            local_ip=local_ip,
            network_cidr=network_cidr,
            port=port,
            found_ip=found_ip,
            elapsed_seconds=elapsed,
        )
