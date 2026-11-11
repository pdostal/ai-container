"""ai-container: launch the containerized AI Coding Assistants environment.

Usage syntax::

    ai-container [WRAPPER OPTIONS] -- [TOOL ARGS]

Everything before ``--`` configures this launcher (engine, mounts, server
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
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from typer._click.core import Context as TyperContext
from typer.core import TyperCommand

from . import (
    __version__,
    config,
    defaults,
    git_utils,
    mounts,
    paths,
    rich_patches,
    selinux,
    server,
    ssh_agent,
    terminal,
)
from . import engine as engine_ops
from . import workspace as workspace_ops
from .console import Reporter
from .models import Engine, MountAccess, MountEntry, MountKind, MountSpec
from .naming import random_container_name
from .runner import build_argv, build_exec_argv, run, spawn_relay_chmod_fix

rich_patches.apply()


class _DashAwareCommand(TyperCommand):
    """Remember raw tokens after ``--`` so subcommand names there stay literal."""

    def parse_args(self, ctx: TyperContext, args: list[str]) -> list[str]:
        ctx.meta["after_double_dash"] = tuple(args[args.index("--") + 1 :]) if "--" in args else ()
        return super().parse_args(ctx, args)


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
HOST_TERMINFO = Path("/usr/share/terminfo")
CONTAINER_TERMINFO = Path("/run/host-terminfo")
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
SHELL_ENTRYPOINT = "/bin/bash"
INIT_ENTRYPOINT = "/usr/local/bin/init.sh"
DEFAULT_OPENCODE_ENTRYPOINT = defaults.ASSISTANT_ENTRYPOINTS["opencode"]
DEFAULT_CLAUDE_ENTRYPOINT = defaults.ASSISTANT_ENTRYPOINTS["claude"]
DEFAULT_CODEX_ENTRYPOINT = defaults.ASSISTANT_ENTRYPOINTS["codex"]
DEFAULT_COPILOT_ENTRYPOINT = defaults.ASSISTANT_ENTRYPOINTS["copilot"]
DEFAULT_PI_ENTRYPOINT = defaults.ASSISTANT_ENTRYPOINTS["pi"]
BUNDLED_ASSISTANT_ENTRYPOINTS = (
    DEFAULT_OPENCODE_ENTRYPOINT,
    DEFAULT_CLAUDE_ENTRYPOINT,
    DEFAULT_CODEX_ENTRYPOINT,
    DEFAULT_COPILOT_ENTRYPOINT,
    DEFAULT_PI_ENTRYPOINT,
)
SUBCOMMANDS = frozenset({"init", "server", "attach", "continue", "list", "shell", "help"})


class CliError(Exception):
    """A user-facing error that should exit(1) with a plain message."""


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ai-container {__version__}")
        raise typer.Exit()


@app.command(cls=_DashAwareCommand)
def main(
    ctx: typer.Context,
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
    codex: Annotated[
        bool, typer.Option("--codex", help="Shortcut for --entrypoint the bundled Codex CLI.")
    ] = False,
    copilot: Annotated[
        bool,
        typer.Option("--copilot", help="Shortcut for --entrypoint the bundled Copilot CLI."),
    ] = False,
    pi: Annotated[
        bool, typer.Option("--pi", help="Shortcut for --entrypoint the bundled pi agent.")
    ] = False,
    shell: Annotated[
        bool,
        typer.Option(
            "--shell",
            help="Open a bash shell: exec into the running container for this directory "
            "if there is one (podman/docker), else start a new container running bash.",
        ),
    ] = False,
    init_mode: Annotated[
        bool,
        typer.Option(
            "--init",
            help="Initialize host-persisted assistant configuration and skills.",
        ),
    ] = False,
    server_mode: Annotated[
        bool, typer.Option("--server", help="Run OpenCode as a background HTTP server.")
    ] = False,
    list_mode: Annotated[
        bool,
        typer.Option(
            "--list",
            help="List running ai-container containers (name, workdir, command, port, password).",
        ),
    ] = False,
    show_secrets: Annotated[
        bool,
        typer.Option("--show-secrets", help="With --list, print the full server password."),
    ] = False,
    server_port: Annotated[
        int | None,
        typer.Option(
            "--server-port",
            min=1,
            max=65535,
            help="Published OpenCode port (default: free port in 5000-5499).",
        ),
    ] = None,
    attach: Annotated[
        bool | None,
        typer.Option(
            "--attach/--no-attach",
            help="Attach to an existing directory's OpenCode server, or force a fresh container.",
        ),
    ] = None,
    server_username: Annotated[
        str,
        typer.Option("--server-username", help="HTTP basic auth username (V2 requires opencode)."),
    ] = "opencode",
    server_password: Annotated[
        str | None,
        typer.Option(
            "--server-password",
            "--password",
            help="OpenCode server/attach password (default: service config, otherwise random).",
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
    network_arg: Annotated[
        list[str] | None,
        typer.Option(
            "--network-arg",
            help="Raw extra engine network arg, one token per flag. Repeatable. A --network=... "
            "value replaces the default --network=pasta, e.g. "
            "--network-arg=--network=pasta:-i,dummy0,-a,172.29.0.2,-n,24,-g,172.29.0.1 "
            "--network-arg=--dns=1.1.1.1",
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
    debug_runtime: Annotated[
        bool,
        typer.Option(
            "--debug-runtime",
            help="Print the full runtime command and enable its debug output (very noisy).",
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

        ai-container init

        ai-container server --server-port 5000

        ai-container continue

        ai-container list

        ai-container shell

        ai-container --claude --resume

        ai-container --codex

        ai-container --copilot

        ai-container --pi

        ai-container pi -p 'summarize this repo'

        ai-container --server --pi

        ai-container --entrypoint /bin/bash -c 'echo hi'

        ai-container --shell

        ai-container --claude -- --debug

    [dim]Subcommands (init, server, attach, continue, list, shell, help, plus the
    assistant names pi, opencode, claude, codex and copilot) are sugar for the
    matching flag; the flag spellings keep working. Put a forwarded token after
    "--" to keep it literal, as in the last example, which sends "--debug" to
    Claude Code instead of enabling this launcher's own --debug output.[/dim]
    """
    reporter = Reporter(debug=debug)
    host_platform = platform.system()
    host_home = Path.home()
    tool_args = list(tool_args or [])
    continue_mode = False
    pi_server = False
    pi_port: int | None = None
    after_dash = ctx.meta.get("after_double_dash", ())
    if (
        tool_args
        and len(tool_args) > len(after_dash)
        and tool_args[0] in defaults.ASSISTANT_ENTRYPOINTS
        and entrypoint is None
        and not (claude or opencode or codex or copilot or pi)
    ):
        assistant = tool_args.pop(0)
        claude = assistant == "claude"
        opencode = assistant == "opencode"
        codex = assistant == "codex"
        copilot = assistant == "copilot"
        pi = assistant == "pi"
    if tool_args and tool_args[0] in SUBCOMMANDS:
        subcommand = tool_args.pop(0)
        if subcommand == "help":
            typer.echo(ctx.get_help())
            raise typer.Exit()
        if subcommand == "init":
            init_mode = True
        elif subcommand == "server":
            server_mode = True
        elif subcommand == "attach":
            attach = True
        elif subcommand == "continue":
            continue_mode = True
            tool_args.insert(0, "--continue")
        elif subcommand == "list":
            list_mode = True
        elif subcommand == "shell":
            shell = True

    try:
        for argument in tool_args:
            if argument.split("=", 1)[0] in {
                "--web",
                "--web-port",
                "--web-username",
                "--web-password",
            }:
                raise CliError(
                    f"{argument.split('=', 1)[0]} was removed; use --server and --server-* options."
                )
        launcher_config = config.load_config(config.config_path(host_home))
        cli_mounts = [config.parse_mount(m, source="--extra-mount") for m in extra_mount or []]
        cli_envs = {config.env_name(e, source="--extra-env"): e for e in env or []}
        resolved_entrypoint = _resolve_entrypoint(
            entrypoint=entrypoint,
            claude=claude,
            opencode=opencode,
            codex=codex,
            copilot=copilot,
            pi=pi,
            shell=shell,
            init_mode=init_mode,
            server=server_mode,
            default_agent=launcher_config.default_agent,
        )
        pi_server = server_mode and Path(resolved_entrypoint).name == "pi"
        if pi_server and server_password is not None:
            raise CliError("--server-password is not used by pi RPC server mode.")
        if server_mode and not pi_server and server_username != "opencode":
            raise CliError("OpenCode V2 requires --server-username opencode.")
        if continue_mode and Path(resolved_entrypoint).name not in {
            "opencode",
            "opencode2",
            "claude",
            "pi",
        }:
            raise CliError("continue is only supported for OpenCode, Claude Code and pi.")
        if continue_mode and server_mode:
            raise CliError("continue cannot be combined with server mode.")
        if show_secrets and not list_mode:
            raise CliError("--show-secrets requires --list.")
        if attach is not None and (shell or init_mode or claude or codex or copilot or pi):
            raise CliError("--attach/--no-attach can only use OpenCode.")
        if attach is True and server_mode:
            raise CliError("--attach cannot be combined with --server.")
        if codex and entrypoint is None:
            tool_args = ["--disable", "daemon_auto_start", *tool_args]
        selected_engine = engine_ops.resolve_engine(
            explicit=runtime,
            env_runtime=os.environ.get("AI_CONTAINER_RUNTIME"),
            host_platform=host_platform,
        )
        engine_ops.ensure_available(selected_engine)
        if list_mode:
            _list_containers(selected_engine, show_secrets=show_secrets)
            raise typer.Exit()
        docker_rootless = selected_engine is Engine.DOCKER and engine_ops.docker_is_rootless()
        if microvm and selected_engine is not Engine.PODMAN:
            raise CliError(
                "--microvm is only supported with the podman engine "
                "(Apple's container tool already runs each container in its own VM; "
                "docker has no krun runtime)."
            )
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
        extra_network_args = list(
            dict.fromkeys([*launcher_config.extra_network_args, *(network_arg or [])])
        )
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
        if init_mode:
            _initialize_assistant_paths(host_home, reporter)
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

    interactive = terminal.should_allocate_tty(
        stdin_tty=sys.stdin.isatty(),
        stdout_tty=sys.stdout.isatty(),
        term=os.environ.get("TERM"),
    )
    terminal_session = interactive and not server_mode
    terminal_title = (
        terminal.title_for(
            workspace=active_workspace.name if active_workspace else None,
            cwd=cwd,
            entrypoint=resolved_entrypoint,
        )
        if terminal_session
        else None
    )
    opencode_entrypoint = Path(resolved_entrypoint).name in {"opencode", "opencode2"}
    passthrough = bool(
        tool_args
        and tool_args[0]
        in {
            "service",
            "serve",
            "auth",
            "api",
            "upgrade",
            "update",
            "uninstall",
            "debug",
            "mcp",
            "plugin",
            "models",
            "stats",
            "session",
            "reload",
            "pair",
            "acp",
        }
    ) or any(arg.split("=", 1)[0] in {"--server", "--standalone"} for arg in tool_args)
    network_server = opencode_entrypoint and not passthrough
    if server_mode and passthrough:
        reporter.fail("--server cannot forward service commands, --server, or --standalone.")
        raise typer.Exit(1)
    if network_server and server_username != "opencode":
        reporter.fail("OpenCode V2 requires --server-username opencode.")
        raise typer.Exit(1)
    if attach is not None and not network_server:
        reporter.fail("--attach/--no-attach requires a local OpenCode TUI.")
        raise typer.Exit(1)
    if debug and opencode_entrypoint:
        tool_args = ["--print-logs", "--log-level", "DEBUG", *tool_args]
    try:
        existing = (
            engine_ops.find_running(selected_engine, cwd, service=True)
            if network_server and attach is not False
            else None
        )
        if existing:
            port = engine_ops.published_port(selected_engine, existing, server.CONTAINER_PORT)
            if server_port is not None and server_port != port:
                raise CliError(
                    f"Existing server uses port {port}, not {server_port}; "
                    "use --no-attach for a new server."
                )
            reporter.note(
                f"Attaching to server - "
                f"{', '.join(server.urls(server.host_ips(host_platform), port))}"
            )
            if server_mode:
                raise typer.Exit(0)
            exec_argv = build_exec_argv(
                engine=selected_engine,
                name=existing,
                command="/usr/local/bin/opencode-launch",
                tool_args=tool_args,
                tty_args=[
                    "-w",
                    str(target_workdir),
                    "-e",
                    "AI_CONTAINER_OPENCODE_ATTACH=true",
                    "-e",
                    f"AI_CONTAINER_OPENCODE_PORT={server.CONTAINER_PORT}",
                    "-e",
                    f"AI_CONTAINER_OPENCODE_COMMAND={resolved_entrypoint}",
                    *(["-e", f"OPENCODE_PASSWORD={server_password}"] if server_password else []),
                    *(
                        item
                        for name in ("TERM", "COLORTERM")
                        if (value := os.environ.get(name))
                        for item in ("-e", f"{name}={value}")
                    ),
                    *(engine_ops.tty_args(selected_engine) if interactive else ["-i"]),
                ],
            )
            if debug_runtime:
                reporter.step(f"Running: {_safe_command(exec_argv)}")
            raise typer.Exit(run(exec_argv, terminal_title=terminal_title))
        if attach is True:
            raise CliError(
                "No OpenCode server running for this directory; "
                "start one with `ai-container server`."
            )
        if network_server:
            server_port = server.port_for(server_port)
            server_password = server_password or server.configured_password(host_home)
        if pi_server:
            pi_port = server.port_for(server_port)
    except (ValueError, OSError, engine_ops.EngineProbeError, CliError) as exc:
        reporter.fail(str(exc))
        raise typer.Exit(1) from exc
    if shell and (running := engine_ops.find_running(selected_engine, cwd)):
        reporter.ok(f"Attaching to running {selected_engine.value} container: {running}")
        exec_argv = build_exec_argv(
            engine=selected_engine,
            name=running,
            command=resolved_entrypoint,
            tool_args=tool_args,
            tty_args=engine_ops.tty_args(selected_engine) if interactive else ["-i"],
        )
        if debug_runtime:
            reporter.step(f"Running: {shlex.join(exec_argv)}")
        raise typer.Exit(run(exec_argv, terminal_title=terminal_title))

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
        *engine_ops.label_args(cwd),
        "-e",
        f"HOME={CONTAINER_HOME}",
        *(
            item
            for name in ("TERM", "COLORTERM")
            if (env_value := os.environ.get(name))
            for item in ("-e", f"{name}={env_value}")
        ),
        # Private state per container: keeps OpenCode's service.json out of the shared host mount.
        "-e",
        f"XDG_STATE_HOME={CONTAINER_HOME / '.local/state/ai-container' / container_name}",
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
    if terminal_session and HOST_TERMINFO.is_dir() and CONTAINER_TERMINFO not in mounted_targets:
        args.extend(
            [
                f"--mount=type=bind,source={HOST_TERMINFO},target={CONTAINER_TERMINFO},readonly",
                "-e",
                f"TERMINFO_DIRS={CONTAINER_TERMINFO}:",
            ]
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
    for name, command in launcher_config.export_vars.items():
        if name in disabled_envs or name in cli_envs:
            reporter.debug_fail(f"{name} export skipped (disabled or set by --extra-env)")
        elif (exported := _run_env_command(command)) is None:
            reporter.debug_fail(f"{name} skipped (command failed or printed nothing)")
        else:
            reporter.debug_ok(f"Setting {name} environment variable from command")
            env_entries.pop(name, None)
            args.extend(["-e", f"{name}={exported}"])
    for entry in env_entries.values():
        _apply_env(args, entry, reporter)
    for name in defaults.PROVIDER_KEY_ENVS:
        if name in disabled_envs:
            reporter.debug_fail(f"{name} disabled")
        elif name in env_entries or name in launcher_config.export_vars:
            continue
        elif os.environ.get(name):
            reporter.debug_ok(f"Forwarding {name} environment variable")
            args.extend(["-e", name])
        else:
            reporter.debug_fail(f"{name} not set")

    run_entrypoint = resolved_entrypoint
    if pi_server and pi_port is not None:
        pi_cmd = shlex.join([DEFAULT_PI_ENTRYPOINT, "--mode", "rpc", *tool_args])
        listen = f"TCP-LISTEN:{server.CONTAINER_PORT},reuseaddr,fork"
        args.extend(
            [
                "-d",
                "--label",
                f"{server.PI_SERVICE_LABEL}=true",
                "-p",
                f"0.0.0.0:{pi_port}:{server.CONTAINER_PORT}",
            ]
        )
        reporter.note(
            "Starting pi RPC server - "
            f"{', '.join(server.urls(server.host_ips(host_platform), pi_port))}"
        )
        tool_args = ["-c", f"exec {shlex.join(['/usr/bin/socat', listen, f'SYSTEM:{pi_cmd}'])}"]
        run_entrypoint = "/bin/sh"

    if network_server and server_port is not None:
        server_config = server.configure(
            port=server_port,
            username=server_username,
            password=server_password,
            tool_args=tool_args if server_mode else [],
            host_platform=host_platform,
        )
        reporter.note(
            f"{'Starting server' if server_mode else 'Starting server + TUI'} - "
            f"{server_config.username}:{server_config.password}@{', '.join(server_config.urls)}"
        )
        args.extend(["--label", f"{server.SERVICE_LABEL}=true", *server_config.args[1:]])
        if server_mode:
            args.append("-d")
            tool_args = server_config.tool_args
        else:
            args.extend(
                [
                    "-e",
                    f"AI_CONTAINER_OPENCODE_PORT={server.CONTAINER_PORT}",
                    "-e",
                    f"AI_CONTAINER_OPENCODE_COMMAND={resolved_entrypoint}",
                ]
            )
    if not server_mode and interactive:
        args.extend(engine_ops.tty_args(selected_engine))
    elif not server_mode:
        args.append("-i")
        reporter.debug_detail("\u25cb No TTY detected; running without -t")

    for extra in extra_network_args:
        reporter.debug_ok(f"Adding network arg: {extra}")
    args.extend(engine_ops.network_args(selected_engine, extra_network_args))
    args.extend(engine_ops.oci_runtime_args(selected_engine, microvm=microvm))

    engine_debug_args: list[str] = []
    if debug_runtime:
        engine_debug_args = engine_ops.debug_args(selected_engine)

    engine_ops.announce(
        selected_engine,
        container_name,
        reporter=reporter,
        workspace=active_workspace.name if active_workspace else None,
    )
    if debug or resolved_entrypoint not in BUNDLED_ASSISTANT_ENTRYPOINTS:
        reporter.step(f"Using entrypoint: {resolved_entrypoint}")
    if tool_args:
        reporter.step(f"Passing params: {' '.join(tool_args)}")

    if forwarding.needs_relay_chmod:
        spawn_relay_chmod_fix(selected_engine, container_name)

    argv = build_argv(
        engine=selected_engine,
        engine_debug_args=engine_debug_args,
        entrypoint="/usr/local/bin/opencode-launch"
        if network_server and not server_mode
        else run_entrypoint,
        args=args,
        image=image,
        tool_args=tool_args,
    )
    if debug_runtime:
        reporter.step(f"Running: {_safe_command(argv)}")
    raise typer.Exit(run(argv, terminal_title=terminal_title))


def _list_containers(engine: Engine, *, show_secrets: bool) -> None:
    """Print one line per running container: name, workdir, command, port, password."""
    if engine is Engine.CONTAINER:
        typer.echo(
            "Listing is not supported on the Apple `container` engine; use podman or docker."
        )
        return
    infos = engine_ops.list_running(engine)
    if not infos:
        typer.echo("No running ai-container containers.")
        return
    for info in infos:
        port = "-" if info.port is None else str(info.port)
        password = "-" if info.password is None else ("****" if not show_secrets else info.password)
        typer.echo(
            f"{info.name} - {info.workdir or '-'} - {info.command or '-'} - {port} - {password}"
        )


def _safe_command(argv: list[str]) -> str:
    return shlex.join(
        [
            "OPENCODE_PASSWORD=<redacted>" if arg.startswith("OPENCODE_PASSWORD=") else arg
            for arg in argv
        ]
    )


def _resolve_entrypoint(
    *,
    entrypoint: str | None,
    claude: bool,
    opencode: bool,
    codex: bool,
    copilot: bool,
    pi: bool,
    shell: bool,
    init_mode: bool,
    server: bool,
    default_agent: str,
) -> str:
    selected = [
        flag
        for flag, enabled in (
            ("--claude", claude),
            ("--opencode", opencode),
            ("--codex", codex),
            ("--copilot", copilot),
            ("--pi", pi),
        )
        if enabled
    ]
    if len(selected) > 1:
        raise CliError(f"Cannot combine assistant shortcuts: {', '.join(selected)}.")
    if server and (claude or codex or copilot or entrypoint is not None):
        raise CliError("--server supports only the bundled OpenCode or pi entrypoint.")
    if init_mode:
        if selected or entrypoint is not None or shell or server:
            raise CliError(
                "--init cannot be combined with an assistant shortcut, --entrypoint, --shell "
                "or --server."
            )
        return INIT_ENTRYPOINT
    if shell:
        if selected or entrypoint is not None or server:
            raise CliError(
                "--shell cannot be combined with an assistant shortcut, --entrypoint or --server."
            )
        return SHELL_ENTRYPOINT
    if entrypoint is not None:
        return entrypoint
    if selected:
        return defaults.ASSISTANT_ENTRYPOINTS[selected[0].removeprefix("--")]
    if server and default_agent not in {"opencode", "pi"}:
        raise CliError("--server supports only OpenCode and pi; use --pi or change default_agent.")
    return defaults.ASSISTANT_ENTRYPOINTS[default_agent]


def _initialize_assistant_paths(host_home: Path, reporter: Reporter) -> None:
    reporter.step("Preparing host assistant state")
    try:
        for relative in defaults.ASSISTANT_DIRECTORY_MOUNTS:
            path = host_home / relative
            if path.exists():
                reporter.detail(f"Already exists, skipping: {path}")
            else:
                path.mkdir(parents=True)
                reporter.ok(f"Created directory: {path}")
        for relative in defaults.ASSISTANT_FILE_MOUNTS:
            path = host_home / relative
            if path.exists():
                reporter.detail(f"Already exists, skipping: {path}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
                reporter.ok(f"Created file: {path}")
    except OSError as exc:
        raise CliError(f"Could not initialize host assistant state: {exc}") from exc


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


def _run_env_command(command: str) -> str | None:
    """Run ``command`` on the host (no shell); return stripped stdout, or None on any failure."""
    try:
        result = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=10)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


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
