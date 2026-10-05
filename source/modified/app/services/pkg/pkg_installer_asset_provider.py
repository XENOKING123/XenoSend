from pathlib import Path


class PkgInstallerAssetProvider:
    FILE_NAME = 'pkg-installer.elf'

    def __init__(self, asset_path: Path | None = None):
        self._asset_path = (
            Path(asset_path)
            if asset_path is not None
            else Path(__file__).resolve().parents[2] / 'assets' / 'pkg' / self.FILE_NAME
        )

    def get(self) -> Path:
        path = self._asset_path
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError('pkg-installer.elf interno não está disponível.')
        return path
