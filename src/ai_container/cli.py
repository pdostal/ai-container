"""ai-container: launch the containerized AI Coding Assistants environment.

Usage syntax::

    ai-container [WRAPPER OPTIONS] -- [TOOL ARGS]

Everything before ``--`` configures this launcher (engine, mounts, web
mode, ...). Everything after ``--`` is passed straight through to the
entrypoint running inside the container (OpenCode, Claude Code, or
whatever ``--entrypoint`` points at).

The app is built with Click/Typer's ``ignore_unknown_options`` context
setting, so ``--`` is only *required* when a tool argument's name collides
with one of the launcher's own flags (or with ``-h``/``--help``). Any other
option-looking token (``-c``, ``--resume``, ...) falls straight through to
the entrypoint even without a preceding ``--``, since it keeps scanning the
whole command line for flags it recognizes rather than stopping at the
first one it doesn't -- see the "Usage" section of README.md for examples.
"""

from __future__ import annotations

import os
import platform
import re
import sys
from pathlib import Path
from typing import Annotated

import typer

from . import (
    __version__,
    config,
    defaults,
    git_utils,
    mounts,
    paths,
    rich_patches,
    selinux,
    ssh_agent,
    web,
)
from . import engine as engine_ops
from . import workspace as workspace_ops
from .console import Reporter
from .models import Engine, MountAccess, MountEntry, MountKind, MountSpec
from .naming import random_container_name
from .runner import build_argv, run, spawn_relay_chmod_fix

rich_patches.apply()

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
    context_settings={
        "help_option_names": ["-h", "--help"],
        # Let unrecognized options (e.g. `-c`, `--resume`) fall through to
        # tool_args instead of erroring, so `--` is only needed to forward
        # a name that collides with one of *our* flags. See the module
        # docstring above.
        "ignore_unknown_options": True,
    },
)

CONTAINER_HOME = Path("/home/coder")
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
DEFAULT_OPENCODE_ENTRYPOINT = "/usr/bin/opencode"
DEFAULT_CLAUDE_ENTRYPOINT = str(CONTAINER_HOME / ".local/bin/claude")


class CliError(Exception):
    """A user-facing error that should exit(1) with a plain message."""


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ai-container {__version__}")
        raise typer.Exit()


