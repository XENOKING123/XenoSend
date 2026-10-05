import json
from pathlib import Path
from typing import Any, Dict, Iterable

from app.models.connection_settings import ConnectionSettings


class ConnectionSettingsRepository:
    """Persistência compatível com as chaves usadas pelo aplicativo original."""

    FILE_NAME = "ps5_updater_core_config.json"

    def __init__(self, data_dir: Path, legacy_candidates: Iterable[Path] = ()) -> None:
        self._data_dir = Path(data_dir)
        self._path = self._data_dir / self.FILE_NAME
        self._legacy_candidates = tuple(Path(path) for path in legacy_candidates)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> ConnectionSettings:
        data = self._read_first_available()
        host = str(data.get("ip", "") or "").strip()
        port = self._normalize_port(data.get("port", 9021))
        return ConnectionSettings(host=host, port=port)

    def save(self, settings: ConnectionSettings) -> None:
        data = self._read_json(self._path)
        if not data:
            data = self._read_first_available()
        data["ip"] = settings.host.strip()
        data["port"] = self._normalize_port(settings.port)
        self._write_json_atomic(data)

    def _read_first_available(self) -> Dict[str, Any]:
        for path in (self._path, *self._legacy_candidates):
            data = self._read_json(path)
            if data:
                return data
        return {}

    @staticmethod
    def _normalize_port(value: Any) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            return 9021
        return port if 1 <= port <= 65535 else 9021

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write_json_atomic(self, data: Dict[str, Any]) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(self._path)
