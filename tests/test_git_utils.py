from __future__ import annotations

import subprocess
from pathlib import Path

from ai_container.git_utils import detect_worktree_parent


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": str(cwd),
        },
    )


def test_non_git_directory_returns_none(tmp_path: Path) -> None:
    assert detect_worktree_parent(tmp_path) is None


def test_plain_repo_is_not_a_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "file.txt").write_text("hi\n")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-q", "-m", "init")
    assert detect_worktree_parent(repo) is None


def test_linked_worktree_resolves_to_main_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "file.txt").write_text("hi\n")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-q", "-m", "init")

    worktree = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "feature", str(worktree))

    assert detect_worktree_parent(worktree) == repo.resolve()


def test_missing_git_binary(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PATH", str(tmp_path))  # no `git` anywhere on PATH
    assert detect_worktree_parent(tmp_path) is None
