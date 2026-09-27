"""Workspace resolution: named groups of directories to auto-mount together."""

from __future__ import annotations

from pathlib import Path

from .config import Workspace


class WorkspaceNotFoundError(Exception):
    """Raised when an explicit --workspace name isn't defined in the config file."""


def detect(cwd: Path, workspaces: tuple[Workspace, ...]) -> Workspace | None:
    """Return the first workspace whose dirs contain (or equal) ``cwd``, if any."""
    resolved_cwd = cwd.resolve()
    for workspace in workspaces:
        for d in workspace.dirs:
            if resolved_cwd.is_relative_to(d.resolve()):
                return workspace
    return None


def resolve(
    *,
    explicit_name: str | None,
    auto: bool,
    cwd: Path,
    workspaces: tuple[Workspace, ...],
) -> Workspace | None:
    """Resolve the active workspace: explicit name wins, else auto-detect if enabled."""
    if explicit_name is not None:
        for workspace in workspaces:
            if workspace.name == explicit_name:
                return workspace
        raise WorkspaceNotFoundError(f"Unknown workspace: {explicit_name!r}")
    if auto:
        return detect(cwd, workspaces)
    return None
