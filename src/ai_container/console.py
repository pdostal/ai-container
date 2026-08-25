"""Coloured status output, replacing the bash script's echo/debug_echo helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console

_default_console = Console()
_default_error_console = Console(stderr=True)


@dataclass
class Reporter:
    """Prints status lines, gating the noisy ones behind ``--debug``.

    ``ok``/``fail``/``step`` are always shown (equivalent to the bash
    script's unconditional ``echo`` calls). ``debug_ok``/``debug_fail``
    mirror ``debug_echo``/``debug_echo_err``, only shown when debug mode
    is on.

    ``console``/``error_console`` are injectable so tests can capture
    output without touching global state.
    """

    debug: bool = False
    console: Console = field(default_factory=lambda: _default_console)
    error_console: Console = field(default_factory=lambda: _default_error_console)

    def ok(self, message: str) -> None:
        self.console.print(f"[bold green]\u2713[/bold green] {message}")

    def fail(self, message: str) -> None:
        self.error_console.print(f"[bold red]\u2717[/bold red] {message}")

    def step(self, message: str) -> None:
        self.console.print(f"[bold cyan]\u25b6[/bold cyan] {message}")

    def detail(self, message: str) -> None:
        self.console.print(f"  [dim]\u2192[/dim] {message}")

    def blank(self) -> None:
        self.console.print()

    def debug_ok(self, message: str) -> None:
        if self.debug:
            self.ok(message)

    def debug_fail(self, message: str) -> None:
        if self.debug:
            self.fail(message)

    def debug_detail(self, message: str) -> None:
        if self.debug:
            self.detail(message)