@app.command()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            callback=_version_callback,
            is_eager=True,
            help="Show the installed ai-container version and exit.",
        ),
    ] = None,
    entrypoint: Annotated[
        str | None,
        typer.Option(
            "--entrypoint", help="Command to run inside the container.", show_default=False
        ),
    ] = None,
    claude: Annotated[
        bool, typer.Option("--claude", help="Shortcut for --entrypoint the bundled Claude Code.")
    ] = False,
    opencode: Annotated[
        bool,
        typer.Option(
            "--opencode", help="Shortcut for --entrypoint the bundled OpenCode (default)."
        ),
    ] = False,
    web_mode: Annotated[
        bool, typer.Option("--web", help="Run OpenCode as a background web server.")
    ] = False,
    web_port: Annotated[int, typer.Option("--web-port", help="Port for --web.")] = 4996,
    web_username: Annotated[
        str, typer.Option("--web-username", help="HTTP basic auth username for --web.")
    ] = "coder",
    web_password: Annotated[
        str | None,
        typer.Option(
            "--web-password",
            help="HTTP basic auth password for --web (random if unset).",
            show_default=False,
        ),
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            help="Mount a named workspace's dirs (see [[workspace]] in the config file). "
            "Overrides auto_workspaces detection.",
            show_default=False,
        ),
    ] = None,
    extra_mount: Annotated[
        list[str] | None,
        typer.Option(
            "--extra-mount",
            "-m",
            help="Bind mount SOURCE[:TARGET][:ro|rw] (default rw; directory or file). "
            "Repeatable. Wins over --disable-mount.",
        ),
    ] = None,
    disable_mount: Annotated[
        list[Path] | None,
        typer.Option(
            "--disable-mount",
            help="Skip default mounts at or below this absolute host path. Repeatable.",
        ),
    ] = None,
    worktree_mount: Annotated[
        bool,
        typer.Option(
            "--worktree-mount/--no-worktree-mount",
            help="Auto rw-mount a git worktree's parent checkout.",
        ),
    ] = True,
    add_host: Annotated[
        list[str] | None,
        typer.Option(
            "--add-host",
            help="Extra /etc/hosts entry as host:ip. Repeatable. Not supported by `container`.",
        ),
    ] = None,
    env: Annotated[
        list[str] | None,
        typer.Option(
            "--extra-env",
            help="Forward NAME from the host, or set NAME=value (${HOST_VAR} expands from "
            "the host). Repeatable. Wins over --disable-env.",
        ),
    ] = None,
    disable_env: Annotated[
        list[str] | None,
        typer.Option(
            "--disable-env",
            help="Don't set this NAME (built-in defaults and config extra_envs). Repeatable.",
        ),
    ] = None,
    ssh_agent_flag: Annotated[
        bool | None,
        typer.Option(
            "--ssh-agent/--no-ssh-agent",
            help="Forward the host SSH agent. Defaults to the config file's ssh_agent (true).",
            show_default=False,
        ),
    ] = None,
    debug: Annotated[
        bool, typer.Option("--debug", help="Verbose launcher + assistant debug output.")
    ] = False,
    debug_podman: Annotated[
        bool,
        typer.Option(
            "--debug-podman",
            help="Verbose podman/container/docker engine debug output (very noisy).",
        ),
    ] = False,
    microvm: Annotated[
        bool,
        typer.Option(
            "--microvm/--no-microvm",
            help="Run the container in a KVM microVM via crun's krun runtime "
            "(needs the crun-krun package and /dev/kvm). Podman only.",
        ),
    ] = False,
    runtime: Annotated[
        str | None,
        typer.Option(
            "--runtime",
            help="Container engine: podman, container or docker. Defaults to "
            "$AI_CONTAINER_RUNTIME, then autodetection.",
            show_default=False,
        ),
    ] = None,
    tool_args: Annotated[
        list[str] | None,
        typer.Argument(
            help="Arguments passed through to the entrypoint. Unrecognized flags "
            "(e.g. -c, --resume) are forwarded automatically; -- is only needed "
            "to forward a name that collides with one of the options above."
        ),
    ] = None,
) -> None:
    """Launch the AI Coding Assistants container.

    [bold]Examples[/bold]

        ai-container

        ai-container --web --web-port 5000

        ai-container --claude --resume

        ai-container --entrypoint /bin/bash -c 'echo hi'

        ai-container --claude -- --debug

    [dim]The last example forwards a literal "--debug" to Claude Code itself,
    rather than turning on this launcher's own --debug output -- needed only
    because "--debug" collides with one of ai-container's own flags.[/dim]
    """
    reporter = Reporter(debug=debug)
    host_platform = platform.system()
    host_home = Path.home()
    tool_args = list(tool_args or [])

    try:
        cli_mounts = [config.parse_mount(m, source="--extra-mount") for m in extra_mount or []]
        cli_envs = {config.env_name(e, source="--extra-env"): e for e in env or []}
        resolved_entrypoint = _resolve_entrypoint(
            entrypoint=entrypoint, claude=claude, opencode=opencode
        )
        selected_engine = engine_ops.resolve_engine(
            explicit=runtime,
            env_runtime=os.environ.get("AI_CONTAINER_RUNTIME"),
            host_platform=host_platform,
        )
        engine_ops.ensure_available(selected_engine)
        docker_rootless = selected_engine is Engine.DOCKER and engine_ops.docker_is_rootless()
        if microvm and selected_engine is not Engine.PODMAN:
            raise CliError(
                "--microvm is only supported with the podman engine "
                "(Apple's container tool already runs each container in its own VM; "
                "docker has no krun runtime)."
            )
        launcher_config = config.load_config(config.config_path(host_home))
        disabled_mounts = tuple(
            dict.fromkeys(
                [
                    *launcher_config.disable_mounts,
                    *(
                        config.normalize_disable_path(p, source="--disable-mount")
                        for p in disable_mount or []
                    ),
                ]
            )
        )
        config_add_hosts = _validate_add_hosts(list(launcher_config.add_hosts))
        cli_add_hosts = _validate_add_hosts(list(add_host or []))
        if cli_add_hosts and selected_engine is Engine.CONTAINER:
            raise CliError(
                "--add-host is only supported with the podman engine "
                "(Apple's container tool has no /etc/hosts equivalent flag)."
            )
        combined_add_hosts = list(dict.fromkeys([*config_add_hosts, *cli_add_hosts]))
        try:
            cwd = Path.cwd()
        except (FileNotFoundError, OSError) as exc:
            raise CliError("Current directory is gone; refusing to bind-mount workdir.") from exc
        target_workdir = paths.resolve_target_workdir(
            cwd, host_home=host_home, container_home=CONTAINER_HOME
        )
        active_workspace = workspace_ops.resolve(
            explicit_name=workspace,
            auto=launcher_config.auto_workspaces,
            cwd=cwd,
            workspaces=launcher_config.workspaces,
        )
    except engine_ops.UnknownEngineError as exc:
        reporter.fail(
            f"Unknown --runtime/AI_CONTAINER_RUNTIME value: {exc} "
            "(expected 'podman', 'container' or 'docker')"
        )
        raise typer.Exit(1) from exc
    except engine_ops.EngineProbeError as exc:
        reporter.fail(f"Could not query the docker daemon: {exc}")
        raise typer.Exit(1) from exc
    except engine_ops.EngineNotFoundError as exc:
        reporter.fail(f"Selected runtime '{exc}' not found on $PATH")
        raise typer.Exit(1) from exc
    except paths.HomeDirectoryWorkdirError as exc:
        reporter.fail(f"Refusing to run: current directory is your entire $HOME ({exc})")
        reporter.detail("Run this from a project subdirectory instead.")
        raise typer.Exit(1) from exc
    except config.ConfigError as exc:
        reporter.fail(str(exc))
        raise typer.Exit(1) from exc
    except workspace_ops.WorkspaceNotFoundError as exc:
        reporter.fail(str(exc))
        raise typer.Exit(1) from exc
    except CliError as exc:
        reporter.fail(str(exc))
        raise typer.Exit(1) from exc

    image = engine_ops.image_name(selected_engine)
    selinux_status = selinux.detect(host_platform=host_platform, reporter=reporter)
    # docker gets label=disable (see identity_args); its --mount has no z option.
    selinux_enabled = selinux_status.enabled and selected_engine is not Engine.DOCKER
    container_name = random_container_name()

    local_mounts: list[MountEntry] = []
    if active_workspace is not None:
        local_mounts.extend(MountEntry(d) for d in active_workspace.dirs)

    if worktree_mount:
        worktree_parent = git_utils.detect_worktree_parent(cwd)
        if worktree_parent is not None:
            local_mounts.append(MountEntry(worktree_parent))
            reporter.ok(f"Detected git worktree; auto-mounting parent repo: {worktree_parent}")

    args: list[str] = [
        "--rm",
        "--name",
        container_name,
        "-e",
        f"HOME={CONTAINER_HOME}",
        "-w",
        str(target_workdir),
        f"--mount=type=bind,source={cwd},target={target_workdir}"
        f"{selinux.bind_suffix(selinux_enabled)}",
    ]
    args.extend(engine_ops.identity_args(selected_engine, docker_rootless=docker_rootless))
    reporter.debug_ok(f"Mounting working directory (bind-mount, rw): {cwd} \u2192 {target_workdir}")

    mounted_targets: set[Path] = {target_workdir}
    known_hosts = MountEntry(
        host_home / ".ssh/known_hosts", CONTAINER_HOME / ".ssh/known_hosts", MountAccess.READ_ONLY
    )
    credentials = defaults.vertex_credentials(os.environ, cwd=cwd, container_home=CONTAINER_HOME)
    if credentials and mounts.is_disabled(credentials[0].host, disabled_mounts):
        reporter.debug_fail(f"Vertex credentials disabled: {credentials[0].host}")
        credentials = None
    default_mounts = [
        *defaults.assistant_mounts(host_home),
        *([credentials[0]] if credentials else []),
    ]
    # First mount of a target wins: CLI, config, workspace/worktree, built-in defaults, SSH.
    for entries, disabled in (
        (cli_mounts, ()),
        (launcher_config.extra_mounts, disabled_mounts),
        (local_mounts, ()),
        (default_mounts, disabled_mounts),
        ([known_hosts], disabled_mounts),
    ):
        _apply_mounts(
            args,
            entries,
            mounted_targets=mounted_targets,
            disabled=disabled,
            cwd=cwd,
            host_home=host_home,
            selinux_enabled=selinux_enabled,
            reporter=reporter,
        )
    _apply_add_hosts(args, combined_add_hosts, engine=selected_engine, reporter=reporter)
    if ssh_agent_flag if ssh_agent_flag is not None else launcher_config.ssh_agent:
        forwarding = ssh_agent.configure(
            engine=selected_engine,
            container_home=CONTAINER_HOME,
            host_platform=host_platform,
            selinux_enabled=selinux_enabled,
            reporter=reporter,
        )
    else:
        reporter.debug_fail("SSH agent forwarding disabled")
        forwarding = ssh_agent.SshForwarding(args=[], env={}, needs_relay_chmod=False)
    args.extend(forwarding.args)
    for key, value in forwarding.env.items():
        args.extend(["-e", f"{key}={value}"])

    disabled_envs = {*launcher_config.disable_envs, *(disable_env or [])}
    env_entries: dict[str, str] = {}
    default_envs = [*defaults.vertex_envs(os.environ), *([credentials[1]] if credentials else [])]
    for entry in [*default_envs, *launcher_config.extra_envs]:
        name = config.env_name(entry, source="config")
        if name in disabled_envs:
            reporter.debug_fail(f"{name} disabled")
        else:
            env_entries[name] = entry
    env_entries.update(cli_envs)
    for entry in env_entries.values():
        _apply_env(args, entry, reporter)

    if web_mode:
        web_config = web.configure(
            port=web_port,
            username=web_username,
            password=web_password,
            tool_args=tool_args,
            host_platform=host_platform,
            reporter=reporter,
        )
        args.extend(web_config.args)
        tool_args = web_config.tool_args
    elif sys.stdin.isatty() and sys.stdout.isatty():
        args.extend(engine_ops.tty_args(selected_engine))
    else:
        args.append("-i")
        reporter.debug_detail("\u25cb No TTY detected; running without -t")

    args.extend(engine_ops.network_args(selected_engine))
    args.extend(engine_ops.oci_runtime_args(selected_engine, microvm=microvm))

    engine_debug_args: list[str] = []
    if debug_podman:
        engine_debug_args = engine_ops.debug_args(selected_engine)
    if debug and resolved_entrypoint.endswith("/opencode"):
        tool_args = ["--print-logs", "--log-level", "DEBUG", *tool_args]

    engine_ops.announce(
        selected_engine,
        container_name,
        reporter=reporter,
        workspace=active_workspace.name if active_workspace else None,
    )
    if debug or resolved_entrypoint not in (DEFAULT_OPENCODE_ENTRYPOINT, DEFAULT_CLAUDE_ENTRYPOINT):
        reporter.step(f"Using entrypoint: {resolved_entrypoint}")
    if tool_args:
        reporter.step(f"Passing params: {' '.join(tool_args)}")

    if forwarding.needs_relay_chmod:
        spawn_relay_chmod_fix(selected_engine, container_name)

    argv = build_argv(
        engine=selected_engine,
        engine_debug_args=engine_debug_args,
        entrypoint=resolved_entrypoint,
        args=args,
        image=image,
        tool_args=tool_args,
    )
    raise typer.Exit(run(argv))


