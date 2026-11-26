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

AGENT_DIR = Path("/run/ssh-agent")


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
    host_platform: str = "Linux",
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
        host = Path(sock)
        if engine is Engine.DOCKER and host_platform == "Darwin":
            # Docker Desktop can't mount the host socket; it offers a relay at this path.
            source = mount_target = target = Path("/run/host-services/ssh-auth.sock")
        elif host.parent != Path("/"):
            # Mount the socket's directory so an agent that recreates the socket
            # in place (keyring, systemd user socket) still works after a reattach.
            source, mount_target = host.parent, AGENT_DIR
            target = AGENT_DIR / host.name
        else:
            source = host
            mount_target = target = container_home / ".ssh/agent" / host.name
        reporter.debug_ok(f"Mounting SSH agent socket (bind-mount, rw): {source}")
        reporter.debug_detail(f"Setting SSH_AUTH_SOCK={target}")
        suffix = selinux.bind_suffix(selinux_enabled)
        return SshForwarding(
            args=[f"--mount=type=bind,source={source},target={mount_target}{suffix}"],
            env={"SSH_AUTH_SOCK": str(target)},
            needs_relay_chmod=False,
        )

    reporter.debug_fail("SSH agent socket not available")
    return SshForwarding(args=[], env={}, needs_relay_chmod=False)


def fix_relay_permissions(engine: Engine, container_name: str, *, attempts: int = 20) -> None:
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
        # Never inherit the real terminal's stdin: it would race the
        # foreground `container run -it` for keystrokes. start_new_session
        # detaches it from the terminal's process group as a second line of defense.
        result = subprocess.run(
            [engine.value, "exec", "-u", "root", container_name, "sh", "-c", command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            check=False,
        )
        if result.returncode == 0:
            return
        if attempt + 1 < attempts:
            time.sleep(0.25)
