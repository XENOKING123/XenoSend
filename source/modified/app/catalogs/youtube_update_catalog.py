from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Iterable
from urllib.parse import unquote, urlparse

from app.models.youtube_update import (
    YOUTUBE_UPDATE_ALLOWED_EXTENSIONS,
    YOUTUBE_UPDATE_TARGET_DIR,
    YOUTUBE_UPDATE_TARGET_NAME,
    YouTubeUpdateSource,
)
from app.services.catalog.catalog_contract import (
    CATALOG_APP,
    CATALOG_SCHEMA_VERSION,
    KIND_YOUTUBE,
    stable_item_key,
)
from app.services.payload.payload_url_presentation import (
    derive_payload_presentation,
    normalize_payload_url,
)

REMOTE_YOUTUBE_UPDATE_CATALOG_SCHEMA_VERSION = CATALOG_SCHEMA_VERSION
REMOTE_YOUTUBE_UPDATE_CATALOG_APP = CATALOG_APP
REMOTE_YOUTUBE_UPDATE_CATALOG_URL = 'https://raw.githubusercontent.com/ps4macedo/sendpp/main/catalogs/youtube_update_catalog.json'

_RELEASE_PATH_RE = re.compile(r'/releases/download/(?P<tag>[^/]+)/(?P<asset>[^/?#]+)$', re.IGNORECASE)

YOUTUBE_UPDATE_URLS = (
    'https://github.com/ps4macedo/p2jb-relapse/releases/download/1.0/Y2JB_RELAPSE_AUTO_PSM.zip',
    'https://github.com/ps4macedo/y2jb-p2jb/releases/download/1.0/Y2JB_P2JB_AUTO_PSM.zip',
    'https://github.com/Gezine/Y2JB/releases/download/1.6/Y2JB_download0_1.6.zip',
    'https://github.com/itsPLK/ps5-y2jb-autoloader/releases/download/v1.0.0-dev-a05c279/download0.dat',
)


def normalize_youtube_update_url(url: str) -> str:
    normalized = normalize_payload_url(url)
    filename = unquote(PurePosixPath(urlparse(normalized).path).name).strip().lower()
    if not filename.endswith(YOUTUBE_UPDATE_ALLOWED_EXTENSIONS):
        raise ValueError('youtube_update_url_extension_invalid')
    return normalized


def derive_youtube_update_presentation(url: str) -> tuple[str, str]:
    normalized = normalize_youtube_update_url(url)
    name, version = derive_payload_presentation(normalized)
    if version:
        return (name, version)
    release_match = _RELEASE_PATH_RE.search(unquote(urlparse(normalized).path or ''))
    release_tag = unquote(release_match.group('tag')).strip() if release_match else ''
    return (name, release_tag)


def build_youtube_update_source(url: str, *, key: str = '', name_override: str = '') -> YouTubeUpdateSource:
    normalized = normalize_youtube_update_url(url)
    name, version = derive_youtube_update_presentation(normalized)
    return YouTubeUpdateSource(
        key=str(key or '').strip() or stable_item_key(KIND_YOUTUBE, normalized),
        name=name,
        version=version,
        url=normalized,
        name_override=str(name_override or '').strip(),
        remote_dir=YOUTUBE_UPDATE_TARGET_DIR,
        remote_name=YOUTUBE_UPDATE_TARGET_NAME,
    )


def build_youtube_update_sources(urls: Iterable[str] = YOUTUBE_UPDATE_URLS) -> tuple[YouTubeUpdateSource, ...]:
    sources = tuple(build_youtube_update_source(url) for url in urls)
    keys = [source.key for source in sources]
    urls_seen = [source.url.lower() for source in sources]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate_youtube_update_source')
    if len(urls_seen) != len(set(urls_seen)):
        raise ValueError('duplicate_youtube_update_source_url')
    return sources


YOUTUBE_UPDATE_SOURCES = build_youtube_update_sources()
