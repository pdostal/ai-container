"""Strip the box-drawing borders from Typer's Rich-based help/error output.

Typer's ``--help`` and error formatting (``typer.rich_utils``) unconditionally
wraps the options/arguments listing and error messages in a ``rich.panel.Panel``
(the "boxes"), with only style/color constants exposed for customization --
no public setting to disable the border itself.

Rather than vendoring ``typer.rich_utils``'s ~150 lines of private
table-building helpers just to change the final wrapper, this swaps out the
``Panel`` name inside that module's own namespace for a borderless
stand-in. Module-level functions resolve bare names (like ``Panel(...)``)
from their module's globals at call time, so overwriting
``typer.rich_utils.Panel`` after import is enough -- everything else
(coloring, tables, alignment) is untouched.
"""

from __future__ import annotations

from typing import Any

import typer.rich_utils as _rich_utils
from rich.console import Group, RenderableType
from rich.text import Text


def _borderless_panel(
    renderable: RenderableType,
    *,
    title: str | None = None,
    border_style: str | None = None,
    title_align: str = "left",
    **_ignored: Any,
) -> RenderableType:
    if not title:
        return renderable
    heading_style = f"bold {border_style}" if border_style else "bold"
    return Group(Text(""), Text(title, style=heading_style), renderable)


def apply() -> None:
    """Install the borderless panel replacement. Idempotent."""
    _rich_utils.Panel = _borderless_panel  # type: ignore[attr-defined,assignment]


def installed_panel_factory() -> object:
    """Return whatever `typer.rich_utils.Panel` currently resolves to.

    Lets tests verify `apply()`'s effect from outside this module without
    each needing their own `type: ignore[attr-defined]` for
    `typer.rich_utils` not explicitly re-exporting `Panel`.
    """
    return _rich_utils.Panel  # type: ignore[attr-defined]
