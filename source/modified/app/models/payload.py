from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional


PAYLOAD_ALLOWED_EXTENSIONS = (".elf", ".bin", ".js", ".jar")
PAYLOAD_ARCHIVE_EXTENSIONS = (".zip",)


@dataclass(frozen=True)
class PayloadSource:
    key: str
    name: str
    version: str
    url: str
    name_override: str = ""

    @property
    def display_name(self) -> str:
        return self.name_override.strip() or self.name.strip()

    @property
    def label(self) -> str:
        parts = [self.display_name, self.version.strip()]
        return " ".join(part for part in parts if part)

    def with_resolution(self, *, name: str, version: str, url: str) -> "PayloadSource":
        return replace(
            self,
            name=name.strip(),
            version=version.strip(),
            url=url.strip(),
        )


@dataclass(frozen=True)
class PayloadMenuEntry:
    key: str
    label: str
    kind: str
    source_key: str = ""
    local_path: Optional[Path] = None


@dataclass(frozen=True)
class PayloadProgress:
    message: str
    percent: Optional[int] = None


@dataclass(frozen=True)
class PayloadExecutionResult:
    label: str
    local_path: Path
    bytes_sent: int
