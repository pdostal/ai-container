"""Optional host-level launcher config file (``~/.config/ai-container.toml``).

Lets a machine that always needs the same extra flags (e.g. a static
``--add-host`` entry for a service only reachable from one host) carry that
as a standing default instead of retyping it on every invocation.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """Raised when the config file exists but can't be parsed/understood."""


@dataclass(frozen=True, slots=True)
class Workspace:
    name: str
    dirs: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class LauncherConfig:
    add_hosts: tuple[str, ...] = ()
    extra_envs: tuple[str, ...] = ()
    disable_envs: tuple[str, ...] = ()
    extra_mounts: tuple[Path, ...] = ()
    disable_mounts: tuple[Path, ...] = ()
    ssh_agent: bool = True
    workspaces: tuple[Workspace, ...] = ()
    auto_workspaces: bool = False


def config_path(host_home: Path) -> Path:
    """Resolve the config file path: $AI_CONTAINER_CONFIG, else ~/.config/ai-container.toml."""
    override = os.environ.get("AI_CONTAINER_CONFIG")
    if override:
        return Path(override)
    return host_home / ".config" / "ai-container.toml"


def normalize_disable_path(raw: Path, *, source: str) -> Path:
    """Expand ``~`` and require an absolute path without ``..`` (matching is lexical)."""
    expanded = raw.expanduser()
    if not expanded.is_absolute() or ".." in expanded.parts:
        raise ConfigError(f"{source}: disable path must be absolute without '..': {raw}")
    return expanded


def _str_list(path: Path, data: dict[str, object], key: str) -> tuple[str, ...]:
    raw = data.get(key, [])
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ConfigError(f"{path}: {key!r} must be an array of strings")
    return tuple(raw)


def load_config(path: Path) -> LauncherConfig:
    """Load ``path``, tolerating a missing file the way MountSpec.exists() does."""
    if not path.is_file():
        return LauncherConfig()

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc

    if "env" in data:
        raise ConfigError(f"{path}: 'env' was renamed to 'extra_envs'")

    disable_mounts = tuple(
        normalize_disable_path(Path(d), source=f"{path}: 'disable_mounts'")
        for d in _str_list(path, data, "disable_mounts")
    )
    extra_mounts = tuple(Path(d).expanduser() for d in _str_list(path, data, "extra_mounts"))

    ssh_agent = data.get("ssh_agent", True)
    if not isinstance(ssh_agent, bool):
        raise ConfigError(f"{path}: 'ssh_agent' must be a boolean")

    raw_auto_workspaces = data.get("auto_workspaces", False)
    if not isinstance(raw_auto_workspaces, bool):
        raise ConfigError(f"{path}: 'auto_workspaces' must be a boolean")

    raw_workspaces = data.get("workspace", [])
    if not isinstance(raw_workspaces, list):
        raise ConfigError(f"{path}: 'workspace' must be an array of tables")
    workspaces = tuple(_parse_workspace(path, entry) for entry in raw_workspaces)

    return LauncherConfig(
        add_hosts=_str_list(path, data, "add_hosts"),
        extra_envs=_str_list(path, data, "extra_envs"),
        disable_envs=_str_list(path, data, "disable_envs"),
        extra_mounts=extra_mounts,
        disable_mounts=disable_mounts,
        ssh_agent=ssh_agent,
        workspaces=workspaces,
        auto_workspaces=raw_auto_workspaces,
    )


def _parse_workspace(path: Path, entry: object) -> Workspace:
    if not isinstance(entry, dict):
        raise ConfigError(f"{path}: each [[workspace]] entry must be a table")
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"{path}: workspace 'name' must be a non-empty string")
    dirs = entry.get("dirs")
    if not isinstance(dirs, list) or not dirs or not all(isinstance(d, str) for d in dirs):
        raise ConfigError(f"{path}: workspace '{name}' 'dirs' must be a non-empty array of strings")
    return Workspace(name=name, dirs=tuple(Path(d).expanduser() for d in dirs))
