from __future__ import annotations

import os
from pathlib import Path

import pytest
from pytest_subprocess import FakeProcess

from ai_container import engine
from ai_container.models import Engine


def test_explicit_runtime_wins(fake_engine_path) -> None:  # type: ignore[no-untyped-def]
    result = engine.resolve_engine(
        explicit="container", env_runtime="podman", host_platform="Linux"
    )
    assert result is Engine.CONTAINER


def test_env_runtime_used_when_no_explicit(fake_engine_path) -> None:  # type: ignore[no-untyped-def]
    result = engine.resolve_engine(explicit=None, env_runtime="container", host_platform="Linux")
    assert result is Engine.CONTAINER


def test_unknown_runtime_raises() -> None:
    with pytest.raises(engine.UnknownEngineError):
        engine.resolve_engine(explicit="nonsense", env_runtime=None, host_platform="Linux")


def test_autodetects_podman_when_present(fake_engine_path) -> None:  # type: ignore[no-untyped-def]
    result = engine.resolve_engine(explicit=None, env_runtime=None, host_platform="Linux")
    assert result is Engine.PODMAN


def test_falls_back_to_container_on_macos_without_podman(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "container"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    result = engine.resolve_engine(explicit=None, env_runtime=None, host_platform="Darwin")
    assert result is Engine.CONTAINER


def test_defaults_to_podman_when_nothing_found(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PATH", str(tmp_path))
    result = engine.resolve_engine(explicit=None, env_runtime=None, host_platform="Linux")
    assert result is Engine.PODMAN


def test_ensure_available_raises_when_missing(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(engine.EngineNotFoundError):
        engine.ensure_available(Engine.PODMAN)


def test_ensure_available_ok_when_present(fake_engine_path) -> None:  # type: ignore[no-untyped-def]
    engine.ensure_available(Engine.PODMAN)


@pytest.mark.parametrize(
    ("selected", "expected_image"),
    [(Engine.PODMAN, "localhost/ai"), (Engine.CONTAINER, "ai"), (Engine.DOCKER, "ai")],
)
def test_image_name(selected: Engine, expected_image: str) -> None:
    assert engine.image_name(selected) == expected_image


def test_identity_args_podman() -> None:
    args = engine.identity_args(Engine.PODMAN)
    assert args == ["-h", "ai", "--security-opt", "label=disable"]


def test_identity_args_container(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(os, "getgid", lambda: 1000)
    assert engine.identity_args(Engine.CONTAINER) == ["--uid", "1000", "--gid", "1000"]


def test_network_args_only_for_podman() -> None:
    assert engine.network_args(Engine.PODMAN) == ["--network=pasta", "--userns=keep-id"]
    assert engine.network_args(Engine.CONTAINER) == []


def test_tty_args_differ_per_engine() -> None:
    assert engine.tty_args(Engine.PODMAN) == ["-it"]
    assert engine.tty_args(Engine.CONTAINER) == ["-i", "-t"]


def test_debug_args_differ_per_engine() -> None:
    assert engine.debug_args(Engine.PODMAN) == ["--log-level=debug"]
    assert engine.debug_args(Engine.CONTAINER) == ["--debug"]


def test_oci_runtime_args_podman_microvm() -> None:
    assert engine.oci_runtime_args(Engine.PODMAN, microvm=True) == [
        "--runtime",
        "krun",
        "--annotation",
        "krun.use_passt=1",
    ]


@pytest.mark.parametrize(
    ("selected", "microvm"),
    [(Engine.PODMAN, False), (Engine.CONTAINER, True), (Engine.CONTAINER, False)],
)
def test_oci_runtime_args_empty_otherwise(selected: Engine, microvm: bool) -> None:
    assert engine.oci_runtime_args(selected, microvm=microvm) == []


def test_explicit_docker_runtime(fake_engine_path) -> None:  # type: ignore[no-untyped-def]
    result = engine.resolve_engine(explicit="docker", env_runtime=None, host_platform="Linux")
    assert result is Engine.DOCKER


def _only_on_path(tmp_path, monkeypatch, *names: str) -> None:  # type: ignore[no-untyped-def]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in names:
        exe = bin_dir / name
        exe.write_text("#!/bin/sh\nexit 0\n")
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))


@pytest.mark.parametrize("host_platform", ["Linux", "Darwin"])
def test_autodetects_docker_last(tmp_path, monkeypatch, host_platform: str) -> None:  # type: ignore[no-untyped-def]
    _only_on_path(tmp_path, monkeypatch, "docker")
    result = engine.resolve_engine(explicit=None, env_runtime=None, host_platform=host_platform)
    assert result is Engine.DOCKER


def test_container_beats_docker_on_macos(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _only_on_path(tmp_path, monkeypatch, "docker", "container")
    result = engine.resolve_engine(explicit=None, env_runtime=None, host_platform="Darwin")
    assert result is Engine.CONTAINER


def test_identity_args_docker_rootful(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(os, "getuid", lambda: 1234)
    monkeypatch.setattr(os, "getgid", lambda: 5678)
    assert engine.identity_args(Engine.DOCKER) == [
        "-h",
        "ai",
        "--security-opt",
        "label=disable",
        "--user",
        "1234:5678",
    ]


def test_identity_args_docker_rootless_runs_as_mapped_root() -> None:
    assert engine.identity_args(Engine.DOCKER, docker_rootless=True)[-2:] == ["--user", "0:0"]


def test_docker_engine_has_no_podman_only_args() -> None:
    assert engine.network_args(Engine.DOCKER) == []
    assert engine.oci_runtime_args(Engine.DOCKER, microvm=True) == []
    assert engine.tty_args(Engine.DOCKER) == ["-it"]
    assert engine.debug_args(Engine.DOCKER) == ["--debug"]


_INFO = ["docker", "info", "--format", "{{json .SecurityOptions}}"]


def test_docker_is_rootless_true(fp: FakeProcess) -> None:
    fp.register(_INFO, stdout='["name=seccomp,profile=builtin","name=rootless"]')
    assert engine.docker_is_rootless() is True


def test_docker_is_rootless_false(fp: FakeProcess) -> None:
    fp.register(_INFO, stdout='["name=seccomp,profile=builtin","name=cgroupns"]')
    assert engine.docker_is_rootless() is False


def test_docker_is_rootless_daemon_error(fp: FakeProcess) -> None:
    fp.register(_INFO, returncode=1, stderr="Cannot connect to the Docker daemon")
    with pytest.raises(engine.EngineProbeError, match="Cannot connect"):
        engine.docker_is_rootless()


def _ps(cwd: Path) -> list[str]:
    label = f"label={engine.WORKDIR_LABEL}={cwd}"
    return ["podman", "ps", "--filter", label, "--format", "{{.Names}}"]


def test_find_running_returns_newest(fp: FakeProcess, tmp_path: Path) -> None:
    fp.register(_ps(tmp_path), stdout="ai-new\nai-old\n")
    assert engine.find_running(Engine.PODMAN, tmp_path) == "ai-new"


def test_find_running_none(fp: FakeProcess, tmp_path: Path) -> None:
    fp.register(_ps(tmp_path), stdout="")
    assert engine.find_running(Engine.PODMAN, tmp_path) is None


def test_find_running_none_on_engine_error(fp: FakeProcess, tmp_path: Path) -> None:
    fp.register(_ps(tmp_path), returncode=1, stdout="junk")
    assert engine.find_running(Engine.PODMAN, tmp_path) is None


def test_find_running_unsupported_on_container(tmp_path: Path) -> None:
    assert engine.find_running(Engine.CONTAINER, tmp_path) is None
