"""Resolves and delivers the current CheatRunner.elf build to a PS5.

Mirrors the app's existing Payload-send flow exactly: download via
:class:`HttpDownloadService` (cache + ``.part`` + atomic replace, for free), then push via
:class:`PayloadTcpSender` — just hardcoded to the single asset published by
``notmaj0r/CheatRunner`` on GitHub, resolved fresh from the latest release every time
(unlike the dependency-style services in ``app/services/pkg``, this does not persist a
resolved URL between runs).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from app.services.download.http_download_service import HttpDownloadService
from app.services.payload.payload_tcp_sender import PayloadTcpSender
from app.services.releases.github_release_service import GitHubReleaseService

ProgressCallback = Callable[[object], None]

CHEATRUNNER_OWNER = "notmaj0r"
CHEATRUNNER_REPO = "CheatRunner"


class CheatRunnerReleaseService:
    def __init__(
        self,
        github: GitHubReleaseService,
        downloader: HttpDownloadService,
        sender: PayloadTcpSender,
    ) -> None:
        self._github = github
        self._downloader = downloader
        self._sender = sender

    def resolve_asset(self) -> tuple[str, str]:
        """Returns ``(asset_filename, download_url)`` for the latest CheatRunner.elf."""
        release = self._github.latest_release(CHEATRUNNER_OWNER, CHEATRUNNER_REPO)
        if release is None:
            raise RuntimeError(
                "Não foi possível obter a última versão do CheatRunner no GitHub."
            )
        matches = [asset for asset in release.assets if "cheatrunner" in asset.lower()]
        if len(matches) != 1:
            raise RuntimeError(
                "Não foi possível identificar de forma única o asset do CheatRunner na "
                f"release {release.tag} ({len(matches)} candidato(s) encontrado(s))."
            )
        asset = matches[0]
        url = self._github.build_download_url(
            CHEATRUNNER_OWNER, CHEATRUNNER_REPO, release.tag, asset
        )
        return asset, url

    def download(
        self,
        *,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
    ) -> Path:
        asset, url = self.resolve_asset()
        return self._downloader.download(
            filename=asset,
            url=url,
            is_android=is_android,
            progress=progress,
            display_name="CheatRunner",
        )

    def send(
        self,
        *,
        host: str,
        port: int,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
    ) -> Path:
        path = self.download(is_android=is_android, progress=progress)
        self._sender.send(host=host, port=port, payload_path=path, progress=progress)
        return path
