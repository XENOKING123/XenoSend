import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

from app.models.y2jb_backup import Y2JBBackupProgress, Y2JBBackupResult, Y2JBBackupVariant
from app.services.archive.zip_archive_service import ZipArchiveService
from app.services.download.http_download_service import HttpDownloadService
from app.services.storage.removable_storage_service import RemovableStorageService
from app.services.storage.tree_copy_service import TreeCopyService


ProgressCallback = Callable[[Y2JBBackupProgress], None]


class RemovableUsbNotFoundError(RuntimeError):
    pass


class Y2JBBackupService:
    def __init__(
        self,
        *,
        work_root: Path,
        downloader: HttpDownloadService,
        archive_service: ZipArchiveService,
        removable_storage: RemovableStorageService,
        copy_service: TreeCopyService,
    ):
        self._work_root = Path(work_root)
        self._downloader = downloader
        self._archive_service = archive_service
        self._removable_storage = removable_storage
        self._copy_service = copy_service

    def execute(
        self,
        *,
        variant: Y2JBBackupVariant,
        is_android: bool,
        progress: Optional[ProgressCallback] = None,
    ) -> Y2JBBackupResult:
        archive_path = self._downloader.download(
            filename=variant.filename,
            url=variant.url,
            is_android=is_android,
            progress=progress,
        )

        self._work_root.mkdir(parents=True, exist_ok=True)
        extract_dir = Path(tempfile.mkdtemp(prefix="y2jb_backup_", dir=self._work_root))
        try:
            self._emit(progress, "Extraindo backup...", None)
            self._archive_service.extract(archive_path, extract_dir)

            self._emit(progress, "Procurando USB removível...", None)
            usb_path = self._removable_storage.find_first_writable(is_android=is_android)
            if usb_path is None:
                raise RemovableUsbNotFoundError(
                    "Nenhum USB removível acessível foi encontrado."
                )

            copied_files, copied_bytes = self._copy_service.copy_contents(
                extract_dir,
                usb_path,
                progress=progress,
            )

            return Y2JBBackupResult(
                variant=variant,
                usb_path=str(usb_path),
                copied_files=copied_files,
                copied_bytes=copied_bytes,
            )
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    @staticmethod
    def _emit(
        callback: Optional[ProgressCallback], message: str, percent
    ) -> None:
        if callback is not None:
            callback(Y2JBBackupProgress(message=message, percent=percent))
