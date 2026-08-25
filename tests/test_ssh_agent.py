from __future__ import annotations

import socket
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from pytest_subprocess import FakeProcess

from ai_container import ssh_agent
from ai_container.console import Reporter
from ai_container.models import Engine

CONTAINER_HOME = Path("/home/coder")


@pytest.fixture
def real_socket(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "agent.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    yield path
    sock.close()


def test_no_socket_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    result = ssh_agent.configure(
        engine=Engine.PODMAN,
        container_home=CONTAINER_HOME,
        selinux_enabled=False,
        reporter=Reporter(),
    )
    assert result.args == []
    assert result.env == {}
    assert result.needs_relay_chmod is False


def test_podman_mounts_socket_and_sets_env(
    monkeypatch: pytest.MonkeyPatch, real_socket: Path
) -> None:
    monkeypatch.setenv("SSH_AUTH_SOCK", str(real_socket))
    result = ssh_agent.configure(
        engine=Engine.PODMAN,
        container_home=CONTAINER_HOME,
        selinux_enabled=False,
        reporter=Reporter(),
    )
    target = CONTAINER_HOME / ".ssh/agent/ssh-agent.sock"
    assert result.args == [f"--mount=type=bind,source={real_socket},target={target}"]
    assert result.env == {"SSH_AUTH_SOCK": str(target)}
    assert result.needs_relay_chmod is False


def test_podman_mount_gets_selinux_suffix(
    monkeypatch: pytest.MonkeyPatch, real_socket: Path
) -> None:
    monkeypatch.setenv("SSH_AUTH_SOCK", str(real_socket))
    result = ssh_agent.configure(
        engine=Engine.PODMAN,
        container_home=CONTAINER_HOME,
        selinux_enabled=True,
        reporter=Reporter(),
    )
    assert result.args[0].endswith(",z")


def test_container_engine_uses_ssh_flag(monkeypatch: pytest.MonkeyPatch, real_socket: Path) -> None:
    monkeypatch.setenv("SSH_AUTH_SOCK", str(real_socket))
    result = ssh_agent.configure(
        engine=Engine.CONTAINER,
        container_home=CONTAINER_HOME,
        selinux_enabled=False,
        reporter=Reporter(),
    )
    assert result.args == ["--ssh"]
    assert result.env == {}
    assert result.needs_relay_chmod is True


def test_container_engine_without_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    result = ssh_agent.configure(
        engine=Engine.CONTAINER,
        container_home=CONTAINER_HOME,
        selinux_enabled=False,
        reporter=Reporter(),
    )
    assert result.args == []
    assert result.needs_relay_chmod is False


def test_fix_relay_permissions_succeeds_first_try(fp: FakeProcess) -> None:
    fp.register(["container", "exec", "-u", "root", "ai-abc", "sh", "-c", fp.any()], returncode=0)
    ssh_agent.fix_relay_permissions(Engine.CONTAINER, "ai-abc")
    assert fp.call_count(["container", "exec", "-u", "root", "ai-abc", "sh", "-c", fp.any()]) == 1


def test_fix_relay_permissions_retries_then_gives_up(
    fp: FakeProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    fp.register(["container", "exec", "-u", "root", "ai-abc", "sh", "-c", fp.any()], returncode=1)
    fp.register(["container", "exec", "-u", "root", "ai-abc", "sh", "-c", fp.any()], returncode=1)
    ssh_agent.fix_relay_permissions(Engine.CONTAINER, "ai-abc", attempts=2)
