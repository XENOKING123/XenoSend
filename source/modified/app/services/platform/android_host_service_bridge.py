from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class AndroidHostServiceSnapshot:
    phase: str = "stopped"
    running: bool = False
    local_ip: str = ""
    endpoint: str = ""
    host_label: str = "WebKit + ReLapse + Instalador"
    client_ip: str = ""
    error: str = ""
    session_id: str = ""
    updated_at: float = 0.0


class AndroidHostServiceStateStore:
    """Estado/controle atômico entre Activity e o processo do serviço Android."""

    PROTOCOL_VERSION = 1

    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir) / "host_psm_service"
        self.state_path = self.root / "state.json"
        self.command_path = self.root / "command.json"

    def prepare_session(self, session_id: str, local_ip: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._safe_unlink(self.command_path)
        self.write_state(
            {
                "session_id": session_id,
                "phase": "starting",
                "running": False,
                "local_ip": local_ip,
                "endpoint": f"Proxy {local_ip}:8080",
                "client_ip": "",
                "error": "",
            }
        )

    def write_state(self, payload: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        data = dict(payload)
        data["protocol"] = self.PROTOCOL_VERSION
        data["updated_at"] = time.time()
        self._atomic_json_write(self.state_path, data)

    def read_state(self) -> AndroidHostServiceSnapshot:
        data = self._read_json(self.state_path)
        if not data or int(data.get("protocol", 0) or 0) != self.PROTOCOL_VERSION:
            return AndroidHostServiceSnapshot()
        return AndroidHostServiceSnapshot(
            phase=str(data.get("phase", "stopped") or "stopped"),
            running=bool(data.get("running", False)),
            local_ip=str(data.get("local_ip", "") or ""),
            endpoint=str(data.get("endpoint", "") or ""),
            host_label=str(
                data.get("host_label", "WebKit + ReLapse + Instalador")
                or "WebKit + ReLapse + Instalador"
            ),
            client_ip=str(data.get("client_ip", "") or ""),
            error=str(data.get("error", "") or ""),
            session_id=str(data.get("session_id", "") or ""),
            updated_at=float(data.get("updated_at", 0.0) or 0.0),
        )

    def request_stop(self, session_id: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._atomic_json_write(
            self.command_path,
            {
                "protocol": self.PROTOCOL_VERSION,
                "command": "stop",
                "session_id": session_id,
                "created_at": time.time(),
            },
        )

    def stop_requested(self, session_id: str) -> bool:
        data = self._read_json(self.command_path)
        if not data:
            return False

        return (
            int(data.get("protocol", 0) or 0) == self.PROTOCOL_VERSION
            and str(data.get("command", "") or "") == "stop"
            and str(data.get("session_id", "") or "") == session_id
        )

    def clear_command(self) -> None:
        self._safe_unlink(self.command_path)

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _atomic_json_write(path: Path, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            temp.write_text(encoded, encoding="utf-8")
            os.replace(temp, path)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


class AndroidHostServiceBridge:
    """Controla o serviço foreground do Host Local sem mover sockets para a Activity."""

    SERVICE_CLASS_SUFFIX = ".ServiceHostpsm"
    START_TIMEOUT_SECONDS = 30.0
    STOP_TIMEOUT_SECONDS = 8.0
    STALE_AFTER_SECONDS = 5.0
    RUNNING_STALE_GRACE_SECONDS = 45.0
    POLL_SECONDS = 0.1
    MAIN_THREAD_DISPATCH_TIMEOUT_SECONDS = 8.0

    def __init__(
        self,
        data_dir: Path,
        *,
        start_service: Callable[[str], None] | None = None,
        main_thread_runner: Callable[[Callable[[], None]], None] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._store = AndroidHostServiceStateStore(self._data_dir)
        self._start_service_override = start_service
        self._main_thread_runner = main_thread_runner
        self._sleep = sleeper
        self._wall_clock = wall_clock
        self._lock = threading.RLock()
        self._session_id = ""

    @property
    def state_store(self) -> AndroidHostServiceStateStore:
        return self._store

    def start(self, local_ip: str) -> AndroidHostServiceSnapshot:
        normalized_ip = str(local_ip or "").strip()
        if not normalized_ip or normalized_ip.startswith("127."):
            raise RuntimeError("Não foi possível detectar um IPv4 válido da rede local.")

        existing = self.snapshot()
        if existing.running:
            with self._lock:
                self._session_id = existing.session_id
            return existing

        session_id = uuid.uuid4().hex
        self._store.prepare_session(session_id, normalized_ip)
        argument = json.dumps(
            {
                "protocol": AndroidHostServiceStateStore.PROTOCOL_VERSION,
                "data_dir": str(self._data_dir),
                "local_ip": normalized_ip,
                "session_id": session_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

        try:
            self._launch_android_service(argument)
        except Exception:
            self._store.write_state(
                {
                    "session_id": session_id,
                    "phase": "failed",
                    "running": False,
                    "local_ip": normalized_ip,
                    "endpoint": f"Proxy {normalized_ip}:8080",
                    "client_ip": "",
                    "error": "Não foi possível iniciar o serviço Android do Host Local.",
                }
            )

            raise

        deadline = self._wall_clock() + self.START_TIMEOUT_SECONDS
        while self._wall_clock() < deadline:
            state = self._store.read_state()
            if state.session_id != session_id:
                self._sleep(self.POLL_SECONDS)
                continue
            if state.running and state.phase == "running":
                with self._lock:
                    self._session_id = session_id
                return state
            if state.phase == "failed":
                detail = state.error.strip() or "O serviço Android do Host Local falhou ao iniciar."
                raise RuntimeError(detail)
            self._sleep(self.POLL_SECONDS)

        raise RuntimeError("O serviço Android do Host Local não confirmou a inicialização.")

    def stop(self) -> AndroidHostServiceSnapshot:
        state = self._store.read_state()
        session_id = state.session_id
        if not session_id or not self._is_alive_enough(state):
            self._clear_session()
            return AndroidHostServiceSnapshot()

        self._store.request_stop(session_id)
        deadline = self._wall_clock() + self.STOP_TIMEOUT_SECONDS
        while self._wall_clock() < deadline:
            current = self._store.read_state()
            if current.session_id != session_id:
                break
            if current.phase in {"stopped", "failed"} and not current.running:
                self._store.clear_command()
                self._clear_session()
                return current
            if not self._is_alive_enough(current):
                break
            self._sleep(self.POLL_SECONDS)

        current = self._store.read_state()
        if (
            current.session_id == session_id
            and current.running
            and self._is_alive_enough(current)
        ):
            raise RuntimeError("O serviço Android do Host Local não confirmou o encerramento.")

        self._store.clear_command()
        self._clear_session()
        return AndroidHostServiceSnapshot()

    def snapshot(self) -> AndroidHostServiceSnapshot:
        state = self._store.read_state()
        if not state.session_id or not self._is_alive_enough(state):
            return AndroidHostServiceSnapshot()
        with self._lock:
            self._session_id = state.session_id
        return state

    def _state_age(self, state: AndroidHostServiceSnapshot) -> float:
        if state.updated_at <= 0:
            return float("inf")
        return max(0.0, self._wall_clock() - state.updated_at)

    def _is_fresh(self, state: AndroidHostServiceSnapshot) -> bool:
        return self._state_age(state) <= self.STALE_AFTER_SECONDS

    def _is_alive_enough(self, state: AndroidHostServiceSnapshot) -> bool:
        if self._is_fresh(state):
            return True
        if state.running and state.phase == "running":
            return self._state_age(state) <= self.RUNNING_STALE_GRACE_SECONDS
        return False

    def _launch_android_service(self, argument: str) -> None:
        override = self._start_service_override
        if override is not None:
            override(argument)
            return

        def launch() -> None:
            from jnius import autoclass

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            if activity is None:
                raise RuntimeError("Activity Android indisponível.")
            package_name = str(activity.getPackageName())
            service_class = autoclass(package_name + self.SERVICE_CLASS_SUFFIX)
            self._start_generated_service(activity, service_class, argument)

        try:
            self._dispatch_on_android_main_thread(launch)
        except Exception as exc:
            detail = str(exc).strip()
            message = "Não foi possível iniciar o serviço Android do Host Local."
            if detail:
                message = f"{message} {detail}"
            raise RuntimeError(message) from exc

    def _dispatch_on_android_main_thread(self, callback: Callable[[], None]) -> None:
        runner = self._main_thread_runner
        if runner is not None:
            runner(callback)
            return

        if threading.current_thread() is threading.main_thread():
            callback()
            return

        try:
            from kivy.clock import Clock
        except Exception:
            callback()
            return

        finished = threading.Event()
        result = {}

        def scheduled(_dt) -> None:
            try:
                callback()
            except BaseException as exc:
                result["error"] = exc
            finally:
                finished.set()

        Clock.schedule_once(scheduled, 0)
        if not finished.wait(self.MAIN_THREAD_DISPATCH_TIMEOUT_SECONDS):
            raise RuntimeError("Timeout ao acionar o serviço Android na thread principal.")
        error = result.get("error")
        if error is not None:
            raise error

    @staticmethod
    def _start_generated_service(activity, service_class, argument: str) -> None:
        try:
            service_class.start(activity, argument)
            return
        except Exception as generated_error:
            generated_detail = (
                str(generated_error).strip() or generated_error.__class__.__name__
            )
            try:
                AndroidHostServiceBridge._start_service_with_intent(
                    activity,
                    service_class,
                    argument,
                )

                return
            except Exception as intent_error:
                intent_detail = (
                    str(intent_error).strip() or intent_error.__class__.__name__
                )
                raise RuntimeError(
                    f"{generated_detail}; fallback Intent falhou: {intent_detail}"
                ) from generated_error

    @staticmethod
    def _start_service_with_intent(activity, service_class, argument: str) -> None:
        from jnius import autoclass

        Intent = autoclass("android.content.Intent")
        BuildVersion = autoclass("android.os.Build$VERSION")
        intent = Intent(activity, service_class)
        files_dir = str(activity.getFilesDir().getAbsolutePath())
        for key, value in (
            ("androidPrivate", files_dir),
            ("androidArgument", files_dir),
            ("pythonHome", files_dir),
            ("pythonPath", files_dir),
            ("pythonName", "hostpsm"),
            ("serviceEntrypoint", "service/main.py"),
            ("pythonServiceArgument", argument),
            ("PYTHON_SERVICE_ARGUMENT", argument),
        ):
            intent.putExtra(key, value)
        intent.putExtra("serviceStartAsForeground", True)
        if int(BuildVersion.SDK_INT) >= 26:
            activity.startForegroundService(intent)
        else:
            activity.startService(intent)

    def _clear_session(self) -> None:
        with self._lock:
            self._session_id = ""
