from pathlib import Path


class SubdirectoryDirectoryProvider:
    """Adds one stable child directory to an existing download provider."""

    def __init__(self, base_provider, subdirectory: str):
        self._base_provider = base_provider
        self._subdirectory = str(subdirectory).strip().strip("/\\")
        if not self._subdirectory:
            raise ValueError("subdirectory_required")

    def get(self, is_android: bool) -> Path:
        path = Path(self._base_provider.get(is_android=is_android)) / self._subdirectory
        path.mkdir(parents=True, exist_ok=True)
        return path
