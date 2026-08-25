"""SSH agent forwarding and the Apple `container` rootless relay workaround."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import selinux
from .console import Reporter
from .models import Engine


@dataclass(frozen=True, slots=True)
class SshForwarding:
    args: list[str]
    env: dict[str, str]
    needs_relay_chmod: bool


def _socket_available() -> str | None:
    sock = os.environ.get("SSH_AUTH_SOCK")
    if sock and Path(sock).is_socket():
        return sock
    return None


def configure(
    *,
    engine: Engine,
    container_home: Path,
    selinux_enabled: bool,
    reporter: Reporter,
) -> SshForwarding:
    sock = _socket_available()

    if engine is Engine.CONTAINER:
        # `container`'s virtiofs bind mounts can't carry a raw AF_UNIX socket
        # file, so use its own `--ssh` forwarding flag instead of a mount.
        if sock:
            reporter.debug_ok(f"Forwarding SSH agent socket (--ssh): {sock}")
            return SshForwarding(args=["--ssh"], env={}, needs_relay_chmod=True)
        reporter.debug_fail("SSH agent socket not available")
        return SshForwarding(args=[], env={}, needs_relay_chmod=False)

    if sock:
        target = container_home / ".ssh/agent/ssh-agent.sock"
        reporter.debug_ok(f"Mounting SSH agent socket (bind-mount, rw): {sock}")
        reporter.debug_detail(f"Setting SSH_AUTH_SOCK={target}")
        suffix = selinux.bind_suffix(selinux_enabled)
        return SshForwarding(
            args=[f"--mount=type=bind,source={sock},target={target}{suffix}"],
            env={"SSH_AUTH_SOCK": str(target)},
            needs_relay_chmod=False,
        )

    reporter.debug_fail("SSH agent socket not available")
    return SshForwarding(args=[], env={}, needs_relay_chmod=False)


def fix_relay_permissions(engine: Engine, container_name: str, *, attempts: int = 2) -> None:
    """Loosen the root-owned per-container `--ssh` relay socket so the
    non-root `coder` user can reach it.

    Only touches the ephemeral, per-container relay copy of the socket
    living in that container's own VM -- never the real host ssh-agent
    socket. Runs synchronously; callers wanting the original script's
    "background while the main container starts" behavior should call
    this in a background thread.
    """
    command = (
        "test -S /var/host-services/ssh-auth.sock && chmod 0666 /var/host-services/ssh-auth.sock"
    )
    for attempt in range(attempts):
        result = subprocess.run(
            [engine.value, "exec", "-u", "root", container_name, "sh", "-c", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return
        if attempt + 1 < attempts:
            time.sleep(1)
