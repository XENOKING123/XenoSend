"""Persistence for UI preferences (language, background theme).

Stored next to the app's other data as ``ui_preferences.json``.  It is deliberately separate
from the connection settings file so that neither feature can corrupt the other.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

FILE_NAME = "ui_preferences.json"


class UiPreferences:
    def __init__(self, data_dir: Path) -> None:
        self._path = Path(data_dir) / FILE_NAME
        self._values: Dict[str, Any] = self._read()

    def _read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key: str) -> Optional[str]:
        value = self._values.get(key)
        return value if isinstance(value, str) and value else None

    def save(self, **updates: str) -> None:
        self._values.update(updates)
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self._values, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError:
            # Preferences are a convenience; failing to persist must never break the UI.
            pass
