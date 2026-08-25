from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from ai_container.console import Reporter


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point $HOME at an empty temp directory, so Path.home() and every
    credential-mount existence check operate on a clean slate.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project directory (outside $HOME) to run the CLI from."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


@pytest.fixture
def fake_engine_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put stub `podman`/`container` executables on $PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("podman", "container"):
        exe = bin_dir / name
        exe.write_text("#!/bin/sh\nexit 0\n")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return bin_dir


@pytest.fixture
def reporter() -> Reporter:
    return Reporter(debug=True)
