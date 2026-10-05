"""Best-effort reader for a single cheat file the user adds to the library.

Its only job is to show a friendly cheat-name list in the UI — it never needs to
fully decode a file, because CheatRunner itself decodes/applies cheats on the
console. So:

* ``.json`` (GoldHEN) — parsed properly; cheat names are plain text in the JSON.
* ``.shn``  — if it is the plaintext/XML variant, names are pulled with a light
  regex; the encrypted ``SHNX`` variant has no readable names, so we return none.
* ``.mc4``  — an encrypted PS5 trainer container; names aren't readable without
  the on-console key, so we return none and just keep the file.

Every function fails soft: a malformed or unreadable file yields an empty name
list rather than raising, so adding a file can never crash the UI.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Tuple

SUPPORTED_EXTENSIONS = (".json", ".shn", ".mc4")

_NAME_ATTR_RE = re.compile(r'name\s*=\s*"([^"]{1,120})"', re.IGNORECASE)
_NAME_TAG_RE = re.compile(r"<name>\s*([^<]{1,120})\s*</name>", re.IGNORECASE)


def format_of(path) -> str:
    ext = Path(path).suffix.lower()
    return ext[1:] if ext in SUPPORTED_EXTENSIONS else "file"


def _names_from_json_obj(obj) -> List[str]:
    """Pull cheat names out of a GoldHEN-style JSON structure."""
    names: List[str] = []

    def visit(node) -> None:
        if isinstance(node, dict):
            # a cheat/mod node usually carries a name plus a type/address/hint
            label = node.get("name") or node.get("title") or node.get("text")
            if isinstance(label, str) and label.strip() and (
                "type" in node or "address" in node or "hint" in node or "mode" in node
            ):
                names.append(label.strip())
            for key in ("mods", "cheats", "codes", "trainers", "entries"):
                child = node.get(key)
                if isinstance(child, list):
                    for item in child:
                        visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(obj)
    # de-dupe preserving order
    seen = set()
    out = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def parse_cheat_file(path) -> Tuple[str, List[str], str]:
    """Return ``(format, cheat_names, note)`` for a cheat file.

    ``note`` is a short human string for the UI when names couldn't be read
    (e.g. encrypted container); empty when names were parsed fine.
    """
    p = Path(path)
    fmt = format_of(p)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return fmt, [], f"Could not read file: {exc}"

    if fmt == "json":
        try:
            obj = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError as exc:
            return fmt, [], f"Invalid JSON: {exc}"
        names = _names_from_json_obj(obj)
        return fmt, names, "" if names else "No cheat names found in this JSON."

    if fmt == "shn":
        if raw[:4] == b"SHNX":
            return fmt, [], "Encrypted .shn — cheats apply on the console."
        text = raw.decode("utf-8", errors="replace")
        names = _NAME_TAG_RE.findall(text) or _NAME_ATTR_RE.findall(text)
        names = [n.strip() for n in names if n.strip()]
        return fmt, names, "" if names else "No readable cheat names in this .shn."

    if fmt == "mc4":
        return fmt, [], "Encrypted .mc4 — cheats apply on the console."

    return fmt, [], "Unsupported file type."
