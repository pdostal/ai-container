"""Optional host-level launcher config file (``~/.config/ai-container.toml``).

Lets a machine that always needs the same extra flags (e.g. a static
``--add-host`` entry for a service only reachable from one host) carry that
as a standing default instead of retyping it on every invocation.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .models import MountAccess, MountEntry


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
    extra_mounts: tuple[MountEntry, ...] = ()
    disable_mounts: tuple[Path, ...] = ()
    ssh_agent: bool = True
    workspaces: tuple[Workspace, ...] = ()
    auto_workspaces: bool = False
    web_port: int | None = None
    web_username: str | None = None
    web_password: str | None = None


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


_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def parse_mount(raw: str, *, source: str) -> MountEntry:
    """Parse ``SOURCE[:TARGET][:ro|rw]`` (``~`` expanded in SOURCE, TARGET absolute)."""
    parts = raw.split(":")
    access = MountAccess(parts.pop()) if len(parts) > 1 and parts[-1] in ("ro", "rw") else None
    target = Path(parts[1]) if len(parts) == 2 else None
    if not 1 <= len(parts) <= 2 or not parts[0] or (target and not target.is_absolute()):
        raise ConfigError(
            f"{source}: invalid mount {raw!r} (expected SOURCE[:ABSOLUTE_TARGET][:ro|rw])"
        )
    return MountEntry(Path(parts[0]).expanduser(), target, access or MountAccess.READ_WRITE)


def env_name(entry: str, *, source: str) -> str:
    """Validate an env entry (``NAME`` or ``NAME=value``) and return ``NAME``."""
    name = entry.partition("=")[0]
    if not _ENV_NAME_RE.fullmatch(name):
        raise ConfigError(f"{source}: invalid environment entry {entry!r} (expected NAME[=value])")
    return name


def _str_list(path: Path, data: dict[str, object], key: str) -> tuple[str, ...]:
    raw = data.get(key, [])
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ConfigError(f"{path}: {key!r} must be an array of strings")
    return tuple(raw)


def _opt_str(path: Path, data: dict[str, object], key: str) -> str | None:
    raw = data.get(key)
    if raw is not None and (not isinstance(raw, str) or not raw):
        raise ConfigError(f"{path}: {key!r} must be a non-empty string")
    return raw


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
    extra_mounts = tuple(
        parse_mount(m, source=f"{path}: 'extra_mounts'")
        for m in _str_list(path, data, "extra_mounts")
    )
    extra_envs = _str_list(path, data, "extra_envs")
    disable_envs = _str_list(path, data, "disable_envs")
    for entry in (*extra_envs, *disable_envs):
        env_name(entry, source=str(path))

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

    web_port = data.get("web_port")
    if web_port is not None and (
        isinstance(web_port, bool) or not isinstance(web_port, int) or not 1 <= web_port <= 65535
    ):
        raise ConfigError(f"{path}: 'web_port' must be an integer between 1 and 65535")
    web_username = _opt_str(path, data, "web_username")
    web_password = _opt_str(path, data, "web_password")

    return LauncherConfig(
        add_hosts=_str_list(path, data, "add_hosts"),
        extra_envs=extra_envs,
        disable_envs=disable_envs,
        extra_mounts=extra_mounts,
        disable_mounts=disable_mounts,
        ssh_agent=ssh_agent,
        workspaces=workspaces,
        auto_workspaces=raw_auto_workspaces,
        web_port=web_port,
        web_username=web_username,
        web_password=web_password,
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
