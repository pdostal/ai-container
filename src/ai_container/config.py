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
class LauncherConfig:
    add_hosts: tuple[str, ...] = ()


def config_path(host_home: Path) -> Path:
    """Resolve the config file path: $AI_CONTAINER_CONFIG, else ~/.config/ai-container.toml."""
    override = os.environ.get("AI_CONTAINER_CONFIG")
    if override:
        return Path(override)
    return host_home / ".config" / "ai-container.toml"


def load_config(path: Path) -> LauncherConfig:
    """Load ``path``, tolerating a missing file the way MountSpec.exists() does."""
    if not path.is_file():
        return LauncherConfig()

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc

    raw_add_hosts = data.get("add_hosts", [])
    if not isinstance(raw_add_hosts, list) or not all(
        isinstance(item, str) for item in raw_add_hosts
    ):
        raise ConfigError(f"{path}: 'add_hosts' must be an array of strings")

    return LauncherConfig(add_hosts=tuple(raw_add_hosts))
