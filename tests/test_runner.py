from __future__ import annotations

import shutil

import pytest
from pytest_subprocess import FakeProcess

from ai_container import runner
from ai_container.models import Engine


def test_build_argv_orders_engine_flags_correctly() -> None:
    argv = runner.build_argv(
        engine=Engine.PODMAN,
        engine_debug_args=["--log-level=debug"],
        entrypoint="/bin/echo",
        args=["--rm", "--name", "ai-abc"],
        image="localhost/ai",
        tool_args=["hi"],
    )
    assert argv == [
        "podman",
        "--log-level=debug",
        "run",
        "--init",
        "--entrypoint",
        "/bin/echo",
        "--rm",
        "--name",
        "ai-abc",
        "localhost/ai",
        "hi",
    ]


def test_run_invokes_subprocess_and_restores_terminal(
    fp: FakeProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/bin/stty")
    fp.register(["podman", "run", "--rm", "image"], returncode=3)
    fp.register(["stty", "sane"])
    exit_code = runner.run(["podman", "run", "--rm", "image"])
    assert exit_code == 3
    assert fp.call_count(["stty", "sane"]) == 1


def test_run_skips_stty_when_unavailable(fp: FakeProcess, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    fp.register(["podman", "run", "--rm", "image"], returncode=0)
    exit_code = runner.run(["podman", "run", "--rm", "image"])
    assert exit_code == 0


def test_spawn_relay_chmod_fix_runs_in_background(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Engine, str]] = []

    def fake_fix(engine: Engine, name: str) -> None:
        calls.append((engine, name))

    monkeypatch.setattr("ai_container.ssh_agent.fix_relay_permissions", fake_fix)
    thread = runner.spawn_relay_chmod_fix(Engine.CONTAINER, "ai-xyz")
    thread.join(timeout=2)
    assert calls == [(Engine.CONTAINER, "ai-xyz")]
