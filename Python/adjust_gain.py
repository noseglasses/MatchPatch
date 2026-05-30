#!/usr/bin/env python3
"""Compatibility wrapper for the historical Helix adjustment command."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "src"))

from matchpatch.normalize import main  # noqa: E402

if __name__ == "__main__":
    arguments = sys.argv[1:]

    if "--device" not in arguments:
        arguments = ["--device", "helix", *arguments]

    main(arguments)
