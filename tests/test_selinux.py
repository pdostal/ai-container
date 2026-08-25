from __future__ import annotations

import shutil

import pytest
from pytest_subprocess import FakeProcess

from ai_container import selinux
from ai_container.console import Reporter


def test_darwin_never_detects_selinux(fp: FakeProcess) -> None:
    status = selinux.detect(host_platform="Darwin", reporter=Reporter())
    assert status.enabled is False
    assert status.mode is None


def test_missing_sestatus_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    status = selinux.detect(host_platform="Linux", reporter=Reporter())
    assert status.enabled is False


def test_sestatus_enabled_enforcing(monkeypatch: pytest.MonkeyPatch, fp: FakeProcess) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/sbin/sestatus")
    fp.register(
        ["sestatus"],
        stdout=(
            "SELinux status:                 enabled\nCurrent mode:                   enforcing\n"
        ),
    )
    status = selinux.detect(host_platform="Linux", reporter=Reporter())
    assert status.enabled is True
    assert status.mode == "enforcing"


def test_sestatus_disabled(monkeypatch: pytest.MonkeyPatch, fp: FakeProcess) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/sbin/sestatus")
    fp.register(["sestatus"], stdout="SELinux status:                 disabled\n")
    status = selinux.detect(host_platform="Linux", reporter=Reporter())
    assert status.enabled is False


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [(True, ",z"), (False, "")],
)
def test_bind_suffix(enabled: bool, expected: str) -> None:
    assert selinux.bind_suffix(enabled) == expected


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [(True, ":z"), (False, "")],
)
def test_volume_rw_suffix(enabled: bool, expected: str) -> None:
    assert selinux.volume_rw_suffix(enabled) == expected


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [(True, ":Z,ro"), (False, ":ro")],
)
def test_volume_ro_suffix(enabled: bool, expected: str) -> None:
    assert selinux.volume_ro_suffix(enabled) == expected
