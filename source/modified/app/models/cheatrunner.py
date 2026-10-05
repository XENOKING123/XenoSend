from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class CheatRunnerGame:
    """One entry from ``GET /api/games``, read leniently (build-dependent key names)."""

    title_id: str
    name: str
    version: str
    running: bool
    has_cheat: bool
    is_app: bool
    raw: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class CheatRunnerCheat:
    """One entry from ``GET /api/cheats/state``."""

    index: int
    name: str
    enabled: bool
    raw: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class AttachResult:
    """Outcome of :meth:`CheatRunnerClient.attach` — launch + poll for live cheat state."""

    ok: bool
    cheat_count: int
    launched: bool
    message: str = ""
