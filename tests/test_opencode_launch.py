from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("attach", [False, True])
def test_launch_waits_for_server_forwards_args_and_cleans_up(tmp_path: Path, attach: bool) -> None:
    command = tmp_path / "opencode"
    calls = tmp_path / "calls"
    stopped = tmp_path / "stopped"
    command.write_text("""#!/bin/bash
printf '%s\\n' "$*" >> "$TEST_CALLS"
if [ "$1" = serve ]; then
    trap 'touch "$TEST_STOPPED"; exit 0' TERM
    while true; do sleep 0.05; done
elif [ "${3:-}" = api ]; then
    exit 0
else
    exit 7
fi
""")
    command.chmod(0o700)
    script = Path(__file__).resolve().parents[1] / "opencode/launch.sh"
    result = subprocess.run(
        ["bash", str(script), "--session", "test-session"],
        env={
            **os.environ,
            "AI_CONTAINER_OPENCODE_COMMAND": str(command),
            "AI_CONTAINER_OPENCODE_PORT": "4996",
            "TEST_CALLS": str(calls),
            "TEST_STOPPED": str(stopped),
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "AI_CONTAINER_OPENCODE_ATTACH": str(attach).lower(),
        },
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 7
    invocations = calls.read_text().splitlines()
    assert ("serve --hostname 0.0.0.0 --port 4996" in invocations) is not attach
    assert "--server http://127.0.0.1:4996 api get /api/info" in invocations
    assert invocations[-1] == "--server http://127.0.0.1:4996 --session test-session"
    assert stopped.exists() is not attach


def test_launch_reports_server_startup_failure(tmp_path: Path) -> None:
    command = tmp_path / "opencode"
    command.write_text("""#!/bin/bash
if [ "$1" = serve ]; then
    echo 'server startup failed' >&2
    exit 1
fi
sleep 0.1
exit 1
""")
    command.chmod(0o700)
    script = Path(__file__).resolve().parents[1] / "opencode/launch.sh"
    result = subprocess.run(
        ["bash", str(script)],
        env={
            **os.environ,
            "AI_CONTAINER_OPENCODE_COMMAND": str(command),
            "AI_CONTAINER_OPENCODE_PORT": "4996",
            "AI_CONTAINER_OPENCODE_ATTACH": "false",
            "XDG_STATE_HOME": str(tmp_path / "state"),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1
    assert "server startup failed" in result.stderr