def _resolve_entrypoint(*, entrypoint: str | None, claude: bool, opencode: bool) -> str:
    if claude and opencode:
        raise CliError("Cannot use --claude and --opencode together.")
    if entrypoint is not None:
        return entrypoint
    if claude:
        return DEFAULT_CLAUDE_ENTRYPOINT
    return DEFAULT_OPENCODE_ENTRYPOINT


def _apply_mounts(
    args: list[str],
    entries: list[MountEntry] | tuple[MountEntry, ...],
    *,
    mounted_targets: set[Path],
    disabled: tuple[Path, ...],
    cwd: Path,
    host_home: Path,
    selinux_enabled: bool,
    reporter: Reporter,
) -> None:
    for entry in entries:
        host = Path(os.path.normpath(cwd / entry.host))
        if mounts.is_disabled(host, disabled):
            reporter.debug_fail(f"Mount disabled: {host}")
            continue
        target = entry.container or paths.map_to_container_path(
            host, host_home=host_home, container_home=CONTAINER_HOME
        )
        if target in mounted_targets:
            reporter.debug_fail(f"{target} skipped (already mounted)")
            continue
        kind = MountKind.DIRECTORY if host.is_dir() else MountKind.FILE
        spec = MountSpec(str(target), host, target, kind, entry.access)
        if mounts.apply_mount(args, spec, selinux_enabled=selinux_enabled, reporter=reporter):
            mounted_targets.add(target)


