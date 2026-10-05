from __future__ import annotations

import hashlib
import re
from typing import Callable, Iterable

CATALOG_SCHEMA_VERSION = 2
CATALOG_APP = 'sendpp'
KIND_PAYLOADS = 'payloads'
KIND_PKGS = 'pkgs'
KIND_YOUTUBE = 'youtube_updates'
CATALOG_KINDS = (KIND_PAYLOADS, KIND_PKGS, KIND_YOUTUBE)
MAX_NAME_OVERRIDE_LENGTH = 120
_ITEM_KEY_RE = re.compile('^[a-z0-9][a-z0-9._-]{2,79}$')

_KIND_PREFIX = {
    KIND_PAYLOADS: 'payload',
    KIND_PKGS: 'pkg',
    KIND_YOUTUBE: 'youtube-update',
}


def stable_item_key(kind: str, url: str) -> str:
    if kind not in _KIND_PREFIX:
        raise ValueError('catalog_kind_invalid')
    normalized = str(url or '').strip()
    if not normalized:
        raise ValueError('catalog_url_required')
    digest = hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]
    return f'{_KIND_PREFIX[kind]}-{digest}'


def normalize_item_key(raw_key: object) -> str:
    key = str(raw_key or '').strip().lower()
    if not key or _ITEM_KEY_RE.fullmatch(key) is None:
        raise ValueError('catalog_item_key_invalid')
    return key


def normalize_name_override(raw_name: object) -> str:
    name = str(raw_name or '').strip()
    if len(name) > MAX_NAME_OVERRIDE_LENGTH:
        raise ValueError('catalog_name_override_too_long')
    return name


def normalize_catalog_items(
    payload: object,
    *,
    expected_kind: str,
    url_normalizer: Callable[[object], str],
    max_items: int,
) -> tuple[dict[str, str], ...]:
    if not isinstance(payload, dict):
        raise ValueError('catalog_root_invalid')
    if payload.get('schema_version') != CATALOG_SCHEMA_VERSION:
        raise ValueError('catalog_schema_invalid')
    if str(payload.get('app', '') or '').strip() != CATALOG_APP:
        raise ValueError('catalog_app_invalid')
    if str(payload.get('kind', '') or '').strip() != expected_kind:
        raise ValueError('catalog_kind_invalid')

    raw_items = payload.get('items')
    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > max_items:
        raise ValueError('catalog_items_invalid')

    result = []
    seen_keys = set()
    seen_urls = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ValueError('catalog_item_invalid')
        key = normalize_item_key(raw.get('key'))
        url = url_normalizer(raw.get('url'))
        name_override = normalize_name_override(raw.get('name_override'))
        key_lower = key.lower()
        url_lower = url.lower()
        if key_lower in seen_keys:
            raise ValueError('catalog_duplicate_key')
        if url_lower in seen_urls:
            raise ValueError('catalog_duplicate_url')
        seen_keys.add(key_lower)
        seen_urls.add(url_lower)
        item = {'key': key, 'url': url}
        if name_override:
            item['name_override'] = name_override
        result.append(item)
    return tuple(result)


def catalog_document(kind: str, items: Iterable[dict[str, str]], *, catalog_version: str = '') -> dict:
    if kind not in CATALOG_KINDS:
        raise ValueError('catalog_kind_invalid')
    normalized_items = []
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError('catalog_item_invalid')
        key = normalize_item_key(raw.get('key'))
        url = str(raw.get('url') or '').strip()
        if not url:
            raise ValueError('catalog_url_required')
        name_override = normalize_name_override(raw.get('name_override'))
        row = {'key': key, 'url': url}
        if name_override:
            row['name_override'] = name_override
        normalized_items.append(row)
    document = {
        'schema_version': CATALOG_SCHEMA_VERSION,
        'app': CATALOG_APP,
        'kind': kind,
    }
    if str(catalog_version or '').strip():
        document['catalog_version'] = str(catalog_version).strip()
    document['items'] = normalized_items
    return document
