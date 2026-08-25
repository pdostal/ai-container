"""Git worktree detection."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _rev_parse(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout.strip()


def detect_worktree_parent(cwd: Path) -> Path | None:
    """Return the parent (main) checkout's directory if ``cwd`` is a git worktree.

    Returns ``None`` if ``cwd`` isn't inside a git repository, or isn't a
    linked worktree (i.e. the common git dir and the git dir are the same).
    """
    common_dir = _rev_parse(cwd, "--path-format=absolute", "--git-common-dir")
    git_dir = _rev_parse(cwd, "--path-format=absolute", "--git-dir")
    if common_dir is None or git_dir is None:
        return None
    if common_dir == git_dir:
        return None
    return Path(common_dir).parent
