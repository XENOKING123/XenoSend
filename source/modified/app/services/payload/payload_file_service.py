import os
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable, Optional
from urllib.parse import unquote, urlparse

import requests

from app.models.payload import (
    PAYLOAD_ALLOWED_EXTENSIONS,
    PAYLOAD_ARCHIVE_EXTENSIONS,
    PayloadProgress,
    PayloadSource,
)
from app.services.download.download_directory_provider import DownloadDirectoryProvider


ProgressCallback = Callable[[PayloadProgress], None]


class PayloadFileService:
    CHUNK_SIZE = 1024 * 1024
    TIMEOUT_SECONDS = 30
    LOCAL_FOLDER_NAME = 'ps5_payloads'
    ARCHIVE_FOLDER_NAME = 'payload_archives'

    def __init__(
        self,
        directory_provider: DownloadDirectoryProvider,
        request_get=None,
        local_directory_provider=None,
    ):
        self._directory_provider = directory_provider
        self._local_directory_provider = local_directory_provider or directory_provider
        self._request_get = request_get or requests.get

    def local_payload_directory(self, *, is_android: bool) -> Path:
        folder = self._local_directory_provider.get(is_android=is_android) / self.LOCAL_FOLDER_NAME
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def list_local_payloads(self, *, is_android: bool) -> tuple[Path, ...]:
        folder = self.local_payload_directory(is_android=is_android)
        try:
            files = [
                path
                for path in folder.iterdir()
                if path.is_file()
                and not path.name.startswith('.')
                and path.suffix.lower() in PAYLOAD_ALLOWED_EXTENSIONS
            ]
        except OSError:
            return ()
        return tuple(sorted(files, key=lambda path: path.name.lower()))

    def prepare_remote(
        self,
        *,
        source: PayloadSource,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
    ) -> Path:
        raw_name = self._filename_from_url(source.url)
        if not raw_name:
            raise RuntimeError('Não foi possível identificar o arquivo do payload.')

        lower = raw_name.lower()
        if lower.endswith(PAYLOAD_ALLOWED_EXTENSIONS):
            extension = Path(raw_name).suffix.lower()
            filename = self._safe_name(source.label, 'payload') + extension
            return self._download_cached(
                filename=filename,
                url=source.url,
                directory=self._directory_provider.get(is_android=is_android),
                progress=progress,
            )

        if lower.endswith(PAYLOAD_ARCHIVE_EXTENSIONS):
            return self._prepare_archive(
                source=source,
                raw_name=raw_name,
                is_android=is_android,
                progress=progress,
            )

        raise RuntimeError('Extensão de payload não suportada.')

    def validate_local(self, path: Path) -> Path:
        payload_path = Path(path)
        if not payload_path.is_file():
            raise RuntimeError('Arquivo de payload local não encontrado.')
        if payload_path.suffix.lower() not in PAYLOAD_ALLOWED_EXTENSIONS:
            raise RuntimeError('Extensão de payload não suportada.')
        if payload_path.stat().st_size <= 0:
            raise RuntimeError('O arquivo de payload está vazio.')
        return payload_path

    def _prepare_archive(
        self,
        *,
        source: PayloadSource,
        raw_name: str,
        is_android: bool,
        progress: Optional[ProgressCallback],
    ) -> Path:
        base = self._directory_provider.get(is_android=is_android)
        archive_dir = base / self.ARCHIVE_FOLDER_NAME
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_name = self._safe_name(source.label, 'payload') + Path(raw_name).suffix.lower()
        archive_path = self._download_cached(
            filename=archive_name,
            url=source.url,
            directory=archive_dir,
            progress=progress,
        )

        member = self._pick_payload_member(
            archive_path,
            preferred_name=self._safe_name(source.label, 'payload') + '.elf',
        )
        destination = base / (self._safe_name(source.label, 'payload') + '.elf')
        temporary = Path(str(destination) + '.part')
        self._emit(progress, 'Extraindo payload...', None)

        try:
            with zipfile.ZipFile(archive_path, 'r') as archive:
                info = archive.getinfo(member)
                if int(getattr(info, 'file_size', 0) or 0) <= 0:
                    raise RuntimeError('O payload dentro do ZIP está vazio.')
                with archive.open(info, 'r') as source_file, temporary.open('wb') as target:
                    shutil.copyfileobj(source_file, target, length=self.CHUNK_SIZE)
            os.replace(temporary, destination)
        except Exception:
            self._remove_if_exists(temporary)
            raise

        if not destination.is_file() or destination.stat().st_size <= 0:
            raise RuntimeError('O payload extraído ficou vazio.')
        self._emit(progress, 'Payload preparado.', 100)
        return destination

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
            self._emit(progress, 'Payload no cache local.', 100)
            return destination

        self._remove_if_exists(destination)
        self._remove_if_exists(metadata)
        partial = Path(str(destination) + '.part')
        self._remove_if_exists(partial)
        self._emit(progress, 'Baixando payload...', 0)

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
                                self._emit(progress, 'Baixando payload...', percent)
            finally:
                close = getattr(response, 'close', None)
                if callable(close):
                    close()
            os.replace(partial, destination)
        except Exception as exc:
            self._remove_if_exists(partial)
            raise RuntimeError(f'Falha ao baixar payload: {exc}') from exc

        try:
            metadata.write_text(url.strip(), encoding='utf-8')
        except OSError:
            pass
        self._emit(progress, 'Download concluído.', 100)
        return destination

    @staticmethod
    def _pick_payload_member(zip_path: Path, preferred_name: str = '') -> str:
        preferred = Path(preferred_name).name.lower()
        candidates = []
        with zipfile.ZipFile(zip_path, 'r') as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = str(info.filename or '')
                base = PurePosixPath(name).name
                lower = base.lower()
                if not base or lower.startswith('._') or '__macosx/' in name.lower():
                    continue
                if not lower.endswith(PAYLOAD_ALLOWED_EXTENSIONS):
                    continue
                candidates.append((name, lower, int(info.file_size or 0)))

        if not candidates:
            raise RuntimeError('ZIP sem payload .elf/.bin/.js/.jar válido.')
        if preferred:
            for name, lower, _size in candidates:
                if lower == preferred:
                    return name
        for name, lower, _size in candidates:
            if 'shadowmount' in lower:
                return name
        candidates.sort(key=lambda item: item[2], reverse=True)
        return candidates[0][0]

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
    def _emit(callback: Optional[ProgressCallback], message: str, percent: Optional[int]) -> None:
        if callback is not None:
            callback(PayloadProgress(message=message, percent=percent))
