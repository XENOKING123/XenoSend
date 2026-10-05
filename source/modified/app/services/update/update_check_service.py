from dataclasses import dataclass
from typing import Any, Optional

try:
    import requests
except ImportError:
    requests = None

from app.app_meta import APP_VERSION
from app.services.releases.github_release_service import compare_release_versions

LATEST_RELEASE_URL = "https://api.github.com/repos/XENOKING123/XenoSend/releases/latest"
_REQUEST_TIMEOUT = (3.05, 8)
_REQUEST_HEADERS = {"User-Agent": "PS5-Send-PKG-Payload"}


@dataclass(frozen=True)
class UpdateInfo:
    tag: str
    url: str


class UpdateCheckService:
    """Checks whether a newer SendPP release exists on GitHub.

    Best-effort and silent: any network, HTTP or parsing failure simply means "no update
    found" (``None``). A tag that cannot be proven newer than :data:`APP_VERSION` (an
    unparseable tag, a tie, or an older/equal release) is never reported as an update.
    """

    def __init__(self, session: Optional[Any] = None):
        self._session = session

    def check(self) -> Optional[UpdateInfo]:
        try:
            return self._check()
        except Exception:
            return None

    def _check(self) -> Optional[UpdateInfo]:
        session = self._session
        if session is None:
            if requests is None:
                return None
            session = requests

        response = session.get(
            LATEST_RELEASE_URL, timeout=_REQUEST_TIMEOUT, headers=_REQUEST_HEADERS
        )
        status = int(getattr(response, "status_code", 0) or 0)
        if not 200 <= status < 300:
            return None

        payload = response.json()
        if not isinstance(payload, dict):
            return None

        raw_tag = str(payload.get("tag_name") or "").strip()
        url = str(payload.get("html_url") or "").strip()
        if not raw_tag or not url:
            return None

        stripped_tag = raw_tag[1:] if raw_tag[:1] in ("v", "V") else raw_tag
        if not stripped_tag:
            return None

        if compare_release_versions(APP_VERSION, stripped_tag) != -1:
            return None

        return UpdateInfo(tag=raw_tag, url=url)
