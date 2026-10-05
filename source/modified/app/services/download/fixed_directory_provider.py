from pathlib import Path


class FixedDirectoryProvider:
    """Writable application-private directory provider."""

    def __init__(self, path: Path):
        self._path = Path(path)

    def get(self, is_android: bool) -> Path:
        self._path.mkdir(parents=True, exist_ok=True)
        return self._path
