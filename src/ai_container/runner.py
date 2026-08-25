"""Assembles and executes the final `podman`/`container` invocation."""

from __future__ import annotations

import shutil
import subprocess
import threading

from .models import Engine


def build_argv(
    *,
    engine: Engine,
    engine_debug_args: list[str],
    entrypoint: str,
    args: list[str],
    image: str,
    tool_args: list[str],
) -> list[str]:
    return [
        engine.value,
        *engine_debug_args,
        "run",
        "--init",
        "--entrypoint",
        entrypoint,
        *args,
        image,
        *tool_args,
    ]


def spawn_relay_chmod_fix(engine: Engine, container_name: str) -> threading.Thread:
    """Start the SSH relay chmod workaround in the background, matching the
    bash script's ``(...)  &`` job that races the container's own startup.
    """
    from . import ssh_agent

    thread = threading.Thread(
        target=ssh_agent.fix_relay_permissions,
        args=(engine, container_name),
        daemon=True,
    )
    thread.start()
    return thread


def run(argv: list[str]) -> int:
    """Run the container engine in the foreground, inheriting stdio.

    Always attempts to restore the terminal afterwards (``stty sane``),
    mirroring the bash script's ``trap ... EXIT`` -- interactive TUI
    entrypoints put the terminal into raw mode, and if the container exits
    abnormally the outer shell would otherwise be left broken.
    """
    try:
        result = subprocess.run(argv, check=False)
        return result.returncode
    finally:
        if shutil.which("stty"):
            subprocess.run(["stty", "sane"], stderr=subprocess.DEVNULL, check=False)
