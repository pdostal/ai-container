"""Built-in defaults: assistant state mounts and the host-driven Vertex AI setup."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .models import MountAccess, MountEntry

ASSISTANT_ENTRYPOINTS = {
    "opencode": "/usr/local/bin/opencode",
    "claude": "/home/coder/.local/bin/claude",
    "codex": "/usr/bin/codex",
    "copilot": "/usr/local/bin/copilot",
    "pi": "/usr/bin/pi",
}
# The image points $TMPDIR at ~/.cache/tmp and the expensive state lives
# underneath it: jiti's Babel transpile cache ($TMPDIR/jiti), Node's
# module-compile cache (NODE_COMPILE_CACHE), and the caches pi-subagents and
# pyright keep in $TMPDIR. A container filesystem is discarded on exit, so
# without this mount every start re-transpiles every pi extension: ~57s cold
# against ~4s once the cache survives a restart. The parent directory is mounted
# rather than the individual entries because pyright names its cache
# `pyright-<pid>-<random>`, which no fixed mount could follow.
PI_CACHE_MOUNTS = (".cache/tmp",)
ASSISTANT_DIRECTORY_MOUNTS = (
    ".agents",
    ".claude",
    ".codex",
    ".copilot",
    ".config/opencode",
    ".local/share/opencode",
    ".local/state/opencode",
    ".cache/opencode",
    ".pi/agent",
    ".pi-lens",
    ".context-mode",
    *PI_CACHE_MOUNTS,
)
ASSISTANT_FILE_MOUNTS = (".claude.json",)
ASSISTANT_MOUNTS = (*ASSISTANT_DIRECTORY_MOUNTS, *ASSISTANT_FILE_MOUNTS)
PROVIDER_KEY_ENVS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
)
ADC_TARGET = ".config/gcloud/application_default_credentials.json"


def assistant_mounts(host_home: Path) -> list[MountEntry]:
    return [MountEntry(host_home / rel) for rel in ASSISTANT_MOUNTS]


def vertex_envs(environ: Mapping[str, str]) -> list[str]:
    """Env entries for Vertex; Claude Code reads CLOUD_ML_REGION, OpenCode VERTEX_LOCATION."""
    envs = [
        "ANTHROPIC_VERTEX_PROJECT_ID=${GCLOUD_PROJECT}",
        "GOOGLE_CLOUD_PROJECT=${GCLOUD_PROJECT}",
    ]
    if environ.get("VERTEX_LOCATION"):
        envs += [
            "VERTEX_LOCATION",
            "CLOUD_ML_REGION=${VERTEX_LOCATION}",
            "CLAUDE_CODE_USE_VERTEX=1",
        ]
    return envs


def vertex_credentials(
    environ: Mapping[str, str], *, cwd: Path, container_home: Path
) -> tuple[MountEntry, str] | None:
    """Read-only mount of the file named by $GOOGLE_APPLICATION_CREDENTIALS plus its env entry."""
    raw = environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    host = cwd / Path(raw).expanduser() if raw else None
    if host is None or not host.is_file():
        return None
    target = container_home / ADC_TARGET
    return MountEntry(
        host, target, MountAccess.READ_ONLY
    ), f"GOOGLE_APPLICATION_CREDENTIALS={target}"
