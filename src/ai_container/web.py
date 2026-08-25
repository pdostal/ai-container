"""Web mode: run OpenCode as a background web server."""

from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass

from .console import Reporter
from .naming import random_web_password


@dataclass(frozen=True, slots=True)
class WebConfig:
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
) -> WebConfig:
    resolved_password = password or random_web_password()
    args = [
        "-d",
        "-p",
        f"{port}:{port}",
        "-e",
        f"OPENCODE_SERVER_PASSWORD={resolved_password}",
        "-e",
        f"OPENCODE_SERVER_USERNAME={username}",
    ]
    new_tool_args = ["web", "--hostname", "0.0.0.0", "--port", str(port), *tool_args]  # noqa: S104

    host_ip = _host_ip(host_platform)
    reporter.ok(f"Web mode: http://{host_ip}:{port}")
    reporter.ok(f"Web username: {username}")
    reporter.ok(f"Web password: {resolved_password}")

    return WebConfig(args=args, tool_args=new_tool_args, password=resolved_password)
