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


def test_load_config_reads_add_hosts(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text('add_hosts = ["openqa-ai.qam.suse.cz:169.254.1.2"]\n')
    result = config.load_config(path)
    assert result.add_hosts == ("openqa-ai.qam.suse.cz:169.254.1.2",)


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


def test_load_config_ignores_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "ai-container.toml"
    path.write_text('unrelated = "value"\n')
    result = config.load_config(path)
    assert result == config.LauncherConfig()
