"""Resolves and delivers the current kstuff-lite build to a PS5.

Mirrors :class:`app.services.xeno.cheatrunner_release_service.CheatRunnerReleaseService`
exactly, pointed at ``EchoStretch/kstuff-lite`` instead. Kept as its own small file rather
than a shared abstraction so each payload's resolution logic stays easy to read on its own —
there are only two of these.

This is a separate resolver from :class:`app.services.pkg.kstuff_dependency_service
.KstuffDependencyService`, which exists to serve the PKG/fPKG install flow (a persisted,
"never downgrade" dependency cached under its own fixed directory). The Trainers auto-loader
wants a plain "fetch the newest build and send it" action, same as every other payload in
the Payloads tab, so it resolves fresh every time instead of reusing that cached URL.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from app.services.download.http_download_service import HttpDownloadService
from app.services.payload.payload_tcp_sender import PayloadTcpSender
from app.services.releases.github_release_service import GitHubReleaseService

ProgressCallback = Callable[[object], None]

KSTUFF_OWNER = "EchoStretch"
KSTUFF_REPO = "kstuff-lite"


class KstuffElfReleaseService:
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
        """Returns ``(asset_filename, download_url)`` for the latest kstuff.elf."""
        release = self._github.latest_release(KSTUFF_OWNER, KSTUFF_REPO)
        if release is None:
            raise RuntimeError("Não foi possível obter a última versão do kstuff no GitHub.")
        matches = [asset for asset in release.assets if "kstuff" in asset.lower()]
        if len(matches) != 1:
            raise RuntimeError(
                "Não foi possível identificar de forma única o asset do kstuff na release "
                f"{release.tag} ({len(matches)} candidato(s) encontrado(s))."
            )
        asset = matches[0]
        url = self._github.build_download_url(KSTUFF_OWNER, KSTUFF_REPO, release.tag, asset)
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
            display_name="kstuff",
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
