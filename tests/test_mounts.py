from __future__ import annotations

from pathlib import Path

from ai_container import mounts
from ai_container.console import Reporter
from ai_container.models import MountAccess, MountKind

CONTAINER_HOME = Path("/home/coder")


def test_glab_config_prefers_macos_path_when_present(tmp_path: Path) -> None:
    mac_dir = tmp_path / "Library/Application Support/glab-cli"
    mac_dir.mkdir(parents=True)
    assert mounts.glab_config_dir(tmp_path, host_platform="Darwin") == mac_dir


def test_glab_config_falls_back_to_xdg_path_on_macos_without_mac_dir(tmp_path: Path) -> None:
    result = mounts.glab_config_dir(tmp_path, host_platform="Darwin")
    assert result == tmp_path / ".config/glab-cli"


def test_glab_config_uses_xdg_path_on_linux(tmp_path: Path) -> None:
    mac_dir = tmp_path / "Library/Application Support/glab-cli"
    mac_dir.mkdir(parents=True)
    result = mounts.glab_config_dir(tmp_path, host_platform="Linux")
    assert result == tmp_path / ".config/glab-cli"


def test_default_mounts_cover_expected_labels(tmp_path: Path) -> None:
    specs = mounts.default_mounts(tmp_path, CONTAINER_HOME, host_platform="Linux")
    labels = {spec.label for spec in specs}
    assert "Claude config directory" in labels
    assert "OpenCode data directory" in labels
    assert "Kubernetes config" in labels
    assert len(specs) == len(labels)  # no accidental duplicates


def test_apply_mount_skips_missing_host_path(tmp_path: Path) -> None:
    from ai_container.models import MountSpec

    spec = MountSpec(
        "does-not-exist",
        tmp_path / "nope",
        CONTAINER_HOME / "nope",
        MountKind.DIRECTORY,
        MountAccess.READ_WRITE,
    )
    args: list[str] = []
    applied = mounts.apply_mount(args, spec, selinux_enabled=False, reporter=Reporter())
    assert applied is False
    assert args == []


def test_apply_mount_adds_rw_flag_without_selinux(tmp_path: Path) -> None:
    from ai_container.models import MountSpec

    host_dir = tmp_path / "cfg"
    host_dir.mkdir()
    spec = MountSpec(
        "cfg", host_dir, CONTAINER_HOME / "cfg", MountKind.DIRECTORY, MountAccess.READ_WRITE
    )
    args: list[str] = []
    applied = mounts.apply_mount(args, spec, selinux_enabled=False, reporter=Reporter())
    assert applied is True
    assert args == ["-v", f"{host_dir}:{CONTAINER_HOME / 'cfg'}"]


def test_apply_mount_adds_ro_flag_with_selinux(tmp_path: Path) -> None:
    from ai_container.models import MountSpec

    host_file = tmp_path / "known_hosts"
    host_file.write_text("")
    spec = MountSpec("kh", host_file, CONTAINER_HOME / "kh", MountKind.FILE, MountAccess.READ_ONLY)
    args: list[str] = []
    mounts.apply_mount(args, spec, selinux_enabled=True, reporter=Reporter())
    assert args == ["-v", f"{host_file}:{CONTAINER_HOME / 'kh'}:Z,ro"]


def test_gcloud_mount_and_env(tmp_path: Path) -> None:
    spec = mounts.gcloud_mount(tmp_path, CONTAINER_HOME)
    assert spec.host == tmp_path / ".config/gcloud/application_default_credentials.json"
    env = mounts.gcloud_env(spec.container)
    assert env["GOOGLE_APPLICATION_CREDENTIALS"] == str(spec.container)
    assert env["GOOGLE_CLOUD_PROJECT"] == mounts.GCLOUD_PROJECT
