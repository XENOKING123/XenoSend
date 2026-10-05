#!/usr/bin/env python3
"""Rebuild the trainer browse index (cheatslist.json) from the full trainer seed.

The shipped index only covered ~2,436 games and was missing titles whose files
are present in the seed but were never indexed (for example Marvel's Wolverine,
which ships only as an .mc4 blob). This scans every trainer file in the seed and
rebuilds the index so the browser shows and searches the whole library.

Parsing mirrors the reference scanner exactly (JSON / SHN / MC4 / Orbis XML), so
cheat ordering here matches apply-by-index on the console.

Usage:
    python tools/build_trainer_index.py <seed_dir_or_zip> <out_cheatslist.json> [--merge <base_index.json>]

<seed_dir> must contain json/ shn/ mc4/ subfolders (as the seed zip does).
With --merge, the base index is kept verbatim (curated titles win) and only
games the scan finds that the base lacks are added, so the game count never
regresses.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ID_RE = re.compile(r"^[A-Za-z]{4}[0-9]{5}$")


# ---- filename / xml helpers (ported from the reference scanner) -------------

def id_from_name(name: str) -> str:
    for tok in re.split(r"[^A-Za-z0-9]+", name):
        if _ID_RE.match(tok):
            return tok.upper()
    return ""


def version_from_name(name: str) -> str:
    for tok in name.split("_"):
        tok = tok.rstrip()
        for suf in (".mc4", ".shn", ".json"):
            if tok.endswith(suf):
                tok = tok[: -len(suf)]
        if tok and tok[0].isdigit() and all(c.isdigit() or c == "." for c in tok) and "." in tok:
            return tok
    return ""


def modder_from_name(name: str) -> str:
    stem = name.rsplit(".", 1)[0]
    last = stem.rsplit("_", 1)[-1].strip()
    if not last or all(c.isdigit() or c == "." for c in last):
        return ""
    return last


def attr(xml: str, key: str) -> str:
    needle = (key + '="').lower()
    lower = xml.lower()
    p = lower.find(needle)
    if p < 0:
        return ""
    start = p + len(needle)
    end = xml[start:].find('"')
    if end < 0:
        return ""
    return xml[start:start + end]


def cheat_texts(xml: str) -> List[str]:
    out: List[str] = []
    rest = xml
    while True:
        p = rest.find('Text="')
        if p < 0:
            break
        s = p + 6
        end = rest[s:].find('"')
        if end < 0:
            break
        out.append(rest[s:s + end])
        rest = rest[s + end:]
    return out


def orbis_title_ids(xml: str) -> List[str]:
    out: List[str] = []
    rest = xml
    while True:
        p = rest.find("<ID>")
        if p < 0:
            break
        s = p + 4
        end = rest[s:].find("</ID>")
        if end < 0:
            break
        tid = rest[s:s + end].strip().upper()
        if tid and tid not in out:
            out.append(tid)
        rest = rest[s + end + 5:]
    return out


def orbis_cheats(xml: str) -> List[str]:
    out: List[str] = []
    rest = xml
    while True:
        mp = rest.find("<Metadata")
        if mp < 0:
            break
        after = rest[mp + 9:]
        tag_end = after.find(">")
        if tag_end < 0:
            tag_end = len(after)
        tag = after[:tag_end]
        np = tag.find('Name="')
        if np >= 0:
            vs = np + 6
            ve = tag[vs:].find('"')
            if ve >= 0:
                name = tag[vs:vs + ve].strip()
                if name:
                    out.append(name)
        rest = after[tag_end:]
    return out


# ---- per-file parsers -------------------------------------------------------

class Row:
    __slots__ = ("game", "title_id", "version", "format", "modder", "cheats")

    def __init__(self, game, title_id, version, fmt, modder, cheats):
        self.game = game
        self.title_id = title_id
        self.version = version
        self.format = fmt
        self.modder = modder
        self.cheats = cheats


def _read_text(data: bytes) -> Optional[str]:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def parse_json(name: str, data: bytes) -> Optional[Row]:
    txt = _read_text(data)
    if txt is None:
        return None
    try:
        v = json.loads(txt)
    except ValueError:
        return None
    if not isinstance(v, dict) or v.get("mods") is None:
        return None  # index/list file, not a trainer
    mods = v.get("mods") if isinstance(v.get("mods"), list) else []
    cheats = [str(m.get("name") or "?") if isinstance(m, dict) else "?" for m in mods]
    tid = str(v.get("id") or "").split("_")[0].upper()
    credits = v.get("credits")
    modder = str(credits[0]) if isinstance(credits, list) and credits else ""
    return Row(str(v.get("name") or ""), tid, str(v.get("version") or ""), "json", modder, cheats)


def parse_shn(name: str, data: bytes) -> Optional[Row]:
    txt = _read_text(data)
    if txt and "<" in txt:
        tid = attr(txt, "Cusa").split("_")[0].upper() or id_from_name(name)
        return Row(attr(txt, "Game"), tid, attr(txt, "Version"), "shn", attr(txt, "Moder"), cheat_texts(txt))
    tid = id_from_name(name)
    if not tid:
        return None
    return Row("", tid, version_from_name(name), "shn", modder_from_name(name), [])


def parse_mc4(name: str, data: bytes, sidecar: Optional[bytes]) -> Optional[Row]:
    tid = id_from_name(name)
    xml = _read_text(sidecar) if sidecar else None
    if xml:
        v = attr(xml, "Version")
        return Row(attr(xml, "Game"), tid, v or version_from_name(name),
                   "mc4", attr(xml, "Moder"), cheat_texts(xml))
    return Row("", tid, version_from_name(name), "mc4", "", [])


# ---- seed loading (dir or zip) ----------------------------------------------

def load_seed(seed: Path) -> Dict[str, Dict[str, bytes]]:
    """Return {subdir: {filename: bytes}} for json/, shn/, mc4/."""
    buckets: Dict[str, Dict[str, bytes]] = {"json": {}, "shn": {}, "mc4": {}}
    if seed.is_file() and seed.suffix.lower() == ".zip":
        with zipfile.ZipFile(seed) as z:
            for n in z.namelist():
                if n.endswith("/"):
                    continue
                parts = n.split("/")
                if len(parts) < 2 or parts[0] not in buckets:
                    continue
                buckets[parts[0]][parts[-1]] = z.read(n)
    else:
        for sub in buckets:
            d = seed / sub
            if d.is_dir():
                for p in d.iterdir():
                    if p.is_file():
                        buckets[sub][p.name] = p.read_bytes()
    return buckets


# ---- index assembly ---------------------------------------------------------

def build_rows(buckets: Dict[str, Dict[str, bytes]]) -> List[Row]:
    rows: List[Row] = []

    for name, data in buckets["json"].items():
        if not name.lower().endswith(".json"):
            continue
        r = parse_json(name, data)
        if r:
            rows.append(r)

    for name, data in buckets["shn"].items():
        if not name.lower().endswith(".shn"):
            continue
        r = parse_shn(name, data)
        if r:
            rows.append(r)

    mc4 = buckets["mc4"]
    for name, data in mc4.items():
        low = name.lower()
        if not low.endswith(".mc4"):
            continue
        r = parse_mc4(name, data, mc4.get(name + ".xml"))
        if r:
            rows.append(r)

    # standalone Orbis patch XMLs in mc4/ (not .mc4.xml sidecars)
    for name, data in mc4.items():
        low = name.lower()
        if not low.endswith(".xml") or low.endswith(".mc4.xml"):
            continue
        xml = _read_text(data)
        if not xml:
            continue
        tids = orbis_title_ids(xml)
        if not tids:
            continue
        cheats = orbis_cheats(xml)
        game, modder, version = attr(xml, "Title"), attr(xml, "Author"), attr(xml, "AppVer")
        for tid in tids:
            rows.append(Row(game, tid, version, "xml", modder, cheats))

    return rows


def group_to_index(rows: List[Row]) -> List[dict]:
    """Group rows by title id into the shipped index schema (one entry per game,
    formats map with hasFile/cheatsCount/cheats, cheatsTotal, creators)."""
    games: "OrderedDict[str, dict]" = OrderedDict()
    for r in rows:
        key = r.title_id.upper()
        if not key and not r.game:
            continue
        if key not in games:
            games[key] = {
                "id": r.title_id.upper(),
                "version": r.version,
                "title": r.game,
                "titleLower": r.game.lower(),
                "idLower": r.title_id.lower(),
                "cheatsTotal": 0,
                "creators": [],
                "creatorsLower": [],
                "formats": {},
            }
        g = games[key]
        if not g["title"] and r.game:
            g["title"] = r.game
            g["titleLower"] = r.game.lower()
        if not g["version"] and r.version:
            g["version"] = r.version
        # xml rows share the mc4 bucket semantics on-console; map to their own key
        fmt_key = r.format if r.format in ("json", "shn", "mc4") else "mc4"
        existing = g["formats"].get(fmt_key)
        if existing is None or (not existing.get("cheats") and r.cheats):
            g["formats"][fmt_key] = {
                "hasFile": True,
                "cheatsCount": len(r.cheats),
                "cheats": list(r.cheats),
            }
        if r.modder and r.modder not in g["creators"]:
            g["creators"].append(r.modder)
            g["creatorsLower"].append(r.modder.lower())

    out: List[dict] = []
    for g in games.values():
        g["cheatsTotal"] = sum(f.get("cheatsCount", 0) for f in g["formats"].values())
        out.append(g)
    out.sort(key=lambda e: (e["title"] or e["id"]).lower())
    return out


def _load_base_entries(path: Path) -> List[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"could not read base index {path}: {exc}")
        return []
    entries = data.get("entries") if isinstance(data, dict) else data
    return entries if isinstance(entries, list) else []


def main(argv: List[str]) -> int:
    args = list(argv[1:])
    base_path: Optional[Path] = None
    if "--merge" in args:
        i = args.index("--merge")
        try:
            base_path = Path(args[i + 1])
        except IndexError:
            print("--merge needs a path")
            return 2
        del args[i:i + 2]
    if len(args) != 2:
        print(__doc__)
        return 2
    seed = Path(args[0])
    out_path = Path(args[1])
    if not seed.exists():
        print(f"seed not found: {seed}")
        return 1

    buckets = load_seed(seed)
    counts = {k: len(v) for k, v in buckets.items()}
    print(f"seed files: {counts} (total {sum(counts.values())})")

    rows = build_rows(buckets)
    print(f"parsed rows: {len(rows)}")

    scanned = group_to_index(rows)
    print(f"games from scan: {len(scanned)}")

    if base_path is not None:
        base = _load_base_entries(base_path)
        base_ids = {str(e.get("id", "")).upper() for e in base}
        added = [e for e in scanned if e["id"].upper() not in base_ids]
        entries = list(base) + added
        entries.sort(key=lambda e: (e.get("title") or e.get("id") or "").lower())
        print(f"base games: {len(base)}  + added from scan: {len(added)}  = {len(entries)}")
    else:
        entries = scanned

    index = {"schema": 1, "generatedUtc": "", "entries": entries}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    with_cheats = sum(1 for e in entries if e["cheatsTotal"] > 0)
    print(f"games indexed: {len(entries)}  (with cheats: {with_cheats})")
    print(f"written: {out_path}  ({out_path.stat().st_size:,} bytes)")

    wolv = [e for e in entries if "wolver" in e["title"].lower() or e["id"] == "PPSA03671"]
    print(f"Wolverine check: {[(e['id'], e['title'], e['cheatsTotal']) for e in wolv]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
