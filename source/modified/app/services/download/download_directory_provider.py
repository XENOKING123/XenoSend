import os
from pathlib import Path


class DownloadDirectoryProvider:
    DOWNLOAD_SUBDIR = "ps5_downloads"

    def __init__(self, fallback_root: Path):
        self._fallback_root = Path(fallback_root)

    def preferred(self, is_android: bool) -> Path:
        """Return the canonical public downloads root without private fallback."""
        return self._preferred_directory(is_android)

    def get(self, is_android: bool) -> Path:
        preferred = self.preferred(is_android)
        if self._ensure_writable(preferred):
            return preferred

        fallback = self._fallback_root / self.DOWNLOAD_SUBDIR
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def _preferred_directory(self, is_android: bool) -> Path:
        if is_android:
            try:
                from android.storage import primary_external_storage_path

                return Path(primary_external_storage_path()) / "Download" / self.DOWNLOAD_SUBDIR
            except Exception:
                return Path.home() / "Download" / self.DOWNLOAD_SUBDIR

        downloads = Path.home() / "Downloads"
        if not downloads.is_dir():
            downloads = Path.home() / "Download"
        return downloads / self.DOWNLOAD_SUBDIR

    @staticmethod
    def _ensure_writable(directory: Path) -> bool:
        probe = directory / ".write_test"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with probe.open("wb") as handle:
                handle.write(b"1")
            try:
                probe.unlink()
            except OSError:
                pass
            return True
        except OSError:
            return False
