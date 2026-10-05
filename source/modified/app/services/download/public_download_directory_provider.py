from pathlib import Path


class PublicDownloadDirectoryProvider:
    """User-visible downloads root; never redirects to the app-private cache."""

    def __init__(self, base_provider):
        self._base_provider = base_provider

    def get(self, is_android: bool) -> Path:
        path = Path(self._base_provider.preferred(is_android=is_android))
        path.mkdir(parents=True, exist_ok=True)
        return path
