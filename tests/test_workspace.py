from __future__ import annotations

from pathlib import Path

import pytest

from ai_container import workspace
from ai_container.config import Workspace

FRONTEND = Workspace(name="frontend", dirs=(Path("/repos/app"), Path("/repos/shared")))
BACKEND = Workspace(name="backend", dirs=(Path("/repos/api"),))
WORKSPACES = (FRONTEND, BACKEND)


def test_detect_matches_exact_dir(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    workspaces = (Workspace(name="frontend", dirs=(app,)),)
    assert workspace.detect(app, workspaces) == workspaces[0]


def test_detect_matches_subdirectory(tmp_path: Path) -> None:
    app = tmp_path / "app"
    (app / "src").mkdir(parents=True)
    workspaces = (Workspace(name="frontend", dirs=(app,)),)
    assert workspace.detect(app / "src", workspaces) == workspaces[0]


def test_detect_returns_none_when_no_match(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    workspaces = (Workspace(name="frontend", dirs=(tmp_path / "app",)),)
    assert workspace.detect(other, workspaces) is None


def test_resolve_explicit_name_found(tmp_path: Path) -> None:
    result = workspace.resolve(
        explicit_name="backend", auto=False, cwd=tmp_path, workspaces=WORKSPACES
    )
    assert result == BACKEND


def test_resolve_explicit_name_not_found_raises(tmp_path: Path) -> None:
    with pytest.raises(workspace.WorkspaceNotFoundError):
        workspace.resolve(
            explicit_name="nonexistent", auto=False, cwd=tmp_path, workspaces=WORKSPACES
        )


def test_resolve_auto_off_returns_none_without_explicit(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    workspaces = (Workspace(name="frontend", dirs=(app,)),)
    result = workspace.resolve(explicit_name=None, auto=False, cwd=app, workspaces=workspaces)
    assert result is None


def test_resolve_auto_on_detects_from_cwd(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    workspaces = (Workspace(name="frontend", dirs=(app,)),)
    result = workspace.resolve(explicit_name=None, auto=True, cwd=app, workspaces=workspaces)
    assert result == workspaces[0]
