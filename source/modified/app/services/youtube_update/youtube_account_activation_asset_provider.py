from pathlib import Path


class YouTubeAccountActivationAssetProvider:
    """Resolve o payload interno de ativação offline da conta local.

    O arquivo é gerado pelo build do próprio projeto a partir de
    tools/ps5/account_activator. Não é dependência do ProsperoMgr.
    """

    FILE_NAME = "sendpp-account-activator.elf"

    def __init__(self, asset_path: Path | None = None):
        self._asset_path = (
            Path(asset_path)
            if asset_path is not None
            else Path(__file__).resolve().parents[2] / "assets" / "youtube_update" / self.FILE_NAME
        )

    def get(self) -> Path:
        path = self._asset_path
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(
                "Módulo interno de ativação não foi gerado. Gere o projeto pelo build unificado para compilar o recurso PS5 interno."
            )
        return path
