"""Backward-compatible entry point for Helix preset handling."""

from matchpatch.devices.line6.helix.preset_handling import *  # noqa: F403
from matchpatch.devices.line6.helix.preset_handling import main

if __name__ == "__main__":
    main()
