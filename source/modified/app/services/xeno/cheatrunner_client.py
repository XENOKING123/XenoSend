"""HTTP client for notmaj0r's CheatRunner, the PS5 web cheat trainer.

This is a faithful port of the CheatRunner REST protocol as documented in the user's own
closed-source XENOKING project (``client/src/lib/cheatRunner.ts`` and
``client/src-tauri/src/commands/xeno_store.rs`` in their XENOKING-src repository), which the
user authorized porting from. It is accurate to that source.

IMPORTANT: this module has **not been tested against a live PS5 / CheatRunner instance**
in this session — no console was reachable. Every public method is written to fail soft:
network/parse errors raise a plain, catchable ``RuntimeError`` with a Portuguese message
(matching this app's house style) instead of letting an unexpected exception type escape
and crash the UI.

Base URL: ``http://<ps5-ip>:9999`` — plain HTTP, no auth, CORS ``*`` (per the original
project's own comment). No endpoint here requires a session or token.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

import requests

from app.models.cheatrunner import AttachResult, CheatRunnerCheat, CheatRunnerGame

PORT = 9999
CONNECT_TIMEOUT_SECONDS = 3.0
READ_TIMEOUT_SECONDS = 5.0
UPLOAD_MIN_READ_TIMEOUT_SECONDS = 10.0
UPLOAD_BYTES_PER_SECOND_BUDGET = 128 * 1024

MAX_JSON_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_SHN_MC4_UPLOAD_BYTES = 1 * 1024 * 1024
VALID_UPLOAD_EXTENSIONS = (".json", ".shn", ".mc4")

ATTACH_DEFAULT_TIMEOUT_SECONDS = 9.0
ATTACH_DEFAULT_INTERVAL_SECONDS = 0.75

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_REPEAT_UNDERSCORE_RE = re.compile(r"_+")


class CheatRunnerFilenameError(RuntimeError):
    """A cheat filename failed the client-side safety checks before it was ever sent."""


def sanitize_cheat_filename(raw_filename: str) -> str:
    """Validate and sanitize a filename before it is uploaded.

    Rejects outright anything that looks like a path-traversal attempt (``/``, ``\\`` or
    ``..``) in the *original* name — sanitizing first would hide those characters without
    removing the risk, since ``.`` is itself an allowed character. After that the name is
    reduced to ``[A-Za-z0-9._-]`` (anything else becomes ``_``, repeats collapse), a
    ``.ShnExt``/``.SHNEXT`` extension is remapped to ``.shn``, and the final lowercase
    extension must be exactly ``.json``, ``.shn`` or ``.mc4``.
    """
    original = str(raw_filename or "").strip()
    if not original:
        raise CheatRunnerFilenameError("Nome de arquivo de cheat vazio.")
    if "/" in original or "\\" in original or ".." in original:
        raise CheatRunnerFilenameError(f"Nome de arquivo de cheat inválido: {raw_filename}")

    sanitized = _SANITIZE_RE.sub("_", original)
    sanitized = _REPEAT_UNDERSCORE_RE.sub("_", sanitized).strip("._")
    if not sanitized:
        raise CheatRunnerFilenameError(f"Nome de arquivo de cheat inválido: {raw_filename}")

    stem, ext = os.path.splitext(sanitized)
    if ext.lower() == ".shnext":
        ext = ".shn"
    lowered_ext = ext.lower()
    if lowered_ext not in VALID_UPLOAD_EXTENSIONS:
        raise CheatRunnerFilenameError(f"Extensão de cheat não suportada: {ext or '(nenhuma)'}")
    return stem + lowered_ext


def _max_upload_bytes(extension: str) -> int:
    return MAX_JSON_UPLOAD_BYTES if extension == ".json" else MAX_SHN_MC4_UPLOAD_BYTES


def _extract_list(payload: object, keys: tuple) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _first_str(item: dict, keys: tuple) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _first_bool(item: dict, keys: tuple) -> bool:
    for key in keys:
        if key in item and item[key] is not None:
            return bool(item[key])
    return False


def _first_int(item: dict, keys: tuple) -> Optional[int]:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _parse_game(item: dict) -> CheatRunnerGame:
    raw_title_id = _first_str(item, ("title_id", "titleId", "id", "titleid", "cusa"))
    title_id = raw_title_id.split("_", 1)[0] if raw_title_id else ""
    return CheatRunnerGame(
        title_id=title_id,
        name=_first_str(item, ("name", "title", "app_name")),
        version=_first_str(item, ("version", "app_ver", "ver")),
        running=_first_bool(item, ("running", "isRunning", "active", "is_running")),
        has_cheat=_first_bool(item, ("has_cheat", "hasCheat", "cheat", "has_trainer")),
        is_app=_first_bool(item, ("is_app", "isApp")),
        raw=item,
    )


def _resolve_enabled(item: dict) -> bool:
    """Enabled-state priority — preserve exactly, there is a known bug class here.

    CheatRunner emits string classifications like ``"off_unverified"``, ``"baseline_unknown"``,
    ``"mismatch"`` or ``"crash_suspect"`` on the ``state`` field — all truthy strings, all mean
    OFF. A naive ``bool(state)`` is a real bug this must not reproduce.
    """
    for key in ("enabled", "on", "active"):
        if key in item and item[key] is not None:
            value = item[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
    visual_state = item.get("visualState")
    if isinstance(visual_state, str):
        return visual_state.strip().lower() == "on"
    state = item.get("state")
    if isinstance(state, str):
        lowered = state.strip().lower()
        return lowered == "on" or lowered.startswith("on_")
    return False


def _parse_cheat(item: dict, position: int) -> CheatRunnerCheat:
    index = _first_int(item, ("index", "idx", "i"))
    return CheatRunnerCheat(
        index=index if index is not None else position,
        name=_first_str(item, ("name", "text", "title")),
        enabled=_resolve_enabled(item),
        raw=item,
    )


class CheatRunnerClient:
    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self._session = session or requests.Session()

    # -- plumbing -------------------------------------------------------------------------
    @staticmethod
    def _base_url(ip: str) -> str:
        return f"http://{str(ip or '').strip()}:{PORT}"

    def _get(self, ip: str, path: str, *, params: Optional[dict] = None, timeout=None):
        url = f"{self._base_url(ip)}{path}"
        try:
            return self._session.get(
                url, params=params, timeout=timeout or (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)
            )
        except Exception as exc:
            raise RuntimeError(f"CheatRunner não respondeu em {ip}:{PORT}: {exc}") from exc

    # -- protocol --------------------------------------------------------------------------
    def is_up(self, ip: str) -> bool:
        """``GET /api/state`` — any 2xx response means CheatRunner is up. Never raises."""
        try:
            response = self._get(ip, "/api/state")
            return 200 <= response.status_code < 300
        except RuntimeError:
            return False

    def list_games(self, ip: str) -> tuple:
        response = self._get(ip, "/api/games")
        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f"Falha ao listar jogos em {ip}:{PORT}: {exc}") from exc
        items = _extract_list(payload, ("games", "list"))
        return tuple(_parse_game(item) for item in items if isinstance(item, dict))

    def cheat_state(self, ip: str, title_id: str) -> tuple:
        response = self._get(ip, "/api/cheats/state", params={"titleId": title_id, "debug": 1})
        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f"Falha ao obter estado dos cheats em {ip}:{PORT}: {exc}") from exc
        items = _extract_list(payload, ("cheats", "state", "mods"))
        return tuple(
            _parse_cheat(item, position)
            for position, item in enumerate(items)
            if isinstance(item, dict)
        )

    def toggle_cheat(self, ip: str, title_id: str, index: int, on: bool) -> None:
        response = self._get(
            ip,
            "/api/cheats/toggle",
            params={"titleId": title_id, "index": int(index), "on": 1 if on else 0},
        )
        try:
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Falha ao alternar cheat em {ip}:{PORT}: {exc}") from exc

    def disable_all(self, ip: str, title_id: str) -> None:
        response = self._get(ip, "/api/cheats/disable-all", params={"titleId": title_id})
        try:
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Falha ao desativar todos os cheats em {ip}:{PORT}: {exc}") from exc

    def launch_game(self, ip: str, title_id: str) -> bool:
        """Try ``/launch`` then ``/api/launch``. Returns True on first success, else False."""
        for path in ("/launch", "/api/launch"):
            try:
                response = self._get(ip, path, params={"titleId": title_id})
            except RuntimeError:
                continue
            if 200 <= response.status_code < 300:
                return True
        return False

    def close_game(self, ip: str, title_id: str) -> bool:
        """Try kill/close variants in order; first success wins."""
        for path in ("/api/kill", "/kill", "/api/close", "/close"):
            try:
                response = self._get(ip, path, params={"titleId": title_id})
            except RuntimeError:
                continue
            if 200 <= response.status_code < 300:
                return True
        return False

    def upload_cheat_file(
        self,
        ip: str,
        local_path,
        filename_hint: Optional[str] = None,
    ) -> None:
        path = Path(local_path)
        if not path.is_file():
            raise RuntimeError(f"Arquivo de cheat não encontrado: {path}")
        filename = sanitize_cheat_filename(filename_hint or path.name)
        extension = Path(filename).suffix.lower()
        size = path.stat().st_size
        limit = _max_upload_bytes(extension)
        if size > limit:
            raise RuntimeError(
                f"Arquivo de cheat excede o limite de {limit // (1024 * 1024)} MiB: {filename}"
            )
        data = path.read_bytes()
        read_timeout = max(UPLOAD_MIN_READ_TIMEOUT_SECONDS, size / UPLOAD_BYTES_PER_SECOND_BUDGET)
        url = f"{self._base_url(ip)}/api/cheats/upload"
        try:
            response = self._session.post(
                url,
                params={"filename": filename},
                data=data,
                headers={"Content-Type": "application/octet-stream"},
                timeout=(CONNECT_TIMEOUT_SECONDS, read_timeout),
            )
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Falha ao enviar cheat para {ip}:{PORT}: {exc}") from exc

    def repo_sync(self, ip: str, source: str = "all", overwrite: bool = False) -> None:
        response = self._get(
            ip,
            "/api/cheats/repo/download",
            params={"source": source, "overwrite": 1 if overwrite else 0},
        )
        try:
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                f"Falha ao sincronizar o repositório de cheats em {ip}:{PORT}: {exc}"
            ) from exc

    def repo_sync_status(self, ip: str) -> str:
        response = self._get(ip, "/api/cheats/repo/download/status")
        try:
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                f"Falha ao consultar status de sincronização em {ip}:{PORT}: {exc}"
            ) from exc
        return response.text

    def attach(
        self,
        ip: str,
        title_id: str,
        already_running: bool = False,
        timeout_s: float = ATTACH_DEFAULT_TIMEOUT_SECONDS,
        interval_s: float = ATTACH_DEFAULT_INTERVAL_SECONDS,
    ) -> AttachResult:
        """Not a real endpoint — client logic: launch if needed, then poll for cheat state."""
        launched = False
        if not already_running:
            launched = self.launch_game(ip, title_id)

        deadline = time.monotonic() + float(timeout_s)
        last_count = 0
        while True:
            try:
                cheats = self.cheat_state(ip, title_id)
            except RuntimeError:
                cheats = ()
            last_count = len(cheats)
            if last_count:
                return AttachResult(ok=True, cheat_count=last_count, launched=launched, message="")
            if time.monotonic() >= deadline:
                break
            time.sleep(float(interval_s))
        return AttachResult(
            ok=False,
            cheat_count=last_count,
            launched=launched,
            message="Nenhum cheat encontrado após conectar.",
        )
