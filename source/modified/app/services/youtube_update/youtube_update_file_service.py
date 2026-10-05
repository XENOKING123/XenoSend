from __future__ import annotations

import os
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable, Optional
from urllib.parse import unquote, urlparse

try:
    import requests
except ImportError:
    requests = None

from app.models.youtube_update import (
    YOUTUBE_UPDATE_ALLOWED_EXTENSIONS,
    YOUTUBE_UPDATE_TARGET_NAME,
    YouTubeUpdateProgress,
    YouTubeUpdateSource,
)
from app.services.download.download_directory_provider import DownloadDirectoryProvider


ProgressCallback = Callable[[YouTubeUpdateProgress], None]


class YouTubeUpdateFileService:
    CHUNK_SIZE = 1024 * 1024
    TIMEOUT_SECONDS = 30
    LOCAL_FOLDER_NAME = 'ps5_youtube_updates'
    ARCHIVE_FOLDER_NAME = 'youtube_update_archives'

    def __init__(
        self,
        directory_provider: DownloadDirectoryProvider,
        request_get=None,
    ):
        self._directory_provider = directory_provider
        self._request_get = request_get or self._default_request_get

    def local_update_directory(self, *, is_android: bool) -> Path:
        folder = self._directory_provider.get(is_android=is_android) / self.LOCAL_FOLDER_NAME
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def list_local_updates(self, *, is_android: bool) -> tuple[Path, ...]:
        folder = self.local_update_directory(is_android=is_android)
        try:
            files = [
                path
                for path in folder.iterdir()
                if path.is_file()
                and not path.name.startswith('.')
                and path.suffix.lower() in YOUTUBE_UPDATE_ALLOWED_EXTENSIONS
            ]
        except OSError:
            return ()
        return tuple(sorted(files, key=lambda path: path.name.lower()))

    def prepare_local(
        self,
        *,
        path: Path,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
    ) -> Path:
        local_path = Path(path)
        if not local_path.is_file():
            raise RuntimeError('Arquivo de update local não encontrado.')
        extension = local_path.suffix.lower()
        if extension not in YOUTUBE_UPDATE_ALLOWED_EXTENSIONS:
            allowed = ', '.join(YOUTUBE_UPDATE_ALLOWED_EXTENSIONS)
            raise RuntimeError(f'Extensão de update do YouTube não suportada. Use: {allowed}.')
        if local_path.stat().st_size <= 0:
            raise RuntimeError('Arquivo de update local está vazio.')
        if extension == '.dat':
            return self._validate_download0(local_path)

        prepared_root = self.local_update_directory(is_android=is_android) / '.prepared'
        prepared_root.mkdir(parents=True, exist_ok=True)
        destination_dir = prepared_root / self._safe_name(local_path.stem, 'youtube_update')
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / YOUTUBE_UPDATE_TARGET_NAME
        temporary = Path(str(destination) + '.part')
        self._remove_if_exists(temporary)
        member = self._pick_download0_member(local_path)
        self._emit(progress, 'Extraindo download0.dat...', None)
        try:
            with zipfile.ZipFile(local_path, 'r') as archive:
                info = archive.getinfo(member)
                if int(getattr(info, 'file_size', 0) or 0) <= 0:
                    raise RuntimeError('download0.dat dentro do ZIP está vazio.')
                with archive.open(info, 'r') as source_file, temporary.open('wb') as target:
                    shutil.copyfileobj(source_file, target, length=self.CHUNK_SIZE)
            os.replace(temporary, destination)
        except Exception:
            self._remove_if_exists(temporary)
            raise

        self._emit(progress, 'download0.dat preparado.', 100)
        return self._validate_download0(destination)

    def prepare_remote(
        self,
        *,
        source: YouTubeUpdateSource,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
    ) -> Path:
        raw_name = self._filename_from_url(source.url)
        if not raw_name:
            raise RuntimeError('Não foi possível identificar o arquivo do update.')

        lower = raw_name.lower()
        if lower.endswith('.dat'):
            filename = self._safe_name(source.label, 'youtube_update') + '.dat'
            path = self._download_cached(
                filename=filename,
                url=source.url,
                directory=self.local_update_directory(is_android=is_android),
                progress=progress,
            )
            return self._validate_download0(path)

        if lower.endswith('.zip'):
            return self._prepare_archive(
                source=source,
                raw_name=raw_name,
                is_android=is_android,
                progress=progress,
            )

        allowed = ', '.join(YOUTUBE_UPDATE_ALLOWED_EXTENSIONS)
        raise RuntimeError(f'Extensão de update do YouTube não suportada. Use: {allowed}.')

    def _prepare_archive(
        self,
        *,
        source: YouTubeUpdateSource,
        raw_name: str,
        is_android: bool,
        progress: Optional[ProgressCallback],
    ) -> Path:
        base = self.local_update_directory(is_android=is_android)
        archive_dir = base / self.ARCHIVE_FOLDER_NAME
        archive_name = self._safe_name(source.label, 'youtube_update') + Path(raw_name).suffix.lower()
        archive_path = self._download_cached(
            filename=archive_name,
            url=source.url,
            directory=archive_dir,
            progress=progress,
        )

        destination_dir = base / self._safe_name(source.label, 'youtube_update')
        destination = destination_dir / YOUTUBE_UPDATE_TARGET_NAME
        temporary = Path(str(destination) + '.part')
        self._emit(progress, 'Extraindo download0.dat...', None)

        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
            member = self._pick_download0_member(archive_path)
            with zipfile.ZipFile(archive_path, 'r') as archive:
                info = archive.getinfo(member)
                if int(getattr(info, 'file_size', 0) or 0) <= 0:
                    raise RuntimeError('download0.dat dentro do ZIP está vazio.')
                with archive.open(info, 'r') as source_file, temporary.open('wb') as target:
                    shutil.copyfileobj(source_file, target, length=self.CHUNK_SIZE)
            os.replace(temporary, destination)
        except Exception:
            self._remove_if_exists(temporary)
            raise

        self._emit(progress, 'download0.dat preparado.', 100)
        return self._validate_download0(destination)

    @staticmethod
    def _pick_download0_member(zip_path: Path) -> str:
        with zipfile.ZipFile(zip_path, 'r') as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = str(info.filename or '')
                base = PurePosixPath(name).name
                lower_name = name.lower()
                if not base or base.startswith('._') or '__macosx/' in lower_name:
                    continue
                if base.lower() == YOUTUBE_UPDATE_TARGET_NAME:
                    return name
        raise RuntimeError('ZIP do YouTube não contém download0.dat.')

    def _download_cached(
        self,
        *,
        filename: str,
        url: str,
        directory: Path,
        progress: Optional[ProgressCallback],
    ) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / filename
        metadata = Path(str(destination) + '.url')
        if self._cache_matches(destination, metadata, url):
            self._emit(progress, 'Update no cache local.', 100)
            return destination

        self._remove_if_exists(destination)
        self._remove_if_exists(metadata)
        partial = Path(str(destination) + '.part')
        self._remove_if_exists(partial)
        self._emit(progress, 'Baixando update...', 0)

        try:
            response = self._request_get(url, stream=True, timeout=self.TIMEOUT_SECONDS)
            try:
                response.raise_for_status()
                total = int(response.headers.get('Content-Length', '0') or '0')
                downloaded = 0
                last_bucket = -1
                with partial.open('wb') as handle:
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
                                self._emit(progress, 'Baixando update...', percent)
            finally:
                close = getattr(response, 'close', None)
                if callable(close):
                    close()
            os.replace(partial, destination)
        except Exception as exc:
            self._remove_if_exists(partial)
            raise RuntimeError(f'Falha ao baixar update: {exc}') from exc

        try:
            metadata.write_text(url.strip(), encoding='utf-8')
        except OSError:
            pass
        self._emit(progress, 'Download concluído.', 100)
        return destination

    @classmethod
    def _validate_download0(cls, path: Path) -> Path:
        download0_path = Path(path)
        if not download0_path.is_file():
            raise RuntimeError('download0.dat não encontrado.')
        if download0_path.suffix.lower() != '.dat':
            raise RuntimeError('Arquivo de update inválido: esperado .dat.')
        if download0_path.stat().st_size <= 0:
            raise RuntimeError('download0.dat está vazio.')
        return download0_path

    @staticmethod
    def _filename_from_url(url: str) -> str:
        parsed = urlparse(str(url or '').strip())
        return unquote(PurePosixPath(parsed.path).name).strip()

    @staticmethod
    def _safe_name(value: str, default: str) -> str:
        text = unquote(str(value or '')).strip()
        text = re.sub(r'[^A-Za-z0-9._-]+', '_', text)
        text = re.sub(r'_+', '_', text).strip('._-')
        return text or default

    @staticmethod
    def _cache_matches(destination: Path, metadata: Path, url: str) -> bool:
        try:
            return (
                destination.is_file()
                and destination.stat().st_size > 0
                and metadata.is_file()
                and metadata.read_text(encoding='utf-8').strip() == url.strip()
            )
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
    def _default_request_get(*args, **kwargs):
        if requests is None:
            raise RuntimeError('Dependência requests indisponível para baixar update.')
        return requests.get(*args, **kwargs)

    @staticmethod
    def _emit(callback: Optional[ProgressCallback], message: str, percent: Optional[int]) -> None:
        if callback is not None:
            callback(YouTubeUpdateProgress(message=message, percent=percent))
