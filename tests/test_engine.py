from __future__ import annotations

import os

import pytest

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
        engine.resolve_engine(explicit="docker", env_runtime=None, host_platform="Linux")


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
    [(Engine.PODMAN, "localhost/ai"), (Engine.CONTAINER, "ai")],
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
