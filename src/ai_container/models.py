"""Shared dataclasses/enums used across the ai-container package."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path


class Engine(StrEnum):
    """Supported container engines.

    Docker isn't implemented yet, but the codebase (see ``engine.py``) is
    structured so adding it later means adding one more branch, not a
    rewrite.
    """

    PODMAN = "podman"
    CONTAINER = "container"


class MountKind(Enum):
    DIRECTORY = "directory"
    FILE = "file"


class MountAccess(Enum):
    READ_WRITE = "rw"
    READ_ONLY = "ro"


@dataclass(frozen=True, slots=True)
class MountSpec:
    """A single conditional host -> container mount.

    Mirrors one of the repeated "if directory/file exists, mount it"
    blocks from the original bash script.
    """

    label: str
    host: Path
    container: Path
    kind: MountKind
    access: MountAccess

    def exists(self) -> bool:
        if self.kind is MountKind.DIRECTORY:
            return self.host.is_dir()
        return self.host.is_file()
