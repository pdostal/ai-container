"""Container engine selection (podman / Apple `container`).

Docker isn't supported yet ("maybe in the future" per the project brief).
When it is, it plugs in as one more ``Engine`` member plus one more branch
in each of the small functions below -- deliberately not over-abstracted
into a plugin system for two engines.
"""

from __future__ import annotations

import os
import shutil

from .console import Reporter
from .models import Engine


class EngineNotFoundError(Exception):
    """Raised when the selected engine binary isn't on $PATH."""


class UnknownEngineError(Exception):
    """Raised when --runtime/$AI_CONTAINER_RUNTIME names an unsupported engine."""


def resolve_engine(*, explicit: str | None, env_runtime: str | None, host_platform: str) -> Engine:
    """Pick an engine: explicit choice wins, then $AI_CONTAINER_RUNTIME, then
    autodetection (podman first everywhere, falling back to Apple's
    ``container`` on macOS if podman isn't installed).
    """
    requested = explicit or env_runtime
    if requested:
        try:
            return Engine(requested)
        except ValueError as exc:
            raise UnknownEngineError(requested) from exc

    if shutil.which("podman"):
        return Engine.PODMAN
    if host_platform == "Darwin" and shutil.which("container"):
        return Engine.CONTAINER
    return Engine.PODMAN


def ensure_available(engine: Engine) -> None:
    if shutil.which(engine.value) is None:
        raise EngineNotFoundError(engine.value)


def image_name(engine: Engine) -> str:
    return "ai" if engine is Engine.CONTAINER else "localhost/ai"


def identity_args(engine: Engine) -> list[str]:
    """Args that make the container run as the current host user."""
    if engine is Engine.PODMAN:
        # `container` has no hostname flag; podman's SELinux label-disable
        # has no `container` equivalent either.
        return ["-h", "ai", "--security-opt", "label=disable"]
    return ["--uid", str(os.getuid()), "--gid", str(os.getgid())]


def network_args(engine: Engine) -> list[str]:
    if engine is Engine.PODMAN:
        return ["--network=pasta", "--userns=keep-id"]
    return []


def oci_runtime_args(engine: Engine, *, microvm: bool) -> list[str]:
    """`krun` (crun+libkrun) runs the container in a KVM microVM instead of
    plain namespaces. `use_passt` is needed for pasta (see network_args)
    traffic to reach the guest. No equivalent exists for `container`.
    """
    if engine is Engine.PODMAN and microvm:
        return ["--runtime", "krun", "--annotation", "krun.use_passt=1"]
    return []


def tty_args(engine: Engine) -> list[str]:
    return ["-it"] if engine is Engine.PODMAN else ["-i", "-t"]


def debug_args(engine: Engine) -> list[str]:
    return ["--log-level=debug"] if engine is Engine.PODMAN else ["--debug"]


def announce(engine: Engine, name: str, *, reporter: Reporter) -> None:
    reporter.ok(f"{engine.value} container: {name}")
