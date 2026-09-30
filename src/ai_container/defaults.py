"""Built-in defaults: assistant state mounts and the host-driven Vertex AI setup."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .models import MountAccess, MountEntry

ASSISTANT_MOUNTS = (
    ".claude",
    ".claude.json",
    ".config/opencode",
    ".local/share/opencode",
    ".local/state/opencode",
    ".cache/opencode",
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
