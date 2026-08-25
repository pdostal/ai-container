"""The full table of conditional credential/cache mounts.

Replaces ~20 near-identical copy-pasted "if it exists, mount it" blocks in
the original bash script with one declarative list plus a single apply
function.
"""

from __future__ import annotations

from pathlib import Path

from . import selinux
from .console import Reporter
from .models import MountAccess, MountKind, MountSpec

GCLOUD_PROJECT = "REDACTED-GCP-PROJECT"


def glab_config_dir(host_home: Path, *, host_platform: str) -> Path:
    if host_platform == "Darwin":
        mac_path = host_home / "Library" / "Application Support" / "glab-cli"
        if mac_path.is_dir():
            return mac_path
    return host_home / ".config" / "glab-cli"


def default_mounts(host_home: Path, container_home: Path, *, host_platform: str) -> list[MountSpec]:
    d = MountKind.DIRECTORY
    f = MountKind.FILE
    rw = MountAccess.READ_WRITE
    ro = MountAccess.READ_ONLY

    def mount(
        label: str, host_rel: str, container_rel: str, kind: MountKind, access: MountAccess
    ) -> MountSpec:
        return MountSpec(label, host_home / host_rel, container_home / container_rel, kind, access)

    glab_host = glab_config_dir(host_home, host_platform=host_platform)

    return [
        mount("Claude config directory", ".claude", ".claude", d, rw),
        mount("Claude config file", ".claude.json", ".claude.json", f, rw),
        mount("GitHub CLI config", ".config/gh", ".config/gh", d, ro),
        MountSpec("GitLab CLI config", glab_host, container_home / ".config/glab-cli", d, ro),
        mount("OpenCode config directory", ".config/opencode", ".config/opencode", d, rw),
        mount("OpenCode data directory", ".local/share/opencode", ".local/share/opencode", d, rw),
        mount("OpenCode state directory", ".local/state/opencode", ".local/state/opencode", d, rw),
        mount("OpenCode cache directory", ".cache/opencode", ".cache/opencode", d, rw),
        mount("npm cache directory", ".npm", ".npm", d, rw),
        mount("Go module cache directory", "go/pkg/mod", "go/pkg/mod", d, rw),
        mount("Go build cache directory", ".cache/go-build", ".cache/go-build", d, rw),
        mount("Cargo registry cache directory", ".cargo/registry", ".cargo/registry", d, rw),
        mount("Cargo git cache directory", ".cargo/git", ".cargo/git", d, rw),
        mount("pip cache directory", ".cache/pip", ".cache/pip", d, rw),
        mount("uv cache directory", ".cache/uv", ".cache/uv", d, rw),
        mount("SSH known_hosts", ".ssh/known_hosts", ".ssh/known_hosts", f, ro),
        mount("Git config", ".gitconfig", ".gitconfig", f, ro),
        mount("openQA config directory", ".config/openqa", ".config/openqa", d, ro),
        mount("osc config directory", ".config/osc", ".config/osc", d, rw),
        mount("tea config directory", ".config/tea", ".config/tea", d, rw),
        mount("AWS config directory", ".aws", ".aws", d, rw),
        mount("Kubernetes config", ".kube", ".kube", d, rw),
    ]


def gcloud_mount(host_home: Path, container_home: Path) -> MountSpec:
    return MountSpec(
        "Google Cloud credentials",
        host_home / ".config/gcloud/application_default_credentials.json",
        container_home / ".config/gcloud/application_default_credentials.json",
        MountKind.FILE,
        MountAccess.READ_ONLY,
    )


def gcloud_env(container_target: Path) -> dict[str, str]:
    return {
        "GOOGLE_APPLICATION_CREDENTIALS": str(container_target),
        "GOOGLE_CLOUD_PROJECT": GCLOUD_PROJECT,
        "VERTEX_LOCATION": "global",
        "VERTEXAI_PROJECT": GCLOUD_PROJECT,
        "VERTEXAI_LOCATION": "global",
    }


def _volume_flag(spec: MountSpec, *, selinux_enabled: bool) -> str:
    suffix = (
        selinux.volume_ro_suffix(selinux_enabled)
        if spec.access is MountAccess.READ_ONLY
        else selinux.volume_rw_suffix(selinux_enabled)
    )
    return f"{spec.host}:{spec.container}{suffix}"


def apply_mount(
    args: list[str], spec: MountSpec, *, selinux_enabled: bool, reporter: Reporter
) -> bool:
    """Append the ``-v`` flag for ``spec`` to ``args`` if the host side exists.

    Returns whether the mount was applied.
    """
    if not spec.exists():
        reporter.debug_fail(f"{spec.label} not found: {spec.host}")
        return False
    access = "rw" if spec.access is MountAccess.READ_WRITE else "ro"
    reporter.debug_ok(f"Mounting {spec.label} (bind-mount, {access}): {spec.host}")
    args.extend(["-v", _volume_flag(spec, selinux_enabled=selinux_enabled)])
    return True
