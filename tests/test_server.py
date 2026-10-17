from __future__ import annotations

from pytest_subprocess import FakeProcess

from ai_container import server
from ai_container.console import Reporter


def test_configure_generates_password_when_unset(fp: FakeProcess) -> None:
    fp.register(["hostname", "-I"], stdout="10.0.0.5 fe80::1\n")
    result = server.configure(
        port=4996,
        username="opencode",
        password=None,
        tool_args=["--resume"],
        host_platform="Linux",
        reporter=Reporter(),
    )
    assert len(result.password) == 20
    assert "OPENCODE_PASSWORD=" + result.password in result.args
    assert result.tool_args == ["serve", "--hostname", "0.0.0.0", "--port", "4996", "--resume"]


def test_configure_keeps_explicit_password(fp: FakeProcess) -> None:
    fp.register(["hostname", "-I"], stdout="10.0.0.5\n")
    result = server.configure(
        port=5000,
        username="opencode",
        password="hunter2",
        tool_args=[],
        host_platform="Linux",
        reporter=Reporter(),
    )
    assert result.password == "hunter2"
    assert "OPENCODE_PASSWORD=hunter2" in result.args
    assert "-p" in result.args and "5000:5000" in result.args


def test_host_ip_linux_uses_hostname_dash_i(fp: FakeProcess) -> None:
    fp.register(["hostname", "-I"], stdout="192.168.1.7 10.0.0.1\n")
    assert server._host_ip("Linux") == "192.168.1.7"


def test_host_ip_darwin_uses_ipconfig(fp: FakeProcess) -> None:
    fp.register(["ipconfig", "getifaddr", "en0"], stdout="192.168.1.9\n")
    assert server._host_ip("Darwin") == "192.168.1.9"


def test_host_ip_darwin_falls_back_to_localhost(fp: FakeProcess) -> None:
    fp.register(["ipconfig", "getifaddr", "en0"], returncode=1)
    fp.register(["ipconfig", "getifaddr", "en1"], returncode=1)
    assert server._host_ip("Darwin") == "localhost"
