"""Host terminal integration for interactive container sessions."""

from __future__ import annotations

import re
from pathlib import Path

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_RESET_MODES = (
    "\x1b[0m"
    "\x1b[?25h"
    "\x1b[?1049l"
    "\x1b[?2004l"
    "\x1b[?1000l"
    "\x1b[?1002l"
    "\x1b[?1003l"
    "\x1b[?1005l"
    "\x1b[?1006l"
    "\x1b[?1015l"
    "\x1b[?1016l"
    "\x1b[?1l"
    "\x1b>"
    "\x1b[?7h"
)


def should_allocate_tty(*, stdin_tty: bool, stdout_tty: bool, term: str | None) -> bool:
    return stdin_tty and stdout_tty and bool(term) and term != "dumb"


def set_title(title: str) -> str:
    safe_title = _CONTROL_CHARS.sub("", title)[:120]
    return f"\x1b]2;{safe_title}\x07"


def preamble(title: str) -> str:
    return f"\x1b[22;0t{set_title(title)}"


def epilogue() -> str:
    return f"{_RESET_MODES}\x1b[23;0t"


def title_for(*, workspace: str | None, cwd: Path, entrypoint: str) -> str:
    location = workspace or cwd.name
    return f"ai-container: {location} ({Path(entrypoint).name})"
