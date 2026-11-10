"""Container engine selection (podman / Apple `container` / docker).

Each engine is one ``Engine`` member plus one branch in each of the small
functions below -- deliberately not over-abstracted into a plugin system.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .console import Reporter
from .models import Engine
from .server import CONTAINER_PORT


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


def network_args(engine: Engine, extra: Sequence[str] = ()) -> list[str]:
    """Default podman networking, plus raw ``extra`` args; an extra ``--network``/``--net``
    replaces the default ``--network=pasta``.
    """
    base: list[str] = []
    if engine is Engine.PODMAN:
        overridden = any(a.partition("=")[0] in ("--network", "--net") for a in extra)
        base = ["--userns=keep-id"] if overridden else ["--network=pasta", "--userns=keep-id"]
    return [*base, *extra]


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


WORKDIR_LABEL = "ai-container.workdir"


def label_args(cwd: Path) -> list[str]:
    return ["--label", f"{WORKDIR_LABEL}={cwd}"]


def find_running(engine: Engine, cwd: Path, *, service: bool = False) -> str | None:
    """Newest running container launched from ``cwd`` (None if none, or on
    `container`, which has no label filter).
    """
    if engine is Engine.CONTAINER:
        return None
    result = subprocess.run(
        [
            engine.value,
            "ps",
            "--filter",
            f"label={WORKDIR_LABEL}={cwd}",
            *(["--filter", "label=ai-container.opencode-server=true"] if service else []),
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    names = result.stdout.split() if result.returncode == 0 else []
    return names[0] if names else None


def published_port(engine: Engine, name: str, port: int) -> int:
    result = subprocess.run(
        [engine.value, "port", name, f"{port}/tcp"], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise EngineProbeError(f"Cannot determine published port for {name}.")
    try:
        return int(result.stdout.splitlines()[0].rsplit(":", 1)[1])
    except (ValueError, IndexError) as exc:
        raise EngineProbeError(f"Cannot determine published port for {name}.") from exc


@dataclass(frozen=True, slots=True)
class ContainerInfo:
    """One running container as shown by `ai-container list`."""

    name: str
    workdir: str
    command: str
    password: str | None
    port: int | None


_PS_FORMAT = (
    '{{.Names}}\t{{.Label "ai-container.workdir"}}\t{{.Label "ai-container.opencode-server"}}'
)
_INSPECT_FORMAT = (
    "{{.Name}}\t{{json .Config.Entrypoint}}\t{{json .Config.Cmd}}\t{{json .Config.Env}}"
)


def _json_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def list_running(engine: Engine) -> list[ContainerInfo]:
    """Running ai-container containers, sorted by workdir then name."""
    if engine is Engine.CONTAINER:
        return []
    result = subprocess.run(
        [engine.value, "ps", "--filter", f"label={WORKDIR_LABEL}", "--format", _PS_FORMAT],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise EngineProbeError(result.stderr.strip() or "`ps` failed")
    rows: dict[str, tuple[str, bool]] = {}
    for line in result.stdout.splitlines():
        name, _, rest = line.partition("\t")
        workdir, _, server_label = rest.partition("\t")
        if name:
            rows[name] = (workdir, server_label == "true")
    if not rows:
        return []

    inspected = subprocess.run(
        [engine.value, "inspect", "--format", _INSPECT_FORMAT, *rows],
        capture_output=True,
        text=True,
        check=False,
    )
    commands: dict[str, tuple[str, str | None]] = {}
    if inspected.returncode == 0:
        for line in inspected.stdout.splitlines():
            name, _, rest = line.partition("\t")
            entrypoint, _, rest = rest.partition("\t")
            cmd, _, env = rest.partition("\t")
            args = [*_json_list(entrypoint), *_json_list(cmd)]
            password = next(
                (
                    item.partition("=")[2]
                    for item in _json_list(env)
                    if item.startswith("OPENCODE_PASSWORD=")
                ),
                None,
            )
            commands[name.removeprefix("/")] = (" ".join(args), password)

    infos = []
    for name, (workdir, is_server) in rows.items():
        command, password = commands.get(name, ("", None))
        port = None
        if is_server:
            try:
                port = published_port(engine, name, CONTAINER_PORT)
            except EngineProbeError:
                port = None
        infos.append(ContainerInfo(name, workdir, command, password, port))
    return sorted(infos, key=lambda info: (info.workdir, info.name))


def debug_args(engine: Engine) -> list[str]:
    return ["--log-level=debug"] if engine is Engine.PODMAN else ["--debug"]


def announce(
    engine: Engine, name: str, *, reporter: Reporter, workspace: str | None = None
) -> None:
    suffix = f" (Workspace: {workspace})" if workspace else ""
    reporter.ok(f"{engine.value} container: {name}{suffix}")
