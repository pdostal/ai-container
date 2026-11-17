#!/usr/bin/env python3
"""Point pi-mcp-adapter's built-in-MCP turn-off at a static import.

Pi loads .ts extensions through jiti with ``moduleCache: false``, so the adapter's
runtime ``import("./pi-builtin-mcp.ts")`` re-executes that module in a fresh graph
whose cross-module named imports come back undefined, which throws
``Cannot read properties of undefined (reading 'getAgentPath')`` on every start.

Exit codes: 0 patched, 1 nothing to do, 2 unrecognised file (left untouched).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

STATIC_IMPORT = 'import { turnOffPiBuiltinMcp } from "./pi-builtin-mcp.ts";\n'
STATIC_MARKER = 'from "./pi-builtin-mcp.ts"'
DYNAMIC = (
    '      void import("./pi-builtin-mcp.ts")\n'
    "        .then(({ turnOffPiBuiltinMcp }) => turnOffPiBuiltinMcp())\n"
)
DIRECT = "      void turnOffPiBuiltinMcp()\n"


def patch(source: str) -> tuple[str, str]:
    """Return the patched source and a status: patched, nothing-to-do or unknown."""
    if DYNAMIC not in source:
        return source, "nothing-to-do" if STATIC_MARKER in source else "unknown"
    patched = source.replace(DYNAMIC, DIRECT, 1)
    if STATIC_MARKER not in patched:
        patched = STATIC_IMPORT + patched
    return patched, "patched"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <pi-mcp-adapter index.ts>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    patched, status = patch(path.read_text())
    if status == "unknown":
        print(f"{path}: unrecognised shape, left untouched", file=sys.stderr)
        return 2
    if status == "nothing-to-do":
        return 1
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(patched)
    tmp.chmod(path.stat().st_mode)
    tmp.replace(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
