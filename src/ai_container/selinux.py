"""SELinux detection and the mount-suffix rules that depend on it.

Preserves an existing quirk of the bash script rather than "fixing" it:
read-only ``-v`` mounts get the private ``:Z`` label, while read-write
``-v`` mounts and all ``--mount=type=bind`` mounts get the shared ``:z``
label (so multiple concurrent ``ai-container`` runs sharing the same rw
host directories don't fight over an exclusive relabel).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

from .console import Reporter

_STATUS_RE = re.compile(r"SELinux status:\s*(\S+)")
_MODE_RE = re.compile(r"Current mode:\s*(\S+)")


@dataclass(frozen=True, slots=True)
class SELinuxStatus:
    enabled: bool
    mode: str | None = None


def detect(*, host_platform: str, reporter: Reporter) -> SELinuxStatus:
    if host_platform == "Darwin" or shutil.which("sestatus") is None:
        reporter.debug_detail("\u25cb SELinux not detected (sestatus not available)")
        return SELinuxStatus(enabled=False)

    try:
        result = subprocess.run(["sestatus"], capture_output=True, text=True, check=False)
    except OSError:
        reporter.debug_detail("\u25cb SELinux not detected (sestatus not available)")
        return SELinuxStatus(enabled=False)

    status_match = _STATUS_RE.search(result.stdout)
    if not status_match or status_match.group(1) != "enabled":
        reporter.debug_detail("\u25cb SELinux not detected")
        return SELinuxStatus(enabled=False)

    mode_match = _MODE_RE.search(result.stdout)
    mode = mode_match.group(1) if mode_match else None
    if mode:
        reporter.debug_detail(f"\u2713 SELinux detected ({mode} mode)")
    else:
        reporter.debug_detail("\u2713 SELinux detected (enabled)")
    return SELinuxStatus(enabled=True, mode=mode)


def bind_suffix(enabled: bool) -> str:
    """Suffix for ``--mount=type=bind,...target=...`` specs."""
    return ",z" if enabled else ""


def volume_rw_suffix(enabled: bool) -> str:
    """Suffix for read-write ``-v host:container`` specs."""
    return ":z" if enabled else ""


def volume_ro_suffix(enabled: bool) -> str:
    """Suffix for read-only ``-v host:container:...`` specs."""
    return ":Z,ro" if enabled else ":ro"
