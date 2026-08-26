#!/usr/bin/env python3
"""Fail if source files hardcode secret/config-shaped constants instead of loading them from env.

Catches the class of bug generic secret scanners miss: a low-entropy,
no-known-prefix value (e.g. a GCP project id) assigned to a module-level
constant whose *name* gives away what it is. See ``ai_container/mounts.py``
history for the incident this guards against.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

KEYWORDS = (
    "project",
    "account",
    "tenant",
    "org",
    "subscription",
    "key",
    "secret",
    "token",
    "password",
    "credential",
    "client_id",
)
ALLOW_COMMENT = "# allow-hardcoded"
SRC_DIR = Path(__file__).resolve().parent.parent / "src"


def _is_flagged_name(name: str) -> bool:
    lowered = name.lower()
    return name.isupper() and any(keyword in lowered for keyword in KEYWORDS)


def check_file(path: Path) -> list[str]:
    source = path.read_text()
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    findings: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        if not node.value.value:
            continue
        line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
        if ALLOW_COMMENT in line:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and _is_flagged_name(target.id):
                findings.append(
                    f"{path}:{node.lineno}: {target.id} looks like config/secret data hardcoded "
                    f"as a string literal; load it from the environment instead "
                    f"(or add `{ALLOW_COMMENT}` if this is a deliberate exception)"
                )
    return findings


def main() -> int:
    findings = [f for path in sorted(SRC_DIR.rglob("*.py")) for f in check_file(path)]
    for finding in findings:
        print(finding, file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
