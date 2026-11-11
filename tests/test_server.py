from __future__ import annotations

import socket
from pathlib import Path

import pytest
from pytest_subprocess import FakeProcess

from ai_container import server


def test_configure_generates_password_when_unset(fp: FakeProcess) -> None:
    fp.register(["hostname", "-I"], stdout="10.0.0.5 fe80::1\n")
    result = server.configure(
        port=4996,
        username="opencode",
        password=None,
        tool_args=["--resume"],
        host_platform="Linux",
    )
    assert len(result.password) == 20
    assert "OPENCODE_PASSWORD=" + result.password in result.args
    assert result.tool_args == ["serve", "--hostname", "0.0.0.0", "--port", "4996", "--resume"]
    assert result.username == "opencode"
    assert result.urls == ["10.0.0.5:4996"]


def test_configure_keeps_explicit_password(fp: FakeProcess) -> None:
    fp.register(["hostname", "-I"], stdout="10.0.0.5\n")
    result = server.configure(
        port=5000,
        username="opencode",
        password="hunter2",
        tool_args=[],
        host_platform="Linux",
    )
    assert result.password == "hunter2"
    assert "OPENCODE_PASSWORD=hunter2" in result.args
    assert "-p" in result.args and "0.0.0.0:5000:4996" in result.args


def test_host_ips_linux_uses_hostname_dash_i(fp: FakeProcess) -> None:
    fp.register(["hostname", "-I"], stdout="192.168.1.7 fe80::1 127.0.0.1\n")
    assert server.host_ips("Linux") == ["192.168.1.7"]


def test_host_ips_linux_falls_back_to_localhost_when_only_loopback(fp: FakeProcess) -> None:
    fp.register(["hostname", "-I"], stdout="127.0.0.1\n")
    assert server.host_ips("Linux") == ["localhost"]


def test_host_ips_darwin_collects_every_interface(fp: FakeProcess) -> None:
    fp.register(["ipconfig", "getifaddr", "en0"], stdout="192.168.1.9\n")
    for interface in ("en1", "en2", "en3", "en4", "en5"):
        fp.register(["ipconfig", "getifaddr", interface], returncode=1)
    assert server.host_ips("Darwin") == ["192.168.1.9"]


def test_host_ips_darwin_falls_back_to_localhost(fp: FakeProcess) -> None:
    for interface in ("en0", "en1", "en2", "en3", "en4", "en5"):
        fp.register(["ipconfig", "getifaddr", interface], returncode=1)
    assert server.host_ips("Darwin") == ["localhost"]


class _FakeListener:
    def __init__(self, busy: set[int]) -> None:
        self.busy = busy

    def __enter__(self) -> _FakeListener:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def bind(self, address: tuple[str, int]) -> None:
        if address[1] in self.busy:
            raise OSError("busy")


def test_port_defaults_to_container_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "socket", lambda *a, **k: _FakeListener(set()))
    assert server.port_for() == server.CONTAINER_PORT


def test_port_skips_occupied_container_port(monkeypatch: pytest.MonkeyPatch) -> None:
    busy = {server.CONTAINER_PORT}
    monkeypatch.setattr(socket, "socket", lambda *a, **k: _FakeListener(busy))
    assert server.port_for() == server.CONTAINER_PORT + 1
    with pytest.raises(ValueError, match="unavailable"):
        server.port_for(server.CONTAINER_PORT)


def test_urls_are_bare_and_deduplicated() -> None:
    assert server.urls(["localhost"], 4996) == ["localhost:4996"]
    assert server.urls(["10.0.0.5", "10.0.0.5", ""], 5000) == ["10.0.0.5:5000"]
    assert server.urls(["fd00::5"], 4996) == ["[fd00::5]:4996"]


def test_port_range_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args: object, **kwargs: object) -> socket.socket:
        raise OSError("busy")

    monkeypatch.setattr(socket, "socket", unavailable)
    with pytest.raises(ValueError, match="No free port"):
        server.port_for()


def test_password_from_config_and_invalid_config(tmp_path: Path) -> None:
    assert server.configured_password(tmp_path) is None
    config = tmp_path / ".config/opencode/service.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"password": "saved-password", "hostname": "127.0.0.1"}')
    assert server.configured_password(tmp_path) == "saved-password"
    for invalid in ("broken", "[]", '{"password": 123}', '{"password": ""}'):
        config.write_text(invalid)
        with pytest.raises(ValueError):
            server.configured_password(tmp_path)