def _validate_add_hosts(entries: list[str]) -> list[str]:
    for entry in entries:
        host, sep, value = entry.partition(":")
        if not sep or not host or not value:
            raise CliError(f"Invalid --add-host entry: {entry!r} (expected host:ip)")
    return entries


def _apply_add_hosts(
    args: list[str], entries: list[str], *, engine: Engine, reporter: Reporter
) -> None:
    if not entries:
        return
    if engine is Engine.CONTAINER:
        # Config-supplied entries only reach here (an explicit --add-host is
        # already a hard error above); skip quietly since the config file is
        # meant to be a harmless static default across engines/hosts.
        for entry in entries:
            reporter.debug_fail(f"Skipping --add-host (unsupported on container engine): {entry}")
        return
    for entry in entries:
        reporter.debug_ok(f"Adding hosts entry: {entry}")
        args.append(f"--add-host={entry}")


def _apply_env(args: list[str], entry: str, reporter: Reporter) -> None:
    """Forward ``NAME`` if set on the host, or set ``NAME=value`` expanding ``${HOST_VAR}``."""
    name, sep, raw = entry.partition("=")
    if sep:
        missing = [v for v in _ENV_REF_RE.findall(raw) if not os.environ.get(v)]
        value = None if missing else _ENV_REF_RE.sub(lambda m: os.environ[m[1]], raw)
        reason = f"{name} skipped ({', '.join(missing)} not set)"
    else:
        value, reason = os.environ.get(name) or None, f"{name} not set"
    if value is None:
        reporter.debug_fail(reason)
        return
    reporter.debug_ok(f"Setting {name} environment variable")
    args.extend(["-e", f"{name}={value}"])


def run_app() -> None:
    app()


if __name__ == "__main__":
    run_app()
