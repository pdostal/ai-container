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
import sys
from pathlib import Path
from typing import Annotated

import typer

from . import __version__, git_utils, mounts, paths, rich_patches, selinux, ssh_agent, web
from . import engine as engine_ops
from .console import Reporter
from .models import Engine
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
DEFAULT_OPENCODE_ENTRYPOINT = str(CONTAINER_HOME / ".opencode/bin/opencode")
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
    mount_extra: Annotated[
        list[Path] | None,
        typer.Option(
            "--mount-extra", help="Extra host directory to bind-mount read-write. Repeatable."
        ),
    ] = None,
    worktree_mount: Annotated[
        bool,
        typer.Option(
            "--worktree-mount/--no-worktree-mount",
            help="Auto rw-mount a git worktree's parent checkout.",
        ),
    ] = True,
    debug: Annotated[
        bool, typer.Option("--debug", help="Verbose launcher + assistant debug output.")
    ] = False,
    debug_podman: Annotated[
        bool,
        typer.Option(
            "--debug-podman", help="Verbose podman/container engine debug output (very noisy)."
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
            help="Container engine: podman or container. Defaults to "
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
    extra_mount_paths = list(mount_extra or [])

    try:
        resolved_entrypoint = _resolve_entrypoint(
            entrypoint=entrypoint, claude=claude, opencode=opencode
        )
        selected_engine = engine_ops.resolve_engine(
            explicit=runtime,
            env_runtime=os.environ.get("AI_CONTAINER_RUNTIME"),
            host_platform=host_platform,
        )
        engine_ops.ensure_available(selected_engine)
        if microvm and selected_engine is Engine.CONTAINER:
            raise CliError(
                "--microvm is only supported with the podman engine "
                "(Apple's container tool already runs each container in its own VM)."
            )
        try:
            cwd = Path.cwd()
        except (FileNotFoundError, OSError) as exc:
            raise CliError("Current directory is gone; refusing to bind-mount workdir.") from exc
        target_workdir = paths.resolve_target_workdir(
            cwd, host_home=host_home, container_home=CONTAINER_HOME
        )
    except engine_ops.UnknownEngineError as exc:
        reporter.fail(
            f"Unknown --runtime/AI_CONTAINER_RUNTIME value: {exc} "
            "(expected 'podman' or 'container')"
        )
        raise typer.Exit(1) from exc
    except engine_ops.EngineNotFoundError as exc:
        reporter.fail(f"Selected runtime '{exc}' not found on $PATH")
        raise typer.Exit(1) from exc
    except paths.HomeDirectoryWorkdirError as exc:
        reporter.fail(f"Refusing to run: current directory is your entire $HOME ({exc})")
        reporter.detail("Run this from a project subdirectory instead.")
        raise typer.Exit(1) from exc
    except CliError as exc:
        reporter.fail(str(exc))
        raise typer.Exit(1) from exc

    image = engine_ops.image_name(selected_engine)
    selinux_status = selinux.detect(host_platform=host_platform, reporter=reporter)
    container_name = random_container_name()

    if worktree_mount:
        worktree_parent = git_utils.detect_worktree_parent(cwd)
        if worktree_parent is not None:
            extra_mount_paths.append(worktree_parent)
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
        f"{selinux.bind_suffix(selinux_status.enabled)}",
    ]
    args.extend(engine_ops.identity_args(selected_engine))
    reporter.debug_ok(f"Mounting working directory (bind-mount, rw): {cwd} \u2192 {target_workdir}")

    _apply_extra_mounts(
        args,
        extra_mount_paths,
        mounted_targets={target_workdir},
        host_home=host_home,
        selinux_enabled=selinux_status.enabled,
        reporter=reporter,
    )
    _apply_gcloud(
        args, host_home=host_home, selinux_enabled=selinux_status.enabled, reporter=reporter
    )
    for spec in mounts.default_mounts(host_home, CONTAINER_HOME, host_platform=host_platform):
        mounts.apply_mount(args, spec, selinux_enabled=selinux_status.enabled, reporter=reporter)

    args.extend(["-e", "OPENCODE_DISABLE_LSP_DOWNLOAD=true"])
    reporter.debug_detail("Setting OPENCODE_DISABLE_LSP_DOWNLOAD=true")

    forwarding = ssh_agent.configure(
        engine=selected_engine,
        container_home=CONTAINER_HOME,
        selinux_enabled=selinux_status.enabled,
        reporter=reporter,
    )
    args.extend(forwarding.args)
    for key, value in forwarding.env.items():
        args.extend(["-e", f"{key}={value}"])

    _forward_env(args, "ANTHROPIC_VERTEX_PROJECT_ID", reporter)
    _forward_env(args, "BUGZILLA_API_KEY", reporter)
    _forward_env(args, "REDMINE_API_KEY", reporter)

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

    engine_ops.announce(selected_engine, container_name, reporter=reporter)
    reporter.step(f"Using entrypoint: {resolved_entrypoint}")
    reporter.step(f"Passing params: {' '.join(tool_args)}")
    reporter.blank()

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


def _apply_extra_mounts(
    args: list[str],
    extra_mount_paths: list[Path],
    *,
    mounted_targets: set[Path],
    host_home: Path,
    selinux_enabled: bool,
    reporter: Reporter,
) -> None:
    for raw_path in extra_mount_paths:
        if not raw_path.is_dir():
            reporter.debug_fail(f"Extra mount path not found, skipping: {raw_path}")
            continue
        resolved = raw_path.resolve()
        target = paths.map_to_container_path(
            resolved, host_home=host_home, container_home=CONTAINER_HOME
        )
        if target in mounted_targets:
            continue
        mounted_targets.add(target)
        reporter.debug_ok(f"Mounting extra directory (bind-mount, rw): {resolved} \u2192 {target}")
        suffix = selinux.bind_suffix(selinux_enabled)
        args.append(f"--mount=type=bind,source={resolved},target={target}{suffix}")


def _apply_gcloud(
    args: list[str], *, host_home: Path, selinux_enabled: bool, reporter: Reporter
) -> None:
    spec = mounts.gcloud_mount(host_home, CONTAINER_HOME)
    if not spec.exists():
        reporter.debug_fail(f"Google Cloud credentials not found: {spec.host}")
        return
    reporter.debug_ok(f"Mounting Google Cloud credentials (bind-mount, ro): {spec.host}")
    suffix = selinux.volume_ro_suffix(selinux_enabled)
    args.extend(["-v", f"{spec.host}:{spec.container}{suffix}"])
    project = os.environ.get("GCLOUD_PROJECT") or os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
    if not project:
        reporter.debug_fail("GCLOUD_PROJECT / ANTHROPIC_VERTEX_PROJECT_ID not set")
    for key, value in mounts.gcloud_env(spec.container, project).items():
        args.extend(["-e", f"{key}={value}"])
        reporter.debug_detail(f"Setting {key}={value}")


def _forward_env(args: list[str], name: str, reporter: Reporter) -> None:
    value = os.environ.get(name)
    if value:
        reporter.debug_ok(f"Forwarding {name} environment variable")
        args.extend(["-e", f"{name}={value}"])
    else:
        reporter.debug_fail(f"{name} not set")


def run_app() -> None:
    app()


if __name__ == "__main__":
    run_app()
