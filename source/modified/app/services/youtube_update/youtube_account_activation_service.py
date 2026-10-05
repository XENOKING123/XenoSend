from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from app.models.youtube_update import YouTubeUpdateProgress
from app.services.payload.payload_tcp_sender import PayloadTcpSender
from app.services.youtube_update.youtube_account_activation_asset_provider import (
    YouTubeAccountActivationAssetProvider,
)

ProgressCallback = Callable[[YouTubeUpdateProgress], None]


@dataclass(frozen=True)
class YouTubeAccountActivationResult:
    bytes_sent: int


class YouTubeAccountActivationService:
    """Envia o módulo PS5 interno que ativa offline a conta local atual.

    A alteração real acontece no PS5, porque depende do RegMgr. Este serviço
    só entrega o módulo interno ao loader já usado pelo aplicativo.
    """

    def __init__(
        self,
        *,
        payload_sender: PayloadTcpSender,
        asset_provider: YouTubeAccountActivationAssetProvider,
    ):
        self._payload_sender = payload_sender
        self._asset_provider = asset_provider

    def activate_current_account(
        self,
        *,
        host: str,
        loader_port: int,
        progress: Optional[ProgressCallback] = None,
    ) -> YouTubeAccountActivationResult:
        payload_path = self._asset_provider.get()
        self._emit(progress, "Enviando ativação para o PS5...", 0)
        bytes_sent = self._payload_sender.send(
            host=host,
            port=loader_port,
            payload_path=payload_path,
            progress=None,
        )
        self._emit(progress, "Ativação enviada ao PS5.", 100)
        return YouTubeAccountActivationResult(bytes_sent=bytes_sent)

    @staticmethod
    def _emit(callback: Optional[ProgressCallback], message: str, percent: Optional[int]) -> None:
        if callback is not None:
            callback(YouTubeUpdateProgress(message=message, percent=percent))
