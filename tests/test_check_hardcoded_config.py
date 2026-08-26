from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "check_hardcoded_config.py"
_spec = importlib.util.spec_from_file_location("check_hardcoded_config", _SCRIPT_PATH)
assert _spec and _spec.loader
check_hardcoded_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_hardcoded_config)


def test_flags_hardcoded_project_constant(tmp_path: Path) -> None:
    module = tmp_path / "mod.py"
    module.write_text('PROJECT = "REDACTED-GCP-PROJECT"\n')
    findings = check_hardcoded_config.check_file(module)
    assert len(findings) == 1
    assert "PROJECT" in findings[0]


def test_allows_env_loaded_value(tmp_path: Path) -> None:
    module = tmp_path / "mod.py"
    module.write_text('import os\nPROJECT = os.environ.get("PROJECT")\n')
    assert check_hardcoded_config.check_file(module) == []


def test_allows_non_string_constant(tmp_path: Path) -> None:
    module = tmp_path / "mod.py"
    module.write_text("TIMEOUT = 30\n")
    assert check_hardcoded_config.check_file(module) == []


def test_allows_unrelated_constant_name(tmp_path: Path) -> None:
    module = tmp_path / "mod.py"
    module.write_text('CONTAINER_HOME = "/home/coder"\n')
    assert check_hardcoded_config.check_file(module) == []


def test_escape_hatch_comment_suppresses_finding(tmp_path: Path) -> None:
    module = tmp_path / "mod.py"
    module.write_text('PROJECT = "REDACTED-GCP-PROJECT"  # allow-hardcoded\n')
    assert check_hardcoded_config.check_file(module) == []


def test_ignores_nested_assignment(tmp_path: Path) -> None:
    module = tmp_path / "mod.py"
    module.write_text('def f():\n    SECRET = "abc"\n    return SECRET\n')
    assert check_hardcoded_config.check_file(module) == []


def test_current_source_tree_is_clean() -> None:
    findings = [
        finding
        for path in sorted(check_hardcoded_config.SRC_DIR.rglob("*.py"))
        for finding in check_hardcoded_config.check_file(path)
    ]
    assert findings == []


def test_main_returns_zero_for_clean_tree() -> None:
    assert check_hardcoded_config.main() == 0
