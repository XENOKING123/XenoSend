from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


HOST_LABEL = "WebKit + ReLapse + Instalador"
INSTALLER_FILE_NAME = "Host-PSM-ReLapse-v1.3.0-instala-host-en.elf"
INSTALLER_SHA256 = "a4e6b24351c111e1819f1eddcd4f6f76ffd514b3954584e111d6f84c0318ef63"


class HostAssetError(RuntimeError):
    pass


def asset_root() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "host_psm"


def bundled_host_root() -> Path:
    return asset_root() / "host_local"


def bundled_pem_path() -> Path:
    return asset_root() / "localhost.pem"


def bundled_blocklist_path() -> Path:
    return asset_root() / "blocklist.txt"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_bundled_assets() -> None:
    root = bundled_host_root()
    required = (
        root / "index.html",
        root / "host-config.js",
        root / "host-runtime.js",
        root / "offsets" / "offsets.json",
        root / "relapse" / "host-psm-adapter.js",
        root / "relapse" / "firmwares.json",
        root / "relapse" / "src" / "main.js",
        root / "relapse" / "src" / "relapse_exploit.js",
        root / "payloads" / "elfldr-ps5-1360.elf",
        root / "payloads" / "kexp_2026_05_25.bin",
        root / "payloads" / INSTALLER_FILE_NAME,
        bundled_pem_path(),
        bundled_blocklist_path(),
    )
    for path in required:
        if not path.is_file():
            raise HostAssetError(f"Asset interno ausente: {path.name}")
        if path.name not in {"blocklist.txt"} and path.stat().st_size <= 0:
            raise HostAssetError(f"Asset interno vazio: {path.name}")

    installer = root / "payloads" / INSTALLER_FILE_NAME
    if _sha256(installer) != INSTALLER_SHA256:
        raise HostAssetError("O ELF instalador interno divergiu do anexo validado.")


def _copy_file_contents(source: Path, destination: Path) -> None:
    """Copia somente os bytes, sem depender de metadados do filesystem de origem."""
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    temporary.unlink(missing_ok=True)
    try:
        with source.open("rb") as source_handle, temporary.open("wb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_tree_contents(source_root: Path, destination_root: Path) -> None:
    """Replica a árvore por conteúdo; adequado ao armazenamento privado do Android."""
    source_root = Path(source_root)
    destination_root = Path(destination_root)
    for current_root, directories, filenames in os.walk(source_root):
        current = Path(current_root)
        relative = current.relative_to(source_root)
        current_destination = destination_root / relative
        current_destination.mkdir(parents=True, exist_ok=True)
        for directory in directories:
            (current_destination / directory).mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            _copy_file_contents(current / filename, current_destination / filename)


def prepare_runtime(
    data_dir: Path,
    *,
    copy_contents_only: bool = False,
) -> tuple[Path, Path, Path]:
    """Cria uma cópia gravável e limpa do host para a sessão atual."""
    validate_bundled_assets()
    base = Path(data_dir).resolve() / "host_psm" / "runtime"
    host_dst = base / "host_local"
    cert_dst = base / "localhost.pem"
    blocklist_dst = base / "blocklist.txt"

    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)

    if copy_contents_only:
        _copy_tree_contents(bundled_host_root(), host_dst)
        _copy_file_contents(bundled_pem_path(), cert_dst)
        _copy_file_contents(bundled_blocklist_path(), blocklist_dst)
    else:
        shutil.copytree(bundled_host_root(), host_dst)
        shutil.copy2(bundled_pem_path(), cert_dst)
        shutil.copy2(bundled_blocklist_path(), blocklist_dst)

    return host_dst, cert_dst, blocklist_dst
