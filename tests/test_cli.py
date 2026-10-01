from __future__ import annotations

import os
import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_container import __version__, git_utils, selinux
from ai_container import cli as cli_mod
from ai_container import engine as engine_ops

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
    result = runner.invoke(cli_mod.app, ["--runtime", "nonsense"])
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


def _stub_rootless(monkeypatch: pytest.MonkeyPatch, value: bool) -> None:
    monkeypatch.setattr(engine_ops, "docker_is_rootless", lambda: value)


def test_docker_rootful_argv(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_rootless(monkeypatch, False)
    result = runner.invoke(cli_mod.app, ["--runtime", "docker", "--add-host", "a.example:1.2.3.4"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert argv[0] == "docker"
    assert argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert "--add-host=a.example:1.2.3.4" in argv
    assert "--network=pasta" not in argv
    assert "ai" in argv
    assert not any(arg.endswith(",z") or arg.endswith(":z") for arg in argv)


def test_docker_rootless_runs_as_mapped_root(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_rootless(monkeypatch, True)
    result = runner.invoke(cli_mod.app, ["--runtime", "docker"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert argv[argv.index("--user") + 1] == "0:0"


def test_docker_selinux_uses_label_disable_not_mount_suffix(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_rootless(monkeypatch, False)
    monkeypatch.setattr(selinux, "detect", lambda **_: selinux.SELinuxStatus(enabled=True))
    result = runner.invoke(cli_mod.app, ["--runtime", "docker"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert "label=disable" in argv
    assert not any(",z" in arg or ":z" in arg.lower() for arg in argv)


def test_docker_daemon_probe_failure_errors(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> bool:
        raise engine_ops.EngineProbeError("Cannot connect")

    monkeypatch.setattr(engine_ops, "docker_is_rootless", boom)
    result = runner.invoke(cli_mod.app, ["--runtime", "docker"])
    assert result.exit_code == 1
    assert "Could not query the docker daemon: Cannot connect" in result.output


def test_microvm_rejected_on_docker_engine(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_rootless(monkeypatch, False)
    result = runner.invoke(cli_mod.app, ["--runtime", "docker", "--microvm"])
    assert result.exit_code == 1
    assert "--microvm is only supported with the podman engine" in result.output


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


def test_no_tool_mounts_or_envs_without_config(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (isolated_home / ".config/gh").mkdir(parents=True)
    monkeypatch.setenv("BUGZILLA_API_KEY", "bz")
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert not any("/.config/gh" in a for a in argv)
    assert not any(a.startswith(("BUGZILLA_API_KEY=", "OPENCODE_")) for a in argv)


def _make_assistant_paths(home: Path) -> None:
    for d in (".claude", ".config/opencode", ".local/share/opencode"):
        (home / d).mkdir(parents=True)
    (home / ".claude.json").write_text("{}")


def test_assistant_mounts_are_automatic_and_read_write(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    _make_assistant_paths(isolated_home)
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    for rel in (".claude", ".claude.json", ".config/opencode", ".local/share/opencode"):
        assert f"{isolated_home}/{rel}:/home/coder/{rel}" in argv
    assert not _mount_flags_targeting(argv, "/home/coder/.cache/opencode")  # missing on host


def test_assistant_mounts_can_be_disabled_and_config_overrides(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    _make_assistant_paths(isolated_home)
    _write_config(
        isolated_home,
        'disable_mounts = ["~/.config"]\nextra_mounts = ["~/.claude:ro"]\n',
    )
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert f"{isolated_home}/.claude:/home/coder/.claude:ro" in argv
    assert f"{isolated_home}/.claude.json:/home/coder/.claude.json" in argv
    assert not _mount_flags_targeting(argv, "/home/coder/.config/opencode")


_VERTEX_VARS = (
    "VERTEX_LOCATION",
    "GCLOUD_PROJECT",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "CLAUDE_CODE_USE_VERTEX",
    "CLOUD_ML_REGION",
)


@pytest.fixture
def clean_vertex_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _VERTEX_VARS:
        monkeypatch.delenv(name, raising=False)


def test_vertex_defaults_are_gated_by_vertex_location(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    clean_vertex_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GCLOUD_PROJECT", "proj")
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert {"ANTHROPIC_VERTEX_PROJECT_ID=proj", "GOOGLE_CLOUD_PROJECT=proj"} <= set(argv)
    assert not any(a.startswith(("CLAUDE_CODE_USE_VERTEX=", "CLOUD_ML_REGION=")) for a in argv)
    assert not any(a.startswith("VERTEX_LOCATION=") for a in argv)
    captured_run.clear()
    monkeypatch.setenv("VERTEX_LOCATION", "global")
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert {"CLAUDE_CODE_USE_VERTEX=1", "CLOUD_ML_REGION=global", "VERTEX_LOCATION=global"} <= set(
        argv
    )


def test_vertex_project_vars_skipped_without_gcloud_project(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    clean_vertex_env: None,
) -> None:
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert not any(
        a.startswith(("ANTHROPIC_VERTEX_PROJECT_ID=", "GOOGLE_CLOUD_PROJECT=")) for a in argv
    )


def test_vertex_credentials_file_mounted_read_only(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    clean_vertex_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    creds = tmp_path / "sa.json"
    creds.write_text("{}")
    target = "/home/coder/.config/gcloud/application_default_credentials.json"
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds))
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert f"{creds}:{target}:ro" in argv
    assert f"GOOGLE_APPLICATION_CREDENTIALS={target}" in argv


def test_vertex_credentials_missing_file_skipped(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    clean_vertex_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/does/not/exist.json")
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert not any(a.startswith("GOOGLE_APPLICATION_CREDENTIALS=") for a in argv)
    assert not any("exist.json" in a for a in argv)


def test_disable_mount_removes_credentials_mount_and_env(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    clean_vertex_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    creds = tmp_path / "sa.json"
    creds.write_text("{}")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds))
    runner.invoke(cli_mod.app, ["--runtime", "podman", "--disable-mount", str(tmp_path)])
    (argv,) = captured_run
    assert not any("application_default_credentials" in a for a in argv)
    assert not any(a.startswith("GOOGLE_APPLICATION_CREDENTIALS=") for a in argv)


def test_disable_env_and_config_override_vertex_defaults(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    clean_vertex_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERTEX_LOCATION", "global")
    monkeypatch.setenv("GCLOUD_PROJECT", "proj")
    _write_config(isolated_home, 'extra_envs = ["CLOUD_ML_REGION=eu"]\n')
    runner.invoke(cli_mod.app, ["--runtime", "podman", "--disable-env", "CLAUDE_CODE_USE_VERTEX"])
    (argv,) = captured_run
    assert "CLOUD_ML_REGION=eu" in argv
    assert "CLOUD_ML_REGION=global" not in argv
    assert not any(a.startswith("CLAUDE_CODE_USE_VERTEX=") for a in argv)


def test_config_mounts_dirs_files_access_and_explicit_target(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    (isolated_home / ".claude").mkdir()
    (isolated_home / ".claude.json").write_text("{}")
    (isolated_home / ".config/gh").mkdir(parents=True)
    (isolated_home / "src").mkdir()
    _write_config(
        isolated_home,
        'extra_mounts = ["~/.claude", "~/.claude.json", "~/.config/gh:ro", "~/src:/opt/src:ro"]\n',
    )
    result = runner.invoke(cli_mod.app, ["--runtime", "podman"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert f"{isolated_home}/.claude:/home/coder/.claude" in argv
    assert f"{isolated_home}/.claude.json:/home/coder/.claude.json" in argv
    assert f"{isolated_home}/.config/gh:/home/coder/.config/gh:ro" in argv
    assert f"{isolated_home}/src:/opt/src:ro" in argv


def test_ro_mount_uses_private_selinux_label(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(selinux, "detect", lambda **_kw: selinux.SELinuxStatus(enabled=True))
    (isolated_home / "a").mkdir()
    (isolated_home / "b").mkdir()
    _write_config(isolated_home, 'extra_mounts = ["~/a:ro", "~/b"]\n')
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert f"{isolated_home}/a:/home/coder/a:Z,ro" in argv
    assert f"{isolated_home}/b:/home/coder/b:z" in argv


def test_invalid_extra_mount_flag_errors(
    isolated_home: Path, workdir: Path, fake_engine_path: Path
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--extra-mount", "a:rel"])
    assert result.exit_code == 1
    assert "invalid mount" in result.output


def test_known_hosts_mounted_read_only_and_disableable(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    (isolated_home / ".ssh").mkdir()
    (isolated_home / ".ssh/known_hosts").write_text("")
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert f"{isolated_home}/.ssh/known_hosts:/home/coder/.ssh/known_hosts:ro" in argv
    captured_run.clear()
    runner.invoke(
        cli_mod.app, ["--runtime", "podman", "--disable-mount", str(isolated_home / ".ssh")]
    )
    (argv,) = captured_run
    assert not _mount_flags_targeting(argv, "/home/coder/.ssh/known_hosts")


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


def test_config_mount_skipped_when_workdir_target_collides(
    isolated_home: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = isolated_home / "bin"
    bin_dir.mkdir()
    _write_config(isolated_home, 'extra_mounts = ["~/bin:ro"]\n')
    monkeypatch.chdir(bin_dir)
    result = runner.invoke(cli_mod.app, ["--runtime", "podman"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    bin_flags = _mount_flags_targeting(argv, "/home/coder/bin")
    assert len(bin_flags) == 1
    assert "type=bind" in bin_flags[0]  # the rw workdir mount, not the ro config mount


def test_cli_mount_wins_over_config_mount_for_same_target(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
) -> None:
    bin_dir = isolated_home / "bin"
    bin_dir.mkdir()
    _write_config(isolated_home, 'extra_mounts = ["~/bin:ro"]\n')
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--extra-mount", str(bin_dir)])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert _mount_flags_targeting(argv, "/home/coder/bin") == [f"{bin_dir}:/home/coder/bin"]


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


def test_web_mode_uses_config_and_masks_password(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    _write_config(
        isolated_home, 'web_port = 6000\nweb_username = "bob"\nweb_password = "s3cretpw"\n'
    )
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--web"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert "6000:6000" in argv
    assert "OPENCODE_SERVER_USERNAME=bob" in argv
    assert "OPENCODE_SERVER_PASSWORD=s3cretpw" in argv
    assert "*****" in result.output
    assert "s3cretpw" not in result.output


def test_web_flags_override_config(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    _write_config(isolated_home, 'web_port = 6000\nweb_username = "bob"\nweb_password = "cfgpw"\n')
    args = ["--runtime", "podman", "--web", "--web-port", "7000", "--web-username", "al"]
    result = runner.invoke(cli_mod.app, [*args, "--web-password", "clipw"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert "7000:7000" in argv
    assert "OPENCODE_SERVER_USERNAME=al" in argv
    assert "OPENCODE_SERVER_PASSWORD=clipw" in argv
    assert "clipw" in result.output
    assert "cfgpw" not in result.output


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


def test_env_assignment_expands_host_references(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GCLOUD_PROJECT", "some-project")
    _write_config(
        isolated_home,
        'extra_envs = ["LIT=global", "P=${GCLOUD_PROJECT}", "Q=a${GCLOUD_PROJECT}b"]\n',
    )
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert {"LIT=global", "P=some-project", "Q=asome-projectb"} <= set(argv)


def test_env_assignment_skipped_when_reference_unset(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    _write_config(isolated_home, 'extra_envs = ["P=${GCLOUD_PROJECT}", "LIT=1"]\n')
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert not any(a.startswith("P=") for a in argv)
    assert "LIT=1" in argv


def test_cli_env_assignment_overrides_config_value(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    _write_config(isolated_home, 'extra_envs = ["X=config"]\n')
    runner.invoke(cli_mod.app, ["--runtime", "podman", "--extra-env", "X=cli"])
    (argv,) = captured_run
    assert "X=cli" in argv
    assert "X=config" not in argv


def test_invalid_extra_env_flag_errors(
    isolated_home: Path, workdir: Path, fake_engine_path: Path
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--extra-env", "=x"])
    assert result.exit_code == 1
    assert "invalid environment entry" in result.output


def test_extra_mount_path_that_does_not_exist_is_skipped(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--extra-mount", "/does/not/exist"])
    assert result.exit_code == 0, result.output
    (argv,) = captured_run
    assert not any("/does/not/exist" in flag for flag in argv)


def test_config_env_names_forwarded_bugzilla_redmine(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BUGZILLA_API_KEY", "bz-secret")
    monkeypatch.setenv("REDMINE_API_KEY", "rm-secret")
    _write_config(isolated_home, 'extra_envs = ["BUGZILLA_API_KEY", "REDMINE_API_KEY"]\n')
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert "BUGZILLA_API_KEY=bz-secret" in argv
    assert "REDMINE_API_KEY=rm-secret" in argv


def test_config_env_names_forwarded_pushover(
    isolated_home: Path,
    workdir: Path,
    fake_engine_path: Path,
    captured_run: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUSHOVER_USER", "po-user")
    monkeypatch.setenv("PUSHOVER_TOKEN", "po-token")
    _write_config(isolated_home, 'extra_envs = ["PUSHOVER_USER", "PUSHOVER_TOKEN"]\n')
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
    _write_config(
        isolated_home,
        'extra_mounts = ["~/.aws", "~/.kube", "~/.npm"]\ndisable_mounts = ["~/.aws"]\n',
    )
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


def test_disable_mounts_parent_path_filters_config_mounts(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    (isolated_home / ".config/gh").mkdir(parents=True)
    _write_config(
        isolated_home, 'extra_mounts = ["~/.config/gh:ro"]\ndisable_mounts = ["~/.config"]\n'
    )
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert not _mount_flags_targeting(argv, "/home/coder/.config/gh")


def test_cli_extra_mount_wins_over_disabled_parent(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    for d in ("gh", "osc"):
        (isolated_home / ".config" / d).mkdir(parents=True)
    gh = isolated_home / ".config/gh"
    _write_config(
        isolated_home,
        'disable_mounts = ["~/.config"]\nextra_mounts = ["~/.config/gh", "~/.config/osc"]\n',
    )
    runner.invoke(cli_mod.app, ["--runtime", "podman", "--extra-mount", str(gh)])
    (argv,) = captured_run
    assert _mount_flags_targeting(argv, "/home/coder/.config/gh") == [
        f"{gh}:/home/coder/.config/gh"
    ]
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
    assert any(a.startswith(f"{workdir / 'rel'}:") for a in argv)
    assert any(a.startswith(f"{cli_dir}:") for a in argv)


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
        'extra_envs = ["PUSHOVER_USER", "PUSHOVER_TOKEN", "BUGZILLA_API_KEY"]\n'
        'disable_envs = ["PUSHOVER_USER", "PUSHOVER_TOKEN"]\n',
    )
    runner.invoke(
        cli_mod.app,
        [
            "--runtime",
            "podman",
            "--disable-env",
            "BUGZILLA_API_KEY",
            "--extra-env",
            "PUSHOVER_TOKEN",
        ],
    )
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
    _write_config(isolated_home, 'extra_envs = ["REDMINE_API_KEY"]\n')
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
