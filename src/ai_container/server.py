"""Server mode: run OpenCode as a background HTTP server."""

from __future__ import annotations

import contextlib
import json
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .naming import random_server_password

CONTAINER_PORT = 4996
SERVICE_LABEL = "ai-container.opencode-server"


def port_for(explicit: int | None = None) -> int:
    """Probe the host port range, trying the container port first so they match."""
    # shortcut: ports are not reserved; add bind-failure retries if concurrent starts collide.
    candidates = [explicit] if explicit is not None else list(range(CONTAINER_PORT, 5500))
    for port in candidates:
        try:
            with socket.socket() as listener:
                listener.bind(("0.0.0.0", port))  # noqa: S104
        except OSError:
            continue
        return port
    raise ValueError(
        f"Port {explicit} is unavailable."
        if explicit
        else f"No free port in {CONTAINER_PORT}-5499."
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
    username: str
    urls: list[str]


def urls(hosts: list[str], port: int) -> list[str]:
    """Bare ``host:port`` endpoints, IPv6 bracketed, deduplicated in order."""
    return list(dict.fromkeys(f"[{h}]:{port}" if ":" in h else f"{h}:{port}" for h in hosts if h))


def _reachable(ip: str) -> bool:
    """False for loopback and link-local addresses."""
    return bool(ip) and not ip.startswith(("127.", "::1", "169.254.", "fe80:"))


def host_ips(host_platform: str) -> list[str]:
    """Host addresses other machines can reach; ``localhost`` when none is found."""
    candidates: list[str] = []
    if host_platform == "Darwin":
        for index in range(6):
            try:
                result = subprocess.run(
                    ["ipconfig", "getifaddr", f"en{index}"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
            candidates.append(result.stdout.strip())
    else:
        try:
            result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, check=True)
            candidates = result.stdout.split()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        if not candidates:
            with contextlib.suppress(OSError):
                candidates = [socket.gethostbyname(socket.gethostname())]
    return list(dict.fromkeys(ip for ip in candidates if _reachable(ip))) or ["localhost"]


def configure(
    *,
    port: int,
    username: str,
    password: str | None,
    tool_args: list[str],
    host_platform: str,
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

    return ServerConfig(
        args=args,
        tool_args=new_tool_args,
        password=resolved_password,
        username=username,
        urls=urls(host_ips(host_platform), port),
    )
