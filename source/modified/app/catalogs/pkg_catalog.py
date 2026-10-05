from __future__ import annotations

from typing import Iterable

from app.models.pkg import PkgSource
from app.services.catalog.catalog_contract import (
    CATALOG_APP,
    CATALOG_SCHEMA_VERSION,
    KIND_PKGS,
    stable_item_key,
)
from app.services.pkg.pkg_url_presentation import derive_pkg_presentation

PKG_INSTALLER_PORT = 9328
PKG_INSTALLER_MIN_VERSION = 14
PKG_UPLOAD_CHUNK_SIZE = 524288
PKG_INSTALL_STATUS_TIMEOUT_SECONDS = 900

REMOTE_PKG_CATALOG_SCHEMA_VERSION = CATALOG_SCHEMA_VERSION
REMOTE_PKG_CATALOG_APP = CATALOG_APP
REMOTE_PKG_CATALOG_URL = 'https://raw.githubusercontent.com/ps4macedo/sendpp/main/catalogs/pkg_catalog.json'

KSTUFF_BASE_URL = 'https://github.com/EchoStretch/kstuff-lite/releases/download/v1.10/kstuff.elf'
KSTUFF_ASSET_NAME = 'kstuff.elf'

PKG_URLS = (
    'https://github.com/TheWizWikii/PS5-Stuff/releases/download/hombrew/YouTube.app.PPSA01650.version.USA.01.000.030.pkg',
    'https://github.com/TheWizWikii/PS5-Stuff/releases/download/hombrew/YouTube_App_1.03_PPSA01650.pkg',
    'https://pkg-zone.com/download/ps5/PPSA01615/6.00',
    'https://pkg-zone.com/download/ps5/LAPY20011/1.05',
    'https://pkg-zone.com/download/ps5/LAPY20016/1.00',
    'https://pkg-zone.com/download/ps5/LAPY20012/1.00',
    'https://github.com/ps5-payload-dev/websrv/releases/download/v0.30/IV9999-FAKE00000_00-HOMEBREWLOADER01.pkg',
    'https://pkg-zone.com/download/ps5/PKGI13337/latest',
)


def build_pkg_source(url: str, *, key: str = '', name_override: str = '') -> PkgSource:
    normalized = str(url or '').strip()
    if not normalized:
        raise ValueError('pkg_source_invalid')
    name, version = derive_pkg_presentation(normalized)
    return PkgSource(
        key=str(key or '').strip() or stable_item_key(KIND_PKGS, normalized),
        name=name,
        version=version,
        url=normalized,
        name_override=str(name_override or '').strip(),
    )


def build_pkg_sources(urls: Iterable[str] = PKG_URLS) -> tuple[PkgSource, ...]:
    sources = tuple(build_pkg_source(url) for url in urls)
    keys = [source.key.lower() for source in sources]
    urls_seen = [source.url.lower() for source in sources]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate_pkg_source')
    if len(urls_seen) != len(set(urls_seen)):
        raise ValueError('duplicate_pkg_source_url')
    return sources


PKG_SOURCES = build_pkg_sources()
