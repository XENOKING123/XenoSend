from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.services.host_psm.dns_server import LocalDnsServer
from app.services.host_psm.http_proxy_server import HttpProxyServer
from app.services.host_psm.https_host_server import HttpsHostServer
from app.services.host_psm.runtime_assets import HOST_LABEL, prepare_runtime


@dataclass(frozen=True)
class HostPsmSnapshot:
    phase: str
    running: bool
    local_ip: str
    endpoint: str
    host_label: str = HOST_LABEL
    client_ip: str = ""
    error: str = ""


class LocalInstallerHostService:
    """Orquestra o Host Local; no Android a Activity delega a um serviço dedicado."""

    def __init__(
        self,
        *,
        data_dir: Path,
        platform_name: str,
        local_ip_provider: Callable[[], str],
        session_guard=None,
        android_service_bridge=None,
        direct_android_runtime: bool = False,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._platform_name = str(platform_name or "").lower()
        self._local_ip_provider = local_ip_provider
        self._session_guard = session_guard
        self._android_service_bridge = android_service_bridge
        self._direct_android_runtime = bool(direct_android_runtime)
        self._lock = threading.RLock()
        self._phase = "stopped"
        self._local_ip = ""
        self._client_ip = ""
        self._https = None
        self._dns = None
        self._proxy = None
        self._activity_callback = None
        self._monitor_stop = threading.Event()
        self._monitor_thread = None

    @property
    def is_android(self) -> bool:
        return self._platform_name == "android"

    @property
    def uses_android_service(self) -> bool:
        return (
            self.is_android
            and not self._direct_android_runtime
            and self._android_service_bridge is not None
        )

    def set_activity_callback(self, callback: Callable[[HostPsmSnapshot], None] | None) -> None:
        with self._lock:
            self._activity_callback = callback
        if self.uses_android_service:
            if callback is None:
                self._stop_android_monitor()
                return
            if self.snapshot().running:
                self._start_android_monitor()

    def detach_activity(self) -> None:
        """Equivalente ao unbind da Activity: não encerra o serviço Android."""
        if not self.uses_android_service:
            return
        with self._lock:
            self._activity_callback = None
        self._stop_android_monitor()

    def ensure_notification_permission(self, on_result=None) -> bool:
        guard = self._session_guard
        if guard is None:
            return True
        return bool(guard.ensure_notification_permission(on_result))

    def ensure_android_long_session_ready(self, on_result=None) -> bool:
        guard = self._session_guard
        if guard is None:
            return True
        ensure = getattr(guard, "ensure_long_session_ready", None)
        if callable(ensure):
            return bool(ensure(on_result))
        return bool(guard.ensure_notification_permission(on_result))

    def snapshot(self) -> HostPsmSnapshot:
        if self.uses_android_service:
            return self._snapshot_from_android_bridge()
        with self._lock:
            return self._local_snapshot_locked()

    def _local_snapshot_locked(self) -> HostPsmSnapshot:
        running = self._phase == "running"
        endpoint = ""
        if running:
            endpoint = (
                f"Proxy {self._local_ip}:8080"
                if self.is_android
                else f"DNS {self._local_ip}"
            )
        return HostPsmSnapshot(
            phase=self._phase,
            running=running,
            local_ip=self._local_ip,
            endpoint=endpoint,
            client_ip=self._client_ip,
        )

    def _snapshot_from_android_bridge(self) -> HostPsmSnapshot:
        bridge_snapshot = self._android_service_bridge.snapshot()
        snapshot = HostPsmSnapshot(
            phase=bridge_snapshot.phase,
            running=bool(bridge_snapshot.running),
            local_ip=bridge_snapshot.local_ip,
            endpoint=bridge_snapshot.endpoint,
            host_label=bridge_snapshot.host_label or HOST_LABEL,
            client_ip=bridge_snapshot.client_ip,
            error=bridge_snapshot.error,
        )
        with self._lock:
            self._phase = snapshot.phase
            self._local_ip = snapshot.local_ip
            self._client_ip = snapshot.client_ip
        return snapshot

    def _on_activity(self, client_ip: str) -> None:
        callback = None
        snapshot = None
        with self._lock:
            normalized = str(client_ip or "").strip()
            if self.is_android and normalized.startswith("127."):
                return
            if normalized and normalized != self._client_ip:
                self._client_ip = normalized
                callback = self._activity_callback
                snapshot = self._local_snapshot_locked()
        if callback is not None and snapshot is not None:
            try:
                callback(snapshot)
            except Exception:
                return

    def start(self) -> HostPsmSnapshot:
        if self.uses_android_service:
            return self._start_android_service()

        with self._lock:
            if self._phase == "running":
                return self._local_snapshot_locked()
            if self._phase in {"starting", "stopping"}:
                raise RuntimeError("O Host PSM já está mudando de estado.")
            self._phase = "starting"
            self._client_ip = ""

        try:
            local_ip = str(self._local_ip_provider() or "").strip()
            if not local_ip or local_ip.startswith("127."):
                raise RuntimeError("Não foi possível detectar um IPv4 válido da rede local.")
            self._start_server_stack(local_ip)

            guard = self._session_guard
            if guard is not None:
                guard.activate(local_ip)

            with self._lock:
                self._local_ip = local_ip
                self._phase = "running"
                return self._local_snapshot_locked()
        except Exception:
            self._stop_servers()
            guard = self._session_guard
            if guard is not None:
                guard.deactivate()
            with self._lock:
                self._local_ip = ""
                self._client_ip = ""
                self._phase = "failed"
            raise

    def _start_server_stack(self, local_ip: str) -> None:
        host_root, pem_path, blocklist_path = prepare_runtime(
            self._data_dir,
            copy_contents_only=self.is_android,
        )

        if self.is_android:
            host_thread_daemon = not self._direct_android_runtime
            https = HttpsHostServer(
                bind_ip="127.0.0.1",
                port=0,
                webroot=host_root,
                pem_path=pem_path,
                activity_callback=None,
                thread_daemon=host_thread_daemon,
            )
            https.start()
            proxy = HttpProxyServer(
                bind_ip=local_ip,
                guide_backend_ip="127.0.0.1",
                guide_backend_port=https.bound_port,
                blocklist_path=blocklist_path,
                port=8080,
                activity_callback=self._on_activity,
                thread_daemon=host_thread_daemon,
            )
            try:
                proxy.start()
            except Exception:
                https.stop()
                raise
            with self._lock:
                self._https = https
                self._proxy = proxy
            return

        https = HttpsHostServer(
            bind_ip=local_ip,
            port=443,
            webroot=host_root,
            pem_path=pem_path,
            activity_callback=self._on_activity,
            thread_daemon=True,
        )
        https.start()
        dns = LocalDnsServer(
            bind_ip=local_ip,
            guide_ip=local_ip,
            blocklist_path=blocklist_path,
            port=53,
            activity_callback=self._on_activity,
        )
        try:
            dns.start()
        except Exception:
            https.stop()
            raise
        with self._lock:
            self._https = https
            self._dns = dns

    def _start_android_service(self) -> HostPsmSnapshot:
        current = self._snapshot_from_android_bridge()
        if current.running:
            self._start_android_monitor()
            return current
        if current.phase in {"starting", "stopping"}:
            raise RuntimeError("O Host PSM já está mudando de estado.")

        local_ip = str(self._local_ip_provider() or "").strip()
        if not local_ip or local_ip.startswith("127."):
            raise RuntimeError("Não foi possível detectar um IPv4 válido da rede local.")

        bridge_snapshot = self._android_service_bridge.start(local_ip)
        snapshot = HostPsmSnapshot(
            phase=bridge_snapshot.phase,
            running=bool(bridge_snapshot.running),
            local_ip=bridge_snapshot.local_ip,
            endpoint=bridge_snapshot.endpoint,
            host_label=bridge_snapshot.host_label or HOST_LABEL,
            client_ip=bridge_snapshot.client_ip,
            error=bridge_snapshot.error,
        )
        with self._lock:
            self._phase = snapshot.phase
            self._local_ip = snapshot.local_ip
            self._client_ip = snapshot.client_ip
        self._start_android_monitor()
        return snapshot

    def _start_android_monitor(self) -> None:
        if not self.uses_android_service:
            return
        with self._lock:
            existing = self._monitor_thread
            if existing is not None and existing.is_alive():
                return
            self._monitor_stop.clear()
            thread = threading.Thread(
                target=self._android_monitor_loop,
                name="host-psm-service-monitor",
                daemon=True,
            )
            self._monitor_thread = thread
            thread.start()

    def _stop_android_monitor(self) -> None:
        with self._lock:
            thread = self._monitor_thread
            self._monitor_thread = None
            self._monitor_stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _android_monitor_loop(self) -> None:
        previous = None
        while not self._monitor_stop.wait(0.5):
            snapshot = self._snapshot_from_android_bridge()
            marker = (
                snapshot.phase,
                snapshot.running,
                snapshot.local_ip,
                snapshot.client_ip,
            )
            if marker == previous:
                continue
            previous = marker
            with self._lock:
                callback = self._activity_callback
            if callback is not None:
                try:
                    callback(snapshot)
                except Exception:
                    pass
            if not snapshot.running and snapshot.phase in {"failed", "stopped"}:
                return

    def _stop_servers(self) -> None:
        with self._lock:
            proxy, dns, https = self._proxy, self._dns, self._https
            self._proxy = None
            self._dns = None
            self._https = None
        for server in (proxy, dns, https):
            if server is None:
                continue
            try:
                server.stop()
            except Exception:
                pass

    def stop(self) -> HostPsmSnapshot:
        if self.uses_android_service:
            return self._stop_android_service()

        with self._lock:
            if self._phase == "stopped":
                return self._local_snapshot_locked()
            if self._phase == "starting":
                raise RuntimeError("Aguarde a inicialização do Host PSM terminar.")
            self._phase = "stopping"

        self._stop_servers()
        guard = self._session_guard
        if guard is not None:
            guard.deactivate()

        with self._lock:
            self._phase = "stopped"
            self._local_ip = ""
            self._client_ip = ""
            return self._local_snapshot_locked()

    def _stop_android_service(self) -> HostPsmSnapshot:
        self._stop_android_monitor()
        bridge_snapshot = self._android_service_bridge.stop()
        snapshot = HostPsmSnapshot(
            phase=bridge_snapshot.phase,
            running=bool(bridge_snapshot.running),
            local_ip=bridge_snapshot.local_ip,
            endpoint=bridge_snapshot.endpoint,
            host_label=bridge_snapshot.host_label or HOST_LABEL,
            client_ip=bridge_snapshot.client_ip,
            error=bridge_snapshot.error,
        )
        with self._lock:
            self._phase = snapshot.phase
            self._local_ip = snapshot.local_ip
            self._client_ip = snapshot.client_ip
        return snapshot

    def shutdown(self) -> None:
        if self.uses_android_service:
            snapshot = self._snapshot_from_android_bridge()
            if snapshot.running:
                self._stop_android_service()
            else:
                self._stop_android_monitor()
            return

        self._stop_servers()
        guard = self._session_guard
        if guard is not None:
            guard.deactivate()
        with self._lock:
            self._phase = "stopped"
            self._local_ip = ""
            self._client_ip = ""
