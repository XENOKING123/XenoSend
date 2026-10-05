from __future__ import annotations

from typing import Iterable

from app.models.payload import PayloadSource
from app.services.catalog.catalog_contract import (
    CATALOG_APP,
    CATALOG_SCHEMA_VERSION,
    KIND_PAYLOADS,
    stable_item_key,
)
from app.services.payload.payload_url_presentation import (
    derive_payload_presentation,
    normalize_payload_url,
)

REMOTE_PAYLOAD_CATALOG_SCHEMA_VERSION = CATALOG_SCHEMA_VERSION
REMOTE_PAYLOAD_CATALOG_APP = CATALOG_APP
REMOTE_PAYLOAD_CATALOG_URL = "https://raw.githubusercontent.com/ps4macedo/sendpp/main/catalogs/payload_catalog.json"

PAYLOAD_URLS = (
    "https://github.com/ps4macedo/p2jb-relapse/releases/download/1.0/Y2JB_RELAPSE_theme.elf",
    "https://github.com/ps4macedo/ps51360/releases/download/relapse-v1.2.3/Host-PSM-ReLapse-v1.2.3-instala-host-pt.elf",
    "https://github.com/ps4macedo/ps51360/releases/download/relapse-v1.2.3/Host-PSM-ReLapse-v1.2.3-instala-host-en.elf",
    "https://github.com/nexgen999/PS5-Super-PLDMGR-Auto-Updater/raw/refs/heads/main/Internal/payloads/beta/a53_ppr/a53_ppr_install_fast_v15.09.elf",
    "https://github.com/EchoStretch/kstuff-lite/releases/download/v1.11/kstuff.elf",
    "https://github.com/drakmor/ShadowMountPlus/releases/download/1.7beta3/ShadowMountPlus_1.7beta3.zip",
    "https://github.com/nexgen999/PS5-Super-PLDMGR-Auto-Updater/raw/refs/heads/main/Internal/payloads/beta/Kstuff-NG/Kstuff-NG_v1.00.elf",
    "https://github.com/ps5-payload-dev/ftpsrv/releases/download/v0.21.1/ftpsrv-ps5.elf",
    "https://github.com/notmaj0r/ProsperoMgr/releases/download/v1.1/ProsperoMgr.elf",
    "https://github.com/drakmor/ftpsrv/releases/download/1.16-ng-test1/ftpsrv-ps5.elf",
    "https://github.com/itsPLK/ps5-payload-manager/releases/download/v0.5.2/pldmgr_v0.5.2.elf",
    "https://github.com/tsuramatsu1/apr-emu-updater/releases/download/v2.0.6/apr_emu_updater_v2.0.6.elf",
    "https://github.com/aydencharles/onionHEN/releases/download/v0.0.13/OnionHEN.elf",
    "https://github.com/itsPLK/ps5-pkg-manager/releases/download/v1.4.1/pkg-manager_v1.4.1.elf",
    "https://github.com/Gezine/BD-UN-JB/releases/download/1.1/bdj_unpatch_1340.elf",
    "https://github.com/ArkSama/PS5-Lapy-JB-Daemon/raw/main/lapy_jb_daemon.elf",
    "https://github.com/drakmor/nanoDNS/releases/download/0.4/nanodns-ps4.elf",
    "https://git.etawen.dev/soniciso/elf-arsenal/releases/download/v1.6.0/elf-arsenal.elf",
    "https://github.com/pegasus-ps5/pegasus-dl/releases/download/v1.10.1/pegasus_dl.elf",
    "https://github.com/notmaj0r/CheatRunner/releases/download/v0.17.2/CheatRunner.elf",
    "https://github.com/earthonion/np-fake-signin/releases/download/1.1/np-fake-signin-ps5.elf",
    "https://github.com/BestPig/BackPork/releases/download/0.1/ps5-backpork.elf",
    "https://github.com/ps4macedo/y2jb-p2jb/releases/download/1.0/P2JB_ASTRO_theme.elf",
    "https://github.com/ps4macedo/y2jb-p2jb/releases/download/1.0/P2JB_ZA_theme.elf",
    "https://github.com/ps4macedo/y2jb-p2jb/releases/download/1.0/TLOU_theme.elf",
    "https://github.com/matem6/P2JB-Y2JB-Porting/releases/download/2.6/p2jb.js",
    "https://github.com/Gezine/Y2JB/raw/main/payloads/lapse.js",
    "https://github.com/ps4macedo/ps51360/releases/download/relapse-v1.3.0/Host-PSM-ReLapse-v1.3.0-instala-host-en.elf",
)


def build_payload_source(url: str, *, key: str = "", name_override: str = "") -> PayloadSource:
    normalized = normalize_payload_url(url)
    name, version = derive_payload_presentation(normalized)
    return PayloadSource(
        key=str(key or "").strip() or stable_item_key(KIND_PAYLOADS, normalized),
        name=name,
        version=version,
        url=normalized,
        name_override=str(name_override or "").strip(),
    )


def build_payload_sources(urls: Iterable[str] = PAYLOAD_URLS) -> tuple[PayloadSource, ...]:
    sources = tuple(build_payload_source(url) for url in urls)
    keys = [source.key for source in sources]
    urls_seen = [source.url.lower() for source in sources]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate_payload_source")
    if len(urls_seen) != len(set(urls_seen)):
        raise ValueError("duplicate_payload_source_url")
    return sources


PAYLOAD_SOURCES = build_payload_sources()
