import os
from pathlib import Path
from typing import Callable, Optional

import requests

from app.models.y2jb_backup import Y2JBBackupProgress
from app.services.download.download_directory_provider import DownloadDirectoryProvider


ProgressCallback = Callable[[Y2JBBackupProgress], None]


class HttpDownloadService:
    CHUNK_SIZE = 1024 * 1024
    TIMEOUT_SECONDS = 30

    def __init__(
        self,
        directory_provider: DownloadDirectoryProvider,
        request_get=None,
    ):
        self._directory_provider = directory_provider
        self._request_get = request_get or requests.get

    def download(
        self,
        *,
        filename: str,
        url: str,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
        display_name: Optional[str] = None,
    ) -> Path:
        base_dir = self._directory_provider.get(is_android=is_android)
        destination = base_dir / filename
        metadata_path = Path(str(destination) + ".url")

        if self._cache_matches(destination, metadata_path, url):
            cache_message = (
                "Backup já está no cache local."
                if not display_name
                else f"{display_name} já está no cache local."
            )
            self._emit(progress, cache_message, 100)
            return destination

        self._remove_if_exists(destination)
        self._remove_if_exists(metadata_path)

        partial = Path(str(destination) + ".part")
        self._remove_if_exists(partial)
        download_message = (
            "Baixando backup..." if not display_name else f"Baixando {display_name}..."
        )
        self._emit(progress, download_message, 0)

        try:
            response = self._request_get(url, stream=True, timeout=self.TIMEOUT_SECONDS)
            try:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", "0") or "0")
                downloaded = 0
                last_bucket = -1

                with partial.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded += len(chunk)

                        if total > 0:
                            percent = min(100, int(downloaded * 100 / total))
                            bucket = percent // 5
                            if bucket != last_bucket:
                                last_bucket = bucket
                                self._emit(progress, download_message, percent)
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(partial, destination)
            except OSError:
                with partial.open("rb") as source, destination.open("wb") as target:
                    while True:
                        chunk = source.read(self.CHUNK_SIZE)
                        if not chunk:
                            break
                        target.write(chunk)
                self._remove_if_exists(partial)
        except Exception as exc:
            self._remove_if_exists(partial)
            raise RuntimeError(f"Falha ao baixar {filename}: {exc}") from exc

        try:
            metadata_path.write_text(url.strip(), encoding="utf-8")
        except OSError:
            pass

        self._emit(progress, "Download concluído.", 100)
        return destination

    @staticmethod
    def _cache_matches(destination: Path, metadata_path: Path, url: str) -> bool:
        try:
            if not destination.is_file() or destination.stat().st_size <= 0:
                return False
            if not metadata_path.is_file():
                return False
            return metadata_path.read_text(encoding="utf-8").strip() == url.strip()
        except OSError:
            return False

    @staticmethod
    def _remove_if_exists(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    @staticmethod
    def _emit(
        callback: Optional[ProgressCallback],
        message: str,
        percent: Optional[int],
    ) -> None:
        if callback is not None:
            callback(Y2JBBackupProgress(message=message, percent=percent))
