"""Static catalog of PS5 cheat-trainer games, backed by ``app/assets/xeno/cheatslist.json``.

The JSON file is ~2.8MB (2,436 entries as of the bundled snapshot), so it is parsed
**lazily** on first access and cached at module level — importing this module must stay
instant and must never touch the filesystem by itself, so app startup is not slowed down
and the app keeps working offline until a trainer lookup is actually requested.

``id`` in the source JSON is a PS4/PS5 title id (e.g. ``CUSA00002``), which doubles as the
CheatRunner ``titleId`` used by :mod:`app.services.xeno.cheatrunner_client`.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

CATALOG_RELATIVE_PATH = Path("assets") / "xeno" / "cheatslist.json"


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / CATALOG_RELATIVE_PATH


@dataclass(frozen=True)
class TrainerFormat:
    has_file: bool
    cheats_count: int
    cheats: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TrainerGame:
    id: str
    version: str
    title: str
    id_lower: str
    title_lower: str
    cheats_total: int
    creators: Tuple[str, ...] = field(default_factory=tuple)
    creators_lower: Tuple[str, ...] = field(default_factory=tuple)
    formats: Dict[str, TrainerFormat] = field(default_factory=dict)

    def best_format(self) -> Optional[TrainerFormat]:
        """First non-empty format, preferring json, then shn, then mc4."""
        for key in ("json", "shn", "mc4"):
            fmt = self.formats.get(key)
            if fmt is not None and fmt.has_file and fmt.cheats:
                return fmt
        return None


_lock = threading.Lock()
_games: Optional[Tuple[TrainerGame, ...]] = None
_by_id: Optional[Dict[str, TrainerGame]] = None


def _parse_format(raw: object) -> TrainerFormat:
    if not isinstance(raw, dict):
        return TrainerFormat(has_file=False, cheats_count=0, cheats=())
    cheats = raw.get("cheats")
    return TrainerFormat(
        has_file=bool(raw.get("hasFile")),
        cheats_count=int(raw.get("cheatsCount") or 0),
        cheats=tuple(str(c) for c in cheats) if isinstance(cheats, list) else (),
    )


def _parse_game(raw: dict) -> TrainerGame:
    raw_formats = raw.get("formats")
    formats = {}
    if isinstance(raw_formats, dict):
        for key, value in raw_formats.items():
            formats[str(key)] = _parse_format(value)
    creators = raw.get("creators")
    creators_lower = raw.get("creatorsLower")
    return TrainerGame(
        id=str(raw.get("id") or ""),
        version=str(raw.get("version") or ""),
        title=str(raw.get("title") or ""),
        id_lower=str(raw.get("idLower") or "").lower(),
        title_lower=str(raw.get("titleLower") or "").lower(),
        cheats_total=int(raw.get("cheatsTotal") or 0),
        creators=tuple(str(c) for c in creators) if isinstance(creators, list) else (),
        creators_lower=tuple(str(c) for c in creators_lower) if isinstance(creators_lower, list) else (),
        formats=formats,
    )


def _merge_formats(
    a: Dict[str, TrainerFormat], b: Dict[str, TrainerFormat]
) -> Dict[str, TrainerFormat]:
    """Union two format maps, keeping the richer entry for any shared key
    (more cheat names > higher declared count > has-file)."""
    out = dict(a)
    for key, fmt in b.items():
        cur = out.get(key)
        rank_new = (len(fmt.cheats), fmt.cheats_count, 1 if fmt.has_file else 0)
        rank_cur = (len(cur.cheats), cur.cheats_count, 1 if cur.has_file else 0) if cur else (-1, -1, -1)
        if rank_new > rank_cur:
            out[key] = fmt
    return out


def _merge_games(a: TrainerGame, b: TrainerGame) -> TrainerGame:
    """Collapse two entries that share a title id into one, combining formats,
    creators and cheat totals. First non-empty title/version wins."""
    formats = _merge_formats(a.formats, b.formats)
    creators = list(a.creators)
    for c in b.creators:
        if c not in creators:
            creators.append(c)
    cheats_total = max(
        a.cheats_total,
        b.cheats_total,
        max((f.cheats_count for f in formats.values()), default=0),
        max((len(f.cheats) for f in formats.values()), default=0),
    )
    return TrainerGame(
        id=a.id or b.id,
        version=a.version or b.version,
        title=a.title or b.title,
        id_lower=a.id_lower or b.id_lower,
        title_lower=a.title_lower or b.title_lower,
        cheats_total=cheats_total,
        creators=tuple(creators),
        creators_lower=tuple(c.lower() for c in creators),
        formats=formats,
    )


def _ensure_loaded() -> None:
    global _games, _by_id
    if _games is not None:
        return
    with _lock:
        if _games is not None:
            return
        try:
            raw_text = _catalog_path().read_text(encoding="utf-8")
            payload = json.loads(raw_text)
            raw_entries = payload.get("entries") if isinstance(payload, dict) else None
            entries = raw_entries if isinstance(raw_entries, list) else []
            games = tuple(_parse_game(entry) for entry in entries if isinstance(entry, dict))
        except (OSError, ValueError):
            games = ()
        # Merge-dedupe by title id, preserving first-seen order. The same title id
        # can appear several times in the source (one row per cheat-file format);
        # those are the same game and must collapse to a single entry, or search
        # and pagination surface the same title repeatedly. Entries with no id fall
        # back to a title key so they still de-duplicate sensibly.
        merged: Dict[str, TrainerGame] = {}
        order: list = []
        for game in games:
            key = game.id_lower or ("title::" + game.title_lower)
            if not key.strip():
                continue
            existing = merged.get(key)
            if existing is None:
                merged[key] = game
                order.append(key)
            else:
                merged[key] = _merge_games(existing, game)
        deduped = tuple(merged[key] for key in order)
        _games = deduped
        _by_id = {g.id_lower: g for g in deduped if g.id_lower}


def all_games() -> Tuple[TrainerGame, ...]:
    """Every game in the catalog, in source order."""
    _ensure_loaded()
    return _games or ()


def search(query: str) -> Tuple[TrainerGame, ...]:
    """Case-insensitive substring match against ``titleLower``."""
    needle = str(query or "").strip().lower()
    if not needle:
        return all_games()
    return tuple(game for game in all_games() if needle in game.title_lower)


def by_id(title_id: str) -> Optional[TrainerGame]:
    """Look up a single game by its PS4/PS5 title id (case-insensitive)."""
    _ensure_loaded()
    key = str(title_id or "").strip().lower()
    if not key or _by_id is None:
        return None
    return _by_id.get(key)
