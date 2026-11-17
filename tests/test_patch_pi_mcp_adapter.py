from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "patch_pi_mcp_adapter.py"
_spec = importlib.util.spec_from_file_location("patch_pi_mcp_adapter", _SCRIPT_PATH)
assert _spec and _spec.loader
patch_pi_mcp_adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(patch_pi_mcp_adapter)

STOCK = (
    'import { registerProtocolBridge } from "./runtime-protocol.ts";\n'
    "\n"
    "function attempt(): void {\n"
    '      void import("./pi-builtin-mcp.ts")\n'
    "        .then(({ turnOffPiBuiltinMcp }) => turnOffPiBuiltinMcp())\n"
    "        .then((turnedOff) => report(turnedOff));\n"
    "}\n"
)


def test_patches_both_hunks() -> None:
    patched, status = patch_pi_mcp_adapter.patch(STOCK)
    assert status == "patched"
    assert patched.startswith(patch_pi_mcp_adapter.STATIC_IMPORT)
    assert "void turnOffPiBuiltinMcp()\n" in patched
    assert 'import("./pi-builtin-mcp.ts")' not in patched


def test_patch_is_idempotent() -> None:
    once, _ = patch_pi_mcp_adapter.patch(STOCK)
    twice, status = patch_pi_mcp_adapter.patch(once)
    assert status == "nothing-to-do"
    assert twice == once


def test_unknown_shape_is_left_untouched() -> None:
    source = "export const x = 1;\n"
    assert patch_pi_mcp_adapter.patch(source) == (source, "unknown")


def test_main_rewrites_file_and_keeps_mode(tmp_path: Path) -> None:
    target = tmp_path / "index.ts"
    target.write_text(STOCK)
    target.chmod(0o644)
    assert patch_pi_mcp_adapter.main(["prog", str(target)]) == 0
    assert "void turnOffPiBuiltinMcp()" in target.read_text()
    assert target.stat().st_mode & 0o777 == 0o644
    assert patch_pi_mcp_adapter.main(["prog", str(target)]) == 1


def test_main_leaves_unknown_file_alone(tmp_path: Path) -> None:
    target = tmp_path / "index.ts"
    source = "export const x = 1;\n"
    target.write_text(source)
    assert patch_pi_mcp_adapter.main(["prog", str(target)]) == 2
    assert target.read_text() == source


def test_main_requires_exactly_one_path(capsys: object) -> None:
    assert patch_pi_mcp_adapter.main(["prog"]) == 2
