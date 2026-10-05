import os
import shutil
from pathlib import Path
from typing import Callable, Optional, Tuple

from app.models.y2jb_backup import Y2JBBackupProgress


ProgressCallback = Callable[[Y2JBBackupProgress], None]


class TreeCopyService:
    CHUNK_SIZE = 1024 * 1024

    def copy_contents(
        self,
        source_root: Path,
        destination_root: Path,
        progress: Optional[ProgressCallback] = None,
    ) -> Tuple[int, int]:
        source_root = Path(source_root)
        destination_root = Path(destination_root)

        files = []
        total_bytes = 0
        for root, _dirs, filenames in os.walk(source_root):
            root_path = Path(root)
            for filename in filenames:
                source = root_path / filename
                relative = source.relative_to(source_root)
                files.append((source, relative))
                try:
                    total_bytes += max(0, source.stat().st_size)
                except OSError:
                    continue

        if not files:
            raise RuntimeError("Nenhum arquivo foi extraído do backup.")

        copied_files = 0
        copied_bytes = 0
        last_percent = -1
        self._emit(progress, "Copiando para o USB...", 0)

        for source, relative in files:
            destination = destination_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)

            with source.open("rb") as source_handle, destination.open("wb") as destination_handle:
                while True:
                    chunk = source_handle.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    destination_handle.write(chunk)
                    copied_bytes += len(chunk)
                    percent = self._percent(copied_bytes, total_bytes, copied_files, len(files))
                    if percent != last_percent:
                        last_percent = percent
                        self._emit(progress, "Copiando para o USB...", percent)

            try:
                shutil.copystat(source, destination)
            except OSError:
                pass

            copied_files += 1
            percent = self._percent(copied_bytes, total_bytes, copied_files, len(files))
            if percent != last_percent:
                last_percent = percent
                self._emit(progress, "Copiando para o USB...", percent)

        self._emit(progress, "Cópia concluída.", 100)
        return copied_files, copied_bytes

    @staticmethod
    def _percent(copied_bytes: int, total_bytes: int, copied_files: int, total_files: int) -> int:
        if total_bytes > 0:
            percent = int(copied_bytes * 100 // total_bytes)
        else:
            percent = int(copied_files * 100 // total_files)
        return max(0, min(100, percent))

    @staticmethod
    def _emit(callback: Optional[ProgressCallback], message: str, percent: int) -> None:
        if callback is not None:
            callback(Y2JBBackupProgress(message=message, percent=percent))
