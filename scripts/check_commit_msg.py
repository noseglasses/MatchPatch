#!/usr/bin/env python3
"""Validate commit messages against the Conventional Commits format."""

from __future__ import annotations

import re
import sys
from pathlib import Path

HEADER_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\([a-z0-9][a-z0-9._-]*\))?(?P<breaking>!)?: (?P<subject>\S.*)$"
)
ALLOWED_TYPES = {
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "style",
    "test",
}
IGNORED_PREFIXES = (
    "Merge ",
    "Revert ",
)


def _first_meaningful_line(message: str) -> str:
    for line in message.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def validate_subject(subject: str) -> str | None:
    if subject.startswith(("fixup! ", "squash! ")):
        subject = subject.split("! ", 1)[1]

    if subject.startswith(IGNORED_PREFIXES):
        return None

    match = HEADER_RE.fullmatch(subject)
    if match is None:
        return "Use '<type>[optional scope][!]: <description>'."

    commit_type = match.group("type")
    if commit_type not in ALLOWED_TYPES:
        allowed = ", ".join(sorted(ALLOWED_TYPES))
        return f"Unknown type '{commit_type}'. Allowed types: {allowed}."

    return None


def validate_message(message: str) -> str | None:
    subject = _first_meaningful_line(message)
    if not subject:
        return "Commit message is empty."
    return validate_subject(subject)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("Usage: check_commit_msg.py <commit-msg-file>", file=sys.stderr)
        return 2

    message_path = Path(argv[0])
    error = validate_message(message_path.read_text(encoding="utf-8"))
    if error is None:
        return 0

    print("Invalid commit message.", file=sys.stderr)
    print(error, file=sys.stderr)
    print(file=sys.stderr)
    print("Examples:", file=sys.stderr)
    print("  feat(gui): add snapshot diff selector", file=sys.stderr)
    print("  fix: preserve adjusted setlist output path", file=sys.stderr)
    print("  chore(release): v0.2.0", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
