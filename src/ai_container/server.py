"""Server mode: run OpenCode as a background HTTP server."""

from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass

from .console import Reporter
from .naming import random_server_password


@dataclass(frozen=True, slots=True)
class ServerConfig:
    args: list[str]
    tool_args: list[str]
    password: str


def _host_ip(host_platform: str) -> str:
    if host_platform == "Darwin":
        for interface in ("en0", "en1"):
            try:
                result = subprocess.run(
                    ["ipconfig", "getifaddr", interface],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
            ip = result.stdout.strip()
            if ip:
                return ip
        return "localhost"

    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, check=True)
        ip = result.stdout.split()[0]
        if ip:
            return ip
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError):
        pass

    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "localhost"


def configure(
    *,
    port: int,
    username: str,
    password: str | None,
    tool_args: list[str],
    host_platform: str,
    reporter: Reporter,
) -> ServerConfig:
    resolved_password = password or random_server_password()
    args = [
        "-d",
        "-p",
        f"{port}:{port}",
        "-e",
        f"OPENCODE_PASSWORD={resolved_password}",
    ]
    new_tool_args = ["serve", "--hostname", "0.0.0.0", "--port", str(port), *tool_args]  # noqa: S104

    host_ip = _host_ip(host_platform)
    reporter.ok(f"Server mode: http://{host_ip}:{port}")
    reporter.ok(f"Server username: {username}")
    reporter.ok(f"Server password: {resolved_password}")

    return ServerConfig(args=args, tool_args=new_tool_args, password=resolved_password)
