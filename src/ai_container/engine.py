"""Container engine selection (podman / Apple `container` / docker).

Each engine is one ``Engine`` member plus one branch in each of the small
functions below -- deliberately not over-abstracted into a plugin system.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from .console import Reporter
from .models import Engine


class EngineNotFoundError(Exception):
    """Raised when the selected engine binary isn't on $PATH."""


class EngineProbeError(Exception):
    """Raised when the engine daemon can't be queried (e.g. `docker info` fails)."""


class UnknownEngineError(Exception):
    """Raised when --runtime/$AI_CONTAINER_RUNTIME names an unsupported engine."""


def resolve_engine(*, explicit: str | None, env_runtime: str | None, host_platform: str) -> Engine:
    """Pick an engine: explicit choice wins, then $AI_CONTAINER_RUNTIME, then
    autodetection (podman first everywhere, then Apple's ``container`` on
    macOS, then docker).
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
    if shutil.which("docker"):
        return Engine.DOCKER
    return Engine.PODMAN


def docker_is_rootless() -> bool:
    """Ask the daemon (honoring DOCKER_HOST/context) whether it runs rootless."""
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{json .SecurityOptions}}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise EngineProbeError(str(exc)) from exc
    if result.returncode != 0:
        raise EngineProbeError(result.stderr.strip() or "`docker info` failed")
    return "name=rootless" in result.stdout


def ensure_available(engine: Engine) -> None:
    if shutil.which(engine.value) is None:
        raise EngineNotFoundError(engine.value)


def image_name(engine: Engine) -> str:
    return "localhost/ai" if engine is Engine.PODMAN else "ai"


def identity_args(engine: Engine, *, docker_rootless: bool = False) -> list[str]:
    """Args that make the container run as the current host user.

    Rootless docker maps container uid 0 to the host user (and uid N to a
    subuid), so running as 0:0 is what keeps bind mounts writable.
    """
    if engine is Engine.DOCKER:
        user = "0:0" if docker_rootless else f"{os.getuid()}:{os.getgid()}"
        return ["-h", "ai", "--security-opt", "label=disable", "--user", user]
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
    return ["-i", "-t"] if engine is Engine.CONTAINER else ["-it"]


def debug_args(engine: Engine) -> list[str]:
    return ["--log-level=debug"] if engine is Engine.PODMAN else ["--debug"]


def announce(
    engine: Engine, name: str, *, reporter: Reporter, workspace: str | None = None
) -> None:
    suffix = f" (Workspace: {workspace})" if workspace else ""
    reporter.ok(f"{engine.value} container: {name}{suffix}")
