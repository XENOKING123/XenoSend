from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from app.services.payload.payload_url_presentation import derive_payload_presentation, normalize_payload_url

_VERSION_ENDPOINT_RE = re.compile(r"^(?:v?\d+(?:[._-][a-z0-9]+)*)$", re.IGNORECASE)


def derive_pkg_presentation(url: str) -> tuple[str, str]:
    """Deriva nome e versão exclusivamente da URL efetiva do PKG.

    URLs diretas para .pkg reaproveitam o mesmo parser determinístico dos
    payloads. Endpoints versionados (como pkg-zone/.../<content-id>/<versão>)
    usam o content-id como nome automático e o último segmento como versão.
    Um nome personalizado, quando existir, é aplicado fora desta função.
    """
    normalized = normalize_payload_url(url)
    parsed = urlparse(normalized)
    path = unquote(parsed.path or "")
    filename = PurePosixPath(path).name.strip()

    if filename.lower().endswith(".pkg"):
        return derive_payload_presentation(normalized)

    parts = [unquote(part).strip() for part in path.split("/") if part.strip()]
    if not parts:
        return "PKG", ""

    endpoint = parts[-1]
    version = endpoint if _VERSION_ENDPOINT_RE.fullmatch(endpoint) else ""
    if endpoint.lower() == "latest":
        version = ""

    candidate = parts[-2] if len(parts) >= 2 else "PKG"
    return _format_pkg_name(candidate), version


def _format_pkg_name(value: str) -> str:
    text = re.sub(r"[-_.]+", " ", str(value or "").strip()).strip()
    if not text:
        return "PKG"
    words = []
    for word in text.split():
        if any(char.isupper() for char in word) or any(char.isdigit() for char in word):
            words.append(word)
        elif len(word) <= 3:
            words.append(word.upper())
        else:
            words.append(word.capitalize())
    return " ".join(words)
