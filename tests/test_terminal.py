from pathlib import Path

import pytest

from ai_container import terminal


@pytest.mark.parametrize(
    ("stdin_tty", "stdout_tty", "term", "expected"),
    [
        (True, True, "xterm-256color", True),
        (True, True, "dumb", False),
        (True, True, None, False),
        (False, True, "xterm-256color", False),
        (True, False, "xterm-256color", False),
    ],
)
def test_should_allocate_tty(
    stdin_tty: bool, stdout_tty: bool, term: str | None, expected: bool
) -> None:
    assert (
        terminal.should_allocate_tty(stdin_tty=stdin_tty, stdout_tty=stdout_tty, term=term)
        is expected
    )


def test_title_sequences_sanitize_controls_and_restore_title() -> None:
    assert terminal.preamble("safe\x1b]2;bad\x07") == "\x1b[22;0t\x1b]2;safe]2;bad\x07"
    assert terminal.epilogue().endswith("\x1b[23;0t")
    for mode in (1000, 1002, 1003, 1005, 1006, 1015, 1016, 2004):
        assert f"\x1b[?{mode}l" in terminal.epilogue()


def test_title_for_uses_workspace_or_directory() -> None:
    assert (
        terminal.title_for(
            workspace="suse", cwd=Path("/workspace/project"), entrypoint="/usr/local/bin/opencode"
        )
        == "ai-container: suse (opencode)"
    )
    assert (
        terminal.title_for(workspace=None, cwd=Path("/workspace/project"), entrypoint="/bin/bash")
        == "ai-container: project (bash)"
    )
