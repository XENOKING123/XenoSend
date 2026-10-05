from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

YOUTUBE_UPDATE_ALLOWED_EXTENSIONS = (".zip", ".dat")
YOUTUBE_UPDATE_TARGET_DIR = "/user/download/PPSA01650"
YOUTUBE_UPDATE_TARGET_NAME = "download0.dat"


@dataclass(frozen=True)
class YouTubeUpdateSource:
    key: str
    name: str
    version: str
    url: str
    name_override: str = ""
    remote_dir: str = YOUTUBE_UPDATE_TARGET_DIR
    remote_name: str = YOUTUBE_UPDATE_TARGET_NAME

    @property
    def display_name(self) -> str:
        return self.name_override.strip() or self.name.strip()

    @property
    def label(self) -> str:
        parts = [self.display_name, self.version.strip()]
        return " ".join(part for part in parts if part)

    @property
    def remote_path(self) -> str:
        return f"{self.remote_dir.rstrip('/')}/{self.remote_name}"

    def with_resolution(self, *, name: str, version: str, url: str) -> "YouTubeUpdateSource":
        return replace(
            self,
            name=name.strip(),
            version=version.strip(),
            url=url.strip(),
        )


@dataclass(frozen=True)
class YouTubeUpdateMenuEntry:
    key: str
    label: str
    kind: str
    source_key: str = ""
    local_path: Optional[Path] = None


@dataclass(frozen=True)
class YouTubeUpdateProgress:
    message: str
    percent: Optional[int] = None


@dataclass(frozen=True)
class YouTubeUpdateResult:
    label: str
    local_path: Path
    remote_path: str
    bytes_uploaded: int
