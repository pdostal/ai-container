"""Tests for the `pi-print` wrapper (pi/print.sh).

It runs pi with `--no-extensions` plus a curated list, because pi imports every
discovered extension sequentially before the first token and print mode can use
only a fraction of them. The wrapper is shell, so these run it against a stub
`pi` that echoes its argv.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "pi" / "print.sh"


def _fake_pi(tmp_path: Path) -> Path:
    """A `pi` that prints one argument per line, revealing the wrapper's argv."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / "pi"
    exe.write_text('#!/bin/sh\nfor arg in "$@"; do printf "%s\\n" "$arg"; done\n')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bin_dir: Path,
    extensions: Path,
    args: list[str],
) -> list[str]:
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PI_PRINT_EXTENSIONS", str(extensions))
    result = subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.splitlines()


def test_trims_to_listed_extensions_and_adds_print_mode(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = tmp_path / "installed.js"
    installed.write_text("")
    missing = tmp_path / "missing.js"
    (isolated_home / "mine.ts").write_text("")
    extensions = tmp_path / "list"
    extensions.write_text(
        f"# a comment\n\nbuiltin:mcp\n{installed}\n{missing}\n~/mine.ts  # trailing\n"
    )

    argv = _run(
        monkeypatch, bin_dir=_fake_pi(tmp_path), extensions=extensions, args=["hello world"]
    )

    assert argv == [
        "--no-extensions",
        "-e",
        "builtin:mcp",
        "-e",
        str(installed),
        "-e",
        f"{isolated_home}/mine.ts",
        "-p",
        "hello world",
    ]


def test_explicit_extension_flags_disable_the_trimming(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extensions = tmp_path / "list"
    extensions.write_text("builtin:mcp\n")

    for flag in ("-e", "--extension", "--no-extensions"):
        argv = _run(
            monkeypatch,
            bin_dir=_fake_pi(tmp_path),
            extensions=extensions,
            args=[flag, "/some/ext.js", "-p", "hi"],
        )
        assert argv == [flag, "/some/ext.js", "-p", "hi"]


def test_an_existing_mode_flag_is_not_duplicated(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = _run(
        monkeypatch,
        bin_dir=_fake_pi(tmp_path),
        extensions=tmp_path / "absent-list",
        args=["--json", "hi"],
    )

    assert argv == ["--no-extensions", "--json", "hi"]


def test_an_empty_list_runs_pi_without_extensions(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extensions = tmp_path / "list"
    extensions.write_text("# nothing enabled\n")

    argv = _run(monkeypatch, bin_dir=_fake_pi(tmp_path), extensions=extensions, args=["hi"])

    assert argv == ["--no-extensions", "-p", "hi"]
