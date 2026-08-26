from __future__ import annotations

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from ai_container import rich_patches


def test_borderless_panel_returns_renderable_unchanged_without_title() -> None:
    content = Text("hello")
    result = rich_patches._borderless_panel(content)
    assert result is content


def test_borderless_panel_wraps_titled_content_without_a_box() -> None:
    content = Text("some options table")
    result = rich_patches._borderless_panel(content, title="Options", border_style="dim")
    assert isinstance(result, Group)
    rendered = list(result.renderables)
    assert rendered[-1] is content
    heading = rendered[-2]
    assert isinstance(heading, Text)
    assert heading.plain == "Options"
    assert heading.style == "bold dim"


def test_borderless_panel_defaults_to_bold_without_border_style() -> None:
    result = rich_patches._borderless_panel(Text("x"), title="Error")
    assert isinstance(result, Group)
    heading = list(result.renderables)[-2]
    assert isinstance(heading, Text)
    assert heading.style == "bold"


def test_apply_replaces_panel_in_rich_utils_namespace() -> None:
    """Prove `apply()` actually changes the name, then leave the patch
    installed -- cli.py applies it once at import time for the whole
    process, and other tests rely on that already being in effect.
    """
    rich_patches.apply()
    installed = rich_patches.installed_panel_factory()
    assert installed is rich_patches._borderless_panel
    assert installed is not Panel


def test_apply_is_idempotent() -> None:
    rich_patches.apply()
    rich_patches.apply()
    assert rich_patches.installed_panel_factory() is rich_patches._borderless_panel
