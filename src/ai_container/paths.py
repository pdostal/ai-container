"""Host <-> container path remapping and workdir validation."""

from __future__ import annotations

from pathlib import Path


class HomeDirectoryWorkdirError(Exception):
    """Raised when the current directory is the whole host $HOME."""


def map_to_container_path(path: Path, *, host_home: Path, container_home: Path) -> Path:
    """Remap a host path under ``host_home`` onto the equivalent ``container_home`` path.

    Paths outside ``host_home`` are returned unchanged, matching the bash
    script's ``"$host_home"/*`` case pattern (e.g. host
    ``~/external/ai-container`` -> container ``/home/coder/external/ai-container``).
    """
    try:
        relative = path.relative_to(host_home)
    except ValueError:
        return path
    if str(relative) == ".":
        return container_home
    return container_home / relative


def resolve_target_workdir(cwd: Path, *, host_home: Path, container_home: Path) -> Path:
    """Validate ``cwd`` and compute its in-container mount target.

    Raises ``HomeDirectoryWorkdirError`` if ``cwd`` is the entire host home
    directory (refused, same as the bash script).
    """
    if cwd == host_home:
        raise HomeDirectoryWorkdirError(str(host_home))
    return map_to_container_path(cwd, host_home=host_home, container_home=container_home)
