from __future__ import annotations

import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_container import __version__, git_utils
from ai_container import cli as cli_mod

runner = CliRunner()


@pytest.fixture
def captured_run(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Replace the final `podman run ...` invocation with a spy."""
    calls: list[list[str]] = []

    def fake_run(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    monkeypatch.setattr(cli_mod, "run", fake_run)
    monkeypatch.setattr(cli_mod, "spawn_relay_chmod_fix", lambda *a, **k: None)
    return calls


def test_help_shows_dash_dash_usage() -> None:
    result = runner.invoke(cli_mod.app, ["--help"])
    assert result.exit_code == 0
    assert "tool_args" in result.output


def test_help_output_has_no_box_drawing_borders() -> None:
    result = runner.invoke(cli_mod.app, ["--help"])
    assert result.exit_code == 0
    assert not any(char in result.output for char in "\u256d\u2570\u2502\u2500")


@pytest.mark.parametrize("flag", ["--version", "-v"])
def test_version_prints_and_exits_before_any_engine_work(flag: str) -> None:
    result = runner.invoke(cli_mod.app, [flag])
    assert result.exit_code == 0
    assert "ai-container" in result.output
    assert __version__ in result.output


def test_unknown_runtime_errors(isolated_home: Path, workdir: Path, fake_engine_path: Path) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "docker"])
    assert result.exit_code == 1
    assert "Unknown --runtime" in result.output


def test_missing_engine_binary_errors(
    isolated_home: Path, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(workdir))  # no podman/container anywhere
    result = runner.invoke(cli_mod.app, ["--runtime", "podman"])
    assert result.exit_code == 1
    assert "not found on $PATH" in result.output


def test_refuses_to_run_from_home(
    isolated_home: Path, fake_engine_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(isolated_home)
    result = runner.invoke(cli_mod.app, ["--runtime", "podman"])
    assert result.exit_code == 1
    assert "your entire $HOME" in result.output


def test_claude_and_opencode_together_is_an_error(
    isolated_home: Path, workdir: Path, fake_engine_path: Path
) -> None:
    result = runner.invoke(cli_mod.app, ["--claude", "--opencode"])
    assert result.exit_code == 1
    assert "Cannot use --claude and --opencode together" in result.output


def test_happy_path_builds_expected_argv(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--", "--resume"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert argv[0] == "podman"
    assert argv[-1] == "--resume"
    assert "--rm" in argv
    assert "--name" in argv
    assert "--network=pasta" in argv
    assert "HOME=/home/coder" in argv


def test_microvm_adds_krun_runtime_and_passt_annotation(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--microvm"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert "--runtime" in argv
    assert argv[argv.index("--runtime") + 1] == "krun"
    assert "--annotation" in argv
    assert argv[argv.index("--annotation") + 1] == "krun.use_passt=1"


def test_microvm_rejected_on_container_engine(
    isolated_home: Path, workdir: Path, fake_engine_path: Path
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "container", "--microvm"])
    assert result.exit_code == 1
    assert "--microvm is only supported with the podman engine" in result.output


def test_add_host_flag_adds_flag_on_podman(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    result = runner.invoke(
        cli_mod.app, ["--runtime", "podman", "--add-host", "foo.example.com:1.2.3.4"]
    )
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert "--add-host=foo.example.com:1.2.3.4" in argv


def test_add_host_rejected_on_container_engine(
    isolated_home: Path, workdir: Path, fake_engine_path: Path
) -> None:
    result = runner.invoke(
        cli_mod.app, ["--runtime", "container", "--add-host", "foo.example.com:1.2.3.4"]
    )
    assert result.exit_code == 1
    assert "--add-host is only supported with the podman engine" in result.output


def test_add_host_rejects_malformed_entry(
    isolated_home: Path, workdir: Path, fake_engine_path: Path
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--add-host", "no-colon-here"])
    assert result.exit_code == 1
    assert "Invalid --add-host entry" in result.output


def test_add_host_from_config_file_applied_on_podman(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    config_dir = isolated_home / ".config"
    config_dir.mkdir()
    (config_dir / "ai-container.toml").write_text('add_hosts = ["cfg.example.com:9.9.9.9"]\n')
    result = runner.invoke(cli_mod.app, ["--runtime", "podman"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert "--add-host=cfg.example.com:9.9.9.9" in argv


def test_add_host_from_config_file_silently_skipped_on_container(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    config_dir = isolated_home / ".config"
    config_dir.mkdir()
    (config_dir / "ai-container.toml").write_text('add_hosts = ["cfg.example.com:9.9.9.9"]\n')
    result = runner.invoke(cli_mod.app, ["--runtime", "container"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert not any("cfg.example.com" in arg for arg in argv)


def test_add_host_config_and_cli_combine_and_dedupe(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    config_dir = isolated_home / ".config"
    config_dir.mkdir()
    (config_dir / "ai-container.toml").write_text(
        'add_hosts = ["cfg.example.com:9.9.9.9", "shared.example.com:5.5.5.5"]\n'
    )
    result = runner.invoke(
        cli_mod.app,
        [
            "--runtime",
            "podman",
            "--add-host",
            "shared.example.com:5.5.5.5",
            "--add-host",
            "cli.example.com:8.8.8.8",
        ],
    )
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert "--add-host=cfg.example.com:9.9.9.9" in argv
    assert "--add-host=cli.example.com:8.8.8.8" in argv
    assert argv.count("--add-host=shared.example.com:5.5.5.5") == 1


def test_add_host_from_malformed_config_file_errors(
    isolated_home: Path, workdir: Path, fake_engine_path: Path
) -> None:
    config_dir = isolated_home / ".config"
    config_dir.mkdir()
    (config_dir / "ai-container.toml").write_text("this is not [valid toml\n")
    result = runner.invoke(cli_mod.app, ["--runtime", "podman"])
    assert result.exit_code == 1
    assert "Failed to parse" in result.output


def test_env_from_config_and_cli_combine_and_dedupe(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = isolated_home / ".config"
    config_dir.mkdir()
    (config_dir / "ai-container.toml").write_text('extra_envs = ["CONFIG_ENV", "SHARED_ENV"]\n')
    monkeypatch.setenv("CONFIG_ENV", "from-config")
    monkeypatch.setenv("SHARED_ENV", "shared")
    monkeypatch.setenv("CLI_ENV", "from-cli")
    result = runner.invoke(
        cli_mod.app,
        ["--runtime", "podman", "--extra-env", "SHARED_ENV", "--extra-env", "CLI_ENV"],
    )
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert "CONFIG_ENV=from-config" in argv
    assert "CLI_ENV=from-cli" in argv
    assert argv.count("SHARED_ENV=shared") == 1


def test_env_skips_unset_host_variable(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_ENV", raising=False)
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--extra-env", "MISSING_ENV"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert not any(arg.startswith("MISSING_ENV=") for arg in argv)


def test_explicit_workspace_mounts_dirs_and_prints_banner(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    tmp_path: Path,
) -> None:
    ws_dir = tmp_path / "ws-repo"
    ws_dir.mkdir()
    config_dir = isolated_home / ".config"
    config_dir.mkdir()
    (config_dir / "ai-container.toml").write_text(
        f'[[workspace]]\nname = "frontend"\ndirs = ["{ws_dir}"]\n'
    )
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--workspace", "frontend"])
    assert result.exit_code == 0, result.output
    (line,) = [ln for ln in result.output.splitlines() if "Workspace: frontend" in ln]
    assert "podman container: ai-" in line
    (argv,) = captured_run
    assert any(str(ws_dir) in flag for flag in argv)


def test_unknown_workspace_name_errors(
    isolated_home: Path, workdir: Path, fake_engine_path: Path
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--workspace", "nonexistent"])
    assert result.exit_code == 1
    assert "Unknown workspace" in result.output


def test_auto_workspaces_detects_from_cwd(
    isolated_home: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws_dir = isolated_home.parent / "ws-repo"
    ws_dir.mkdir()
    monkeypatch.chdir(ws_dir)
    config_dir = isolated_home / ".config"
    config_dir.mkdir()
    (config_dir / "ai-container.toml").write_text(
        f'auto_workspaces = true\n[[workspace]]\nname = "frontend"\ndirs = ["{ws_dir}"]\n'
    )
    result = runner.invoke(cli_mod.app, ["--runtime", "podman"])
    assert result.exit_code == 0, result.output
    assert "Workspace: frontend" in result.output


def test_no_workspace_omits_banner_line(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman"])
    assert result.exit_code == 0, result.output
    assert "Workspace:" not in result.output


def test_short_unknown_option_forwarded_without_dash_dash(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "-c"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert argv[-1] == "-c"


def test_long_unknown_option_forwarded_without_dash_dash(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--claude", "--resume"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert argv[-1] == "--resume"
    assert "/home/coder/.local/bin/claude" in argv


def test_own_flag_recognized_regardless_of_position_relative_to_unknown_ones(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "-c", "--entrypoint", "/bin/bash"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert "/bin/bash" in argv
    assert argv[-1] == "-c"


def test_dash_dash_still_forwards_a_colliding_flag_name_literally(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    """`--debug` collides with our own flag, so forwarding it to the
    entrypoint (rather than turning on our debug output) requires `--`.
    """
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--claude", "--", "--debug"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert argv[-1] == "--debug"
    assert "--log-level=debug" not in argv  # our own debug mode was NOT triggered


def test_default_entrypoint_is_opencode(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert "/home/coder/.opencode/bin/opencode" in argv


def test_claude_flag_switches_entrypoint(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    runner.invoke(cli_mod.app, ["--runtime", "podman", "--claude"])
    (argv,) = captured_run
    assert "/home/coder/.local/bin/claude" in argv


def test_explicit_entrypoint_wins_over_claude(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    runner.invoke(cli_mod.app, ["--runtime", "podman", "--claude", "--entrypoint", "/bin/bash"])
    (argv,) = captured_run
    assert "/bin/bash" in argv
    assert "/home/coder/.local/bin/claude" not in argv


def test_existing_credential_directory_gets_mounted(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    (isolated_home / ".claude").mkdir()
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert f"{isolated_home}/.claude:/home/coder/.claude" in argv


def test_missing_credential_directory_is_not_mounted(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert not any("/.claude" in flag for flag in argv)


def test_mount_extra_is_deduplicated(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    tmp_path: Path,
) -> None:
    extra = tmp_path / "extra"
    extra.mkdir()
    runner.invoke(
        cli_mod.app,
        ["--runtime", "podman", "--extra-mount", str(extra), "--extra-mount", str(extra)],
    )
    (argv,) = captured_run
    mount_flags = [flag for flag in argv if str(extra) in flag]
    assert len(mount_flags) == 1


def test_mount_extra_short_flag(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    tmp_path: Path,
) -> None:
    extra = tmp_path / "extra"
    extra.mkdir()
    runner.invoke(cli_mod.app, ["--runtime", "podman", "-m", str(extra)])
    (argv,) = captured_run
    assert any(str(extra) in flag for flag in argv)


def _mount_flags_targeting(argv: list[str], target: str) -> list[str]:
    """Flags that actually declare a mount to ``target`` (``-v ...`` or ``--mount=...``),
    as opposed to e.g. an unrelated ``-w <target>`` argument."""
    return [
        flag
        for flag in argv
        if f"target={target}" in flag or (len(parts := flag.split(":")) > 1 and parts[1] == target)
    ]


def test_default_mount_skipped_when_workdir_target_collides(
    isolated_home: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = isolated_home / "bin"
    bin_dir.mkdir()
    monkeypatch.chdir(bin_dir)
    result = runner.invoke(cli_mod.app, ["--runtime", "podman"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    bin_flags = _mount_flags_targeting(argv, "/home/coder/bin")
    assert len(bin_flags) == 1
    assert "type=bind" in bin_flags[0]  # the rw workdir mount, not the ro default mount


def test_default_mount_skipped_when_extra_mount_target_collides(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
) -> None:
    bin_dir = isolated_home / "bin"
    bin_dir.mkdir()
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--extra-mount", str(bin_dir)])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    bin_flags = _mount_flags_targeting(argv, "/home/coder/bin")
    assert len(bin_flags) == 1
    assert "type=bind" in bin_flags[0]  # the rw extra mount, not the ro default mount


def test_web_mode_sets_detach_and_port(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--web", "--web-port", "5050"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert "-d" in argv
    assert "5050:5050" in argv
    assert "web" in argv
    assert "--hostname" in argv


def test_debug_flag_prepends_opencode_debug_args(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    runner.invoke(cli_mod.app, ["--runtime", "podman", "--debug", "--", "--resume"])
    (argv,) = captured_run
    tail = argv[argv.index("localhost/ai") + 1 :]
    assert tail == ["--print-logs", "--log-level", "DEBUG", "--resume"]
    assert "--log-level=debug" not in argv  # --debug alone doesn't turn on engine debug output


def test_debug_podman_flag_adds_engine_debug_output_only(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    runner.invoke(cli_mod.app, ["--runtime", "podman", "--debug-podman", "--", "--resume"])
    (argv,) = captured_run
    assert argv[1] == "--log-level=debug"
    tail = argv[argv.index("localhost/ai") + 1 :]
    assert tail == ["--resume"]  # opencode's own debug args are NOT added


def test_debug_and_debug_podman_are_independent_and_combinable(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    runner.invoke(
        cli_mod.app, ["--runtime", "podman", "--debug", "--debug-podman", "--", "--resume"]
    )
    (argv,) = captured_run
    assert argv[1] == "--log-level=debug"
    tail = argv[argv.index("localhost/ai") + 1 :]
    assert tail == ["--print-logs", "--log-level", "DEBUG", "--resume"]


def test_no_worktree_mount_disables_autodetection(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        git_utils, "detect_worktree_parent", lambda _cwd: Path("/should/not/be/used")
    )
    runner.invoke(cli_mod.app, ["--runtime", "podman", "--no-worktree-mount"])
    (argv,) = captured_run
    assert not any("should/not/be/used" in flag for flag in argv)


def test_gcloud_credentials_mounted_when_present(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GCLOUD_PROJECT", "some-project")
    gcloud_dir = isolated_home / ".config/gcloud"
    gcloud_dir.mkdir(parents=True)
    (gcloud_dir / "application_default_credentials.json").write_text("{}")
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert any("application_default_credentials.json" in flag for flag in argv)
    assert "GOOGLE_CLOUD_PROJECT=some-project" in argv
    assert "GOOGLE_VERTEX_PROJECT=some-project" in argv
    assert "GCLOUD_PROJECT=some-project" in argv


def test_gcloud_project_env_vars_omitted_when_unset(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    monkeypatch.delenv("ANTHROPIC_VERTEX_PROJECT_ID", raising=False)
    gcloud_dir = isolated_home / ".config/gcloud"
    gcloud_dir.mkdir(parents=True)
    (gcloud_dir / "application_default_credentials.json").write_text("{}")
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert not any(flag.startswith("GOOGLE_CLOUD_PROJECT=") for flag in argv)
    assert not any(flag.startswith("GOOGLE_VERTEX_PROJECT=") for flag in argv)
    assert not any(flag.startswith("VERTEXAI_PROJECT=") for flag in argv)
    assert not any(flag.startswith("GCLOUD_PROJECT=") for flag in argv)


def test_extra_mount_path_that_does_not_exist_is_skipped(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--extra-mount", "/does/not/exist"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert not any("/does/not/exist" in flag for flag in argv)


def test_bugzilla_and_redmine_keys_forwarded(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BUGZILLA_API_KEY", "bz-secret")
    monkeypatch.setenv("REDMINE_API_KEY", "rm-secret")
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert "BUGZILLA_API_KEY=bz-secret" in argv
    assert "REDMINE_API_KEY=rm-secret" in argv


def test_pushover_keys_forwarded(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUSHOVER_USER", "po-user")
    monkeypatch.setenv("PUSHOVER_TOKEN", "po-token")
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert "PUSHOVER_USER=po-user" in argv
    assert "PUSHOVER_TOKEN=po-token" in argv


def test_debug_does_not_prepend_opencode_flags_for_other_entrypoints(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    runner.invoke(
        cli_mod.app,
        ["--runtime", "podman", "--debug", "--entrypoint", "/bin/bash", "--", "-lc", "echo hi"],
    )
    (argv,) = captured_run
    tail = argv[argv.index("localhost/ai") + 1 :]
    assert tail == ["-lc", "echo hi"]


def test_no_tty_runs_with_dash_i_only(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert "-i" in argv
    assert "-it" not in argv


def test_worktree_is_auto_mounted(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parent = tmp_path / "main-checkout"
    parent.mkdir()
    monkeypatch.setattr(git_utils, "detect_worktree_parent", lambda _cwd: parent)
    result = runner.invoke(cli_mod.app, ["--runtime", "podman"])
    assert "Detected git worktree" in result.output
    (argv,) = captured_run
    assert any(str(parent) in flag for flag in argv)


def _write_config(home: Path, text: str) -> None:
    (home / ".config").mkdir(exist_ok=True)
    (home / ".config" / "ai-container.toml").write_text(text)


@pytest.fixture
def agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A real listening AF_UNIX socket exported as $SSH_AUTH_SOCK (short path: sun_path limit)."""
    sock_path = Path(tempfile.mkdtemp()) / "agent.sock"
    with socket.socket(socket.AF_UNIX) as srv:
        srv.bind(str(sock_path))
        monkeypatch.setenv("SSH_AUTH_SOCK", str(sock_path))
        yield sock_path
    sock_path.unlink(missing_ok=True)
    sock_path.parent.rmdir()


@pytest.mark.parametrize("runtime", ["podman", "container"])
def test_ssh_agent_forwarded_by_default(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    agent: Path,
    runtime: str,
) -> None:
    runner.invoke(cli_mod.app, ["--runtime", runtime])
    (argv,) = captured_run
    assert ("--ssh" in argv) if runtime == "container" else any(str(agent) in a for a in argv)


@pytest.mark.parametrize("runtime", ["podman", "container"])
def test_ssh_agent_disabled_by_config_and_flag_overrides(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    agent: Path,
    runtime: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relay: list[str] = []
    monkeypatch.setattr(cli_mod, "spawn_relay_chmod_fix", lambda *a, **k: relay.append("x"))
    _write_config(isolated_home, "ssh_agent = false\n")
    runner.invoke(cli_mod.app, ["--runtime", runtime])
    (argv,) = captured_run
    assert "--ssh" not in argv
    assert not any(str(agent) in a or a.startswith("SSH_AUTH_SOCK=") for a in argv)
    assert not relay
    captured_run.clear()
    runner.invoke(cli_mod.app, ["--runtime", runtime, "--ssh-agent"])
    (argv,) = captured_run
    assert ("--ssh" in argv) if runtime == "container" else any(str(agent) in a for a in argv)
    assert bool(relay) == (runtime == "container")


@pytest.mark.parametrize("runtime", ["podman", "container"])
def test_no_ssh_agent_flag_overrides_config_true(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    agent: Path,
    runtime: str,
) -> None:
    runner.invoke(cli_mod.app, ["--runtime", runtime, "--no-ssh-agent"])
    (argv,) = captured_run
    assert "--ssh" not in argv
    assert not any(str(agent) in a for a in argv)


def test_disable_mounts_from_config_and_flag(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    for d in (".aws", ".kube", ".npm"):
        (isolated_home / d).mkdir()
    _write_config(isolated_home, 'disable_mounts = ["~/.aws"]\n')
    runner.invoke(
        cli_mod.app, ["--runtime", "podman", "--disable-mount", str(isolated_home / ".kube")]
    )
    (argv,) = captured_run
    assert not _mount_flags_targeting(argv, "/home/coder/.aws")
    assert not _mount_flags_targeting(argv, "/home/coder/.kube")
    assert any(a.startswith(f"{isolated_home}/.npm:") for a in argv)


def test_disable_mount_rejects_relative_path(
    isolated_home: Path, workdir: Path, fake_engine_path: Path
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--disable-mount", "rel/dir"])
    assert result.exit_code == 1
    assert "absolute" in result.output


def test_disable_mounts_parent_path_disables_gcloud(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    gcloud_dir = isolated_home / ".config/gcloud"
    gcloud_dir.mkdir(parents=True)
    (gcloud_dir / "application_default_credentials.json").write_text("{}")
    _write_config(isolated_home, 'disable_mounts = ["~/.config"]\n')
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert not any("application_default_credentials.json" in a for a in argv)
    assert not any(a.startswith("GOOGLE_APPLICATION_CREDENTIALS=") for a in argv)


@pytest.mark.parametrize("via", ["config", "cli"])
def test_extra_mount_wins_over_disabled_parent(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    via: str,
) -> None:
    for d in ("gh", "osc"):
        (isolated_home / ".config" / d).mkdir(parents=True)
    gh = isolated_home / ".config/gh"
    if via == "config":
        _write_config(isolated_home, f'disable_mounts = ["~/.config"]\nextra_mounts = ["{gh}"]\n')
        cli_args: list[str] = []
    else:
        cli_args = ["--disable-mount", str(isolated_home / ".config"), "--extra-mount", str(gh)]
    runner.invoke(cli_mod.app, ["--runtime", "podman", *cli_args])
    (argv,) = captured_run
    (gh_flag,) = _mount_flags_targeting(argv, "/home/coder/.config/gh")
    assert "type=bind" in gh_flag
    assert not _mount_flags_targeting(argv, "/home/coder/.config/osc")


def test_config_extra_mounts_merge_with_cli_and_relative_uses_cwd(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    tmp_path: Path,
) -> None:
    (workdir / "rel").mkdir()
    cli_dir = tmp_path / "cli-dir"
    cli_dir.mkdir()
    _write_config(isolated_home, 'extra_mounts = ["rel"]\n')
    runner.invoke(cli_mod.app, ["--runtime", "podman", "--extra-mount", str(cli_dir)])
    (argv,) = captured_run
    assert any(f"source={workdir / 'rel'}," in a for a in argv)
    assert any(f"source={cli_dir}," in a for a in argv)


def test_disable_envs_filters_builtins_and_extras_restore(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUSHOVER_USER", "u")
    monkeypatch.setenv("PUSHOVER_TOKEN", "t")
    monkeypatch.setenv("BUGZILLA_API_KEY", "b")
    _write_config(
        isolated_home,
        'disable_envs = ["PUSHOVER_USER", "PUSHOVER_TOKEN"]\nextra_envs = ["PUSHOVER_TOKEN"]\n',
    )
    runner.invoke(cli_mod.app, ["--runtime", "podman", "--disable-env", "BUGZILLA_API_KEY"])
    (argv,) = captured_run
    assert "PUSHOVER_USER=u" not in argv
    assert "BUGZILLA_API_KEY=b" not in argv
    assert argv.count("PUSHOVER_TOKEN=t") == 1


def test_extra_env_cli_restores_disabled_builtin(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDMINE_API_KEY", "r")
    runner.invoke(
        cli_mod.app,
        [
            "--runtime",
            "podman",
            "--disable-env",
            "REDMINE_API_KEY",
            "--extra-env",
            "REDMINE_API_KEY",
        ],
    )
    (argv,) = captured_run
    assert argv.count("REDMINE_API_KEY=r") == 1


def test_config_old_env_key_errors(
    isolated_home: Path, workdir: Path, fake_engine_path: Path
) -> None:
    _write_config(isolated_home, 'env = ["X"]\n')
    result = runner.invoke(cli_mod.app, ["--runtime", "podman"])
    assert result.exit_code == 1
    assert "extra_envs" in result.output


@pytest.mark.parametrize("old", ["--env", "--mount-extra"])
def test_removed_flags_are_forwarded_to_the_assistant(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    old: str,
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", old])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert argv[-1] == old
