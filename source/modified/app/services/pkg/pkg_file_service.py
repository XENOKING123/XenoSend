import os
import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse
from typing import Callable, Optional

from app.models.pkg import PKG_ALLOWED_EXTENSIONS, PkgSource
from app.services.download.http_download_service import HttpDownloadService


class PkgFileService:
    def __init__(self, directory_provider, downloader: HttpDownloadService):
        self._directory_provider = directory_provider
        self._downloader = downloader

    def local_pkg_directory(self, *, is_android: bool) -> Path:
        path = Path(self._directory_provider.get(is_android=is_android))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def list_local_pkgs(self, *, is_android: bool) -> tuple[Path, ...]:
        folder = self.local_pkg_directory(is_android=is_android)
        try:
            files = [
                path
                for path in folder.iterdir()
                if path.is_file()
                and path.suffix.lower() in PKG_ALLOWED_EXTENSIONS
                and not path.name.startswith(".")
            ]
        except OSError:
            return ()
        return tuple(sorted(files, key=lambda path: path.name.lower()))

    def download_remote(self, *, source: PkgSource, is_android: bool, progress: Optional[Callable] = None) -> Path:
        filename = self.build_download_filename(source)
        return self._downloader.download(
            filename=filename,
            url=source.url,
            is_android=is_android,
            progress=progress,
            display_name="PKG",
        )

    @classmethod
    def build_download_filename(cls, source: PkgSource) -> str:
        parsed = urlparse(source.url.strip())
        raw_name = PurePosixPath(unquote(parsed.path)).name
        if raw_name.lower().endswith(PKG_ALLOWED_EXTENSIONS):
            return raw_name

        label_base = re.sub(
            r"\s+(?:v?\d+(?:[._-][A-Za-z0-9]+)*)$",
            "",
            source.label.strip(),
            flags=re.IGNORECASE,
        ).strip()
        parts = [cls._safe_part(label_base or source.label, "package")]
        path_parts = [unquote(part).strip() for part in parsed.path.split("/") if part.strip()]
        if "pkg-zone.com" in (parsed.netloc or "").lower() and len(path_parts) >= 2:
            pkg_id = cls._safe_part(path_parts[-2])
            version = cls._safe_part(path_parts[-1])
            if pkg_id:
                parts.append(pkg_id)
            if version:
                parts.append(version)
        final_name = "__".join(part for part in parts if part).strip("_") or "package"
        return final_name + ".pkg"

    @staticmethod
    def upload_name(display_name: str, path: Path) -> str:
        raw_name = os.path.basename(str(display_name or "").strip()) or path.name
        stem = Path(raw_name).stem
        return PkgFileService._safe_part(stem or raw_name, "package") + ".pkg"

    @staticmethod
    def _safe_part(value: str, default: str = "") -> str:
        text = unquote(str(value or "")).strip()
        text = re.sub(r"\.pkg$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("._-")
        return text or default
