from __future__ import annotations

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
        ["--runtime", "podman", "--mount-extra", str(extra), "--mount-extra", str(extra)],
    )
    (argv,) = captured_run
    mount_flags = [flag for flag in argv if str(extra) in flag]
    assert len(mount_flags) == 1


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
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    gcloud_dir = isolated_home / ".config/gcloud"
    gcloud_dir.mkdir(parents=True)
    (gcloud_dir / "application_default_credentials.json").write_text("{}")
    runner.invoke(cli_mod.app, ["--runtime", "podman"])
    (argv,) = captured_run
    assert any("application_default_credentials.json" in flag for flag in argv)
    assert "GOOGLE_CLOUD_PROJECT=REDACTED-GCP-PROJECT" in argv


def test_extra_mount_path_that_does_not_exist_is_skipped(
    isolated_home: Path, workdir: Path, fake_engine_path: Path, captured_run: list[list[str]]
) -> None:
    result = runner.invoke(cli_mod.app, ["--runtime", "podman", "--mount-extra", "/does/not/exist"])
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
