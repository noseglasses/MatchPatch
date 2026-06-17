#!/usr/bin/env python3
"""Check coarse maintainability budgets for file size and complexity."""

from __future__ import annotations

import ast
import fnmatch
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LINE_LIMITS: tuple[tuple[str, int], ...] = (
    ("src/matchpatch/gui/main_window.py", 2500),
    ("tests/test_gui.py", 1600),
    ("src/matchpatch/devices/helix_preset_handling.py", 2000),
    ("src/matchpatch/gui/*.py", 2000),
    ("src/matchpatch/**/*.py", 2000),
    ("tests/test_*.py", 1600),
    ("scripts/*.py", 800),
)

MAX_CYCLOMATIC_COMPLEXITY = 10
COMPLEXITY_PATHS = ("src/matchpatch/**/*.py", "scripts/*.py", "tests/**/*.py")


@dataclass(frozen=True)
class Finding:
    path: str
    message: str


class ComplexityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.complexity = 1

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:  # noqa: N802
        self.complexity += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:  # noqa: N802
        self.complexity += 1
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.complexity += 1 + len(node.ifs)
        self.generic_visit(node)


def tracked_python_files() -> list[Path]:
    files: set[Path] = set()
    for pattern in (*[pattern for pattern, _ in LINE_LIMITS], *COMPLEXITY_PATHS):
        files.update(ROOT.glob(pattern))
    return sorted(path for path in files if path.is_file())


def relative_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def line_limit_for(path: Path) -> int | None:
    relative = relative_path(path)
    for pattern, limit in LINE_LIMITS:
        if fnmatch.fnmatchcase(relative, pattern):
            return limit
    return None


def check_file_sizes(files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        limit = line_limit_for(path)
        if limit is None:
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > limit:
            findings.append(
                Finding(
                    relative_path(path),
                    f"{line_count} lines exceeds the {limit}-line budget",
                )
            )
    return findings


def path_has_complexity_budget(path: Path) -> bool:
    relative = relative_path(path)
    return any(fnmatch.fnmatchcase(relative, pattern) for pattern in COMPLEXITY_PATHS)


def function_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    visitor = ComplexityVisitor()
    for child in node.body:
        visitor.visit(child)
    return visitor.complexity


def function_nodes(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def check_complexity(files: list[Path]) -> list[Finding]:
    paths = [relative_path(path) for path in files if path_has_complexity_budget(path)]
    if not paths:
        return []
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "C901",
            *paths,
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 0:
        return []
    detail = (result.stdout or result.stderr).strip().splitlines()[0]
    return [
        Finding(
            ",".join(COMPLEXITY_PATHS),
            f"Ruff C901 max complexity {MAX_CYCLOMATIC_COMPLEXITY} failed: {detail}",
        )
    ]


def run_checks() -> list[Finding]:
    files = tracked_python_files()
    return [*check_file_sizes(files), *check_complexity(files)]


def main() -> int:
    findings = run_checks()
    if not findings:
        print("Maintainability budgets passed.")
        return 0

    print("Maintainability budgets failed:")
    for finding in findings:
        print(f"  {finding.path}: {finding.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
