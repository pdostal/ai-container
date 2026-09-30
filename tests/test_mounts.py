from __future__ import annotations

from pathlib import Path

from ai_container import mounts
from ai_container.console import Reporter
from ai_container.models import MountAccess, MountKind, MountSpec

CONTAINER_HOME = Path("/home/coder")


def test_apply_mount_skips_missing_host_path(tmp_path: Path) -> None:
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
    host_file = tmp_path / "known_hosts"
    host_file.write_text("")
    spec = MountSpec("kh", host_file, CONTAINER_HOME / "kh", MountKind.FILE, MountAccess.READ_ONLY)
    args: list[str] = []
    mounts.apply_mount(args, spec, selinux_enabled=True, reporter=Reporter())
    assert args == ["-v", f"{host_file}:{CONTAINER_HOME / 'kh'}:Z,ro"]


def test_is_disabled_exact_parent_and_non_match(tmp_path: Path) -> None:
    host = tmp_path / ".aws"
    assert mounts.is_disabled(host, [tmp_path / ".aws"])
    assert mounts.is_disabled(host, [tmp_path])
    assert not mounts.is_disabled(host, [tmp_path / ".aws2"])
    assert not mounts.is_disabled(host, [tmp_path / ".aws" / "sub"])
    assert not mounts.is_disabled(host, [])
