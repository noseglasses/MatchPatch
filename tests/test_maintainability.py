from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import matchpatch

assert matchpatch is not None


def load_maintainability_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_maintainability.py"
    spec = importlib.util.spec_from_file_location("check_maintainability", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_maintainability_budgets_pass() -> None:
    checker = load_maintainability_script()

    findings = checker.run_checks()

    assert findings == []
