from __future__ import annotations

from pathlib import Path

import pytest

from ai_container import config


def test_config_path_defaults_to_dot_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_CONTAINER_CONFIG", raising=False)
    assert config.config_path(tmp_path) == tmp_path / ".config" / "ai-container.toml"


def test_config_path_honors_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    override = tmp_path / "elsewhere.toml"
    monkeypatch.setenv("AI_CONTAINER_CONFIG", str(override))
    assert config.config_path(tmp_path) == override


def test_load_config_missing_file_returns_defaults(tmp_path: Path) -> None:
    result = config.load_config(tmp_path / "does-not-exist.toml")
    assert result == config.LauncherConfig()


def test_load_config_reads_add_hosts_and_env(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text(
        'add_hosts = ["openqa-ai.qam.suse.cz:169.254.1.2"]\nenv = ["OPENQA_HOST", "OPENQA_TOKEN"]\n'
    )
    result = config.load_config(path)
    assert result.add_hosts == ("openqa-ai.qam.suse.cz:169.254.1.2",)
    assert result.env == ("OPENQA_HOST", "OPENQA_TOKEN")


def test_load_config_rejects_malformed_toml(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text("this is not [valid toml\n")
    with pytest.raises(config.ConfigError):
        config.load_config(path)


def test_load_config_rejects_non_list_add_hosts(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text('add_hosts = "not-a-list"\n')
    with pytest.raises(config.ConfigError):
        config.load_config(path)


def test_load_config_rejects_non_string_items(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text("add_hosts = [1, 2]\n")
    with pytest.raises(config.ConfigError):
        config.load_config(path)


def test_load_config_rejects_invalid_env(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text('env = "NOT_A_LIST"\n')
    with pytest.raises(config.ConfigError):
        config.load_config(path)


def test_load_config_ignores_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text('unrelated = "value"\n')
    result = config.load_config(path)
    assert result == config.LauncherConfig()


def test_load_config_reads_workspaces_and_auto_workspaces(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text(
        "auto_workspaces = true\n"
        "\n"
        '[[workspace]]\nname = "frontend"\ndirs = ["/repos/app", "/repos/shared"]\n'
        "\n"
        '[[workspace]]\nname = "backend"\ndirs = ["/repos/api"]\n'
    )
    result = config.load_config(path)
    assert result.auto_workspaces is True
    assert result.workspaces == (
        config.Workspace(name="frontend", dirs=(Path("/repos/app"), Path("/repos/shared"))),
        config.Workspace(name="backend", dirs=(Path("/repos/api"),)),
    )


def test_load_config_rejects_non_bool_auto_workspaces(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text('auto_workspaces = "yes"\n')
    with pytest.raises(config.ConfigError):
        config.load_config(path)


def test_load_config_rejects_workspace_missing_name(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text('[[workspace]]\ndirs = ["/repos/app"]\n')
    with pytest.raises(config.ConfigError):
        config.load_config(path)


def test_load_config_rejects_workspace_missing_dirs(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text('[[workspace]]\nname = "frontend"\n')
    with pytest.raises(config.ConfigError):
        config.load_config(path)


def test_load_config_rejects_workspace_empty_dirs(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text('[[workspace]]\nname = "frontend"\ndirs = []\n')
    with pytest.raises(config.ConfigError):
        config.load_config(path)


def test_load_config_rejects_non_list_workspace(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text('workspace = "not-a-list"\n')
    with pytest.raises(config.ConfigError):
        config.load_config(path)


def test_load_config_rejects_non_table_workspace_entry(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text("workspace = [1]\n")
    with pytest.raises(config.ConfigError):
        config.load_config(path)
