"""Bind-mount helpers: the disable-path filter and the ``-v`` flag builder."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from . import selinux
from .console import Reporter
from .models import MountAccess, MountSpec


def is_disabled(host: Path, disabled: Iterable[Path]) -> bool:
    """True if ``host`` equals or sits below any ``disabled`` path (lexical match)."""
    return any(host.is_relative_to(entry) for entry in disabled)


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
