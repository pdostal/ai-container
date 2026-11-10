"""Server mode: run OpenCode as a background HTTP server."""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .console import Reporter
from .naming import random_server_password

CONTAINER_PORT = 4996
SERVICE_LABEL = "ai-container.opencode-server"


def port_for(cwd: Path, explicit: int | None = None) -> int:
    """Probe the host port range, starting at a stable hash of the canonical path."""
    # shortcut: ports are not reserved; add bind-failure retries if concurrent starts collide.
    start = int.from_bytes(hashlib.sha256(str(cwd.resolve()).encode()).digest()[:8]) % 500
    candidates = (
        [explicit] if explicit is not None else [5000 + (start + i) % 500 for i in range(500)]
    )
    for port in candidates:
        try:
            with socket.socket() as listener:
                listener.bind(("0.0.0.0", port))  # noqa: S104
        except OSError:
            continue
        return port
    raise ValueError(
        f"Port {explicit} is unavailable." if explicit else "No free port in 5000-5499."
    )


def configured_password(host_home: Path) -> str | None:
    """Read the shared credential without starting or stopping a host service."""
    path = host_home / ".config/opencode/service.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read OpenCode service config: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid OpenCode service config: {path}")
    password = data.get("password")
    if password is not None and (not isinstance(password, str) or not password):
        raise ValueError(f"Invalid OpenCode service password: {path}")
    return password


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
        f"0.0.0.0:{port}:{CONTAINER_PORT}",
        "-e",
        f"OPENCODE_PASSWORD={resolved_password}",
    ]
    new_tool_args = ["serve", "--hostname", "0.0.0.0", "--port", str(CONTAINER_PORT), *tool_args]  # noqa: S104

    host_ip = _host_ip(host_platform)
    reporter.ok(f"Server mode: http://{host_ip}:{port}")
    reporter.ok(f"Server username: {username}")
    reporter.ok(f"Server password: {resolved_password}")

    return ServerConfig(args=args, tool_args=new_tool_args, password=resolved_password)
