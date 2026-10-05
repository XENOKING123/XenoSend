import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

_RELEASE_PATH_RE = re.compile(
    r"/releases/download/(?P<tag>[^/]+)/(?P<asset>[^/?#]+)$",
    re.IGNORECASE,
)

_ASSET_VERSION_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<version>v?\d+(?:[._-]\d+)+(?:[A-Za-z]+\d*)?(?:[-_.][A-Za-z]+\d*)*)(?![A-Za-z0-9])",
    re.IGNORECASE,
)

_PLATFORM_EDGE_RE = re.compile(
    r"(?i)(?:^(?:ps5|ps4)[-_.]+|[-_.]+(?:ps5|ps4)$)"
)


def normalize_payload_url(url: str) -> str:
    normalized = str(url or "").strip()
    if not normalized:
        raise ValueError("payload_url_required")

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("payload_url_invalid")
    return normalized


def derive_payload_presentation(url: str) -> tuple[str, str]:
    """Derive display name/version deterministically from the effective URL."""
    normalized = normalize_payload_url(url)
    parsed = urlparse(normalized)
    path = unquote(parsed.path or "")
    file_name = PurePosixPath(path).name
    stem = PurePosixPath(file_name).stem

    release_match = _RELEASE_PATH_RE.search(path)
    release_tag = unquote(release_match.group("tag")).strip() if release_match else ""

    asset_version_match = _ASSET_VERSION_RE.search(stem)
    asset_version = asset_version_match.group("version").strip() if asset_version_match else ""

    release_version_is_displayable = _is_displayable_release_tag(release_tag)
    version = release_tag if release_version_is_displayable else asset_version

    name_version = (
        _release_version_token_in_stem(stem, release_tag)
        if release_version_is_displayable
        else ""
    ) or asset_version

    asset_candidate = _clean_name_candidate(stem, name_version)
    repo_candidate = _clean_name_candidate(_repository_slug(path), "")

    candidate = _choose_name_candidate(
        asset_candidate=asset_candidate,
        repo_candidate=repo_candidate,
        is_release=release_match is not None,
    )

    if not candidate:
        candidate = "Payload"

    return _format_display_name(candidate), version


def _is_displayable_release_tag(tag: str) -> bool:
    value = str(tag or "").strip()
    if not value or not re.search(r"\d", value):
        return False
    if re.fullmatch(r"\d+", value):
        return False
    return bool(re.search(r"[._-]", value) or re.match(r"^[vV]?\d", value))


def _release_version_token_in_stem(stem: str, release_tag: str) -> str:
    """Retorna somente a tag comprovadamente presente no nome do asset.

    Também aceita a forma sem o prefixo ``v`` quando a tag o possui. O valor
    retornado vem do próprio asset, preservando caixa e permitindo remoção
    exata, sem heurística sobre os segmentos que aparecem depois da versão.
    """
    value = str(release_tag or "").strip()
    if not value:
        return ""

    candidates = [value]
    if len(value) > 1 and value[0] in {"v", "V"} and value[1].isdigit():
        candidates.append(value[1:])

    for candidate in candidates:
        match = re.search(
            rf"(?<![A-Za-z0-9]){re.escape(candidate)}(?![A-Za-z0-9])",
            stem,
            re.IGNORECASE,
        )
        if not match:
            continue
        return match.group(0)
    return ""


def _repository_slug(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    for marker in ("releases", "raw"):
        try:
            index = parts.index(marker)
        except ValueError:
            continue
        if index > 0:
            return parts[index - 1]
    return ""


def _clean_name_candidate(value: str, explicit_version: str) -> str:
    candidate = str(value or "").strip()
    if explicit_version:
        candidate = candidate.replace(explicit_version, "", 1)
    candidate = _PLATFORM_EDGE_RE.sub("", candidate)
    candidate = re.sub(r"[-_.]+", " ", candidate).strip()
    return candidate


def _choose_name_candidate(*, asset_candidate: str, repo_candidate: str, is_release: bool) -> str:
    if not asset_candidate:
        return repo_candidate
    if not repo_candidate or not is_release:
        return asset_candidate

    asset_key = _comparison_key(asset_candidate)
    repo_key = _comparison_key(repo_candidate)

    if asset_key == repo_key:
        return repo_candidate

    if (
        len(asset_candidate.split()) == 1
        and len(asset_key) <= 7
        and len(repo_candidate.split()) >= 2
    ):
        return repo_candidate

    return asset_candidate


def _comparison_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _format_display_name(value: str) -> str:
    words = []
    for word in value.split():
        if any(char.isupper() for char in word):
            words.append(word)
            continue
        if any(char.isdigit() for char in word):
            words.append(word.upper())
            continue
        if len(word) <= 3:
            words.append(word.upper())
            continue
        words.append(word.capitalize())
    return " ".join(words)
