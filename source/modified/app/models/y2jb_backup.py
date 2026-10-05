from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Y2JBBackupVariant:
    key: str
    firmware_label: str
    package_label: str
    url: str
    filename: str
    release_version: str = ''


@dataclass(frozen=True)
class Y2JBBackupProgress:
    message: str
    percent: Optional[int] = None


@dataclass(frozen=True)
class Y2JBBackupResult:
    variant: Y2JBBackupVariant
    usb_path: str
    copied_files: int
    copied_bytes: int
