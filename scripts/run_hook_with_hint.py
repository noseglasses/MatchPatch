#!/usr/bin/env python3
"""Run a hook command and print a repair hint when it fails."""

from __future__ import annotations

import argparse
import subprocess
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hint", required=True, help="Command line to suggest after failure.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to execute.")
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required")
    return args


def main() -> int:
    args = parse_args()
    result = subprocess.run(args.command, check=False)
    if result.returncode != 0:
        print(
            f"\nHint: try this command to reproduce or fix the failure:\n  {args.hint}",
            file=sys.stderr,
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
