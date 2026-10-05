from pathlib import Path
import zipfile


class UnsafeArchiveError(RuntimeError):
    pass


class ZipArchiveService:
    def extract(self, archive_path: Path, destination: Path) -> None:
        archive_path = Path(archive_path)
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        root = destination.resolve()

        with zipfile.ZipFile(archive_path, "r") as archive:
            for member in archive.infolist():
                target = (destination / member.filename).resolve()
                try:
                    target.relative_to(root)
                except ValueError as exc:
                    raise UnsafeArchiveError(
                        f"Entrada inválida no ZIP: {member.filename}"
                    ) from exc
            archive.extractall(destination)
