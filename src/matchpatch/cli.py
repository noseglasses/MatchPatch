"""Command-line entry point for MatchPatch."""

from __future__ import annotations

import argparse
import platform
import sys

from matchpatch import __version__
from matchpatch.config import export_default_config
from matchpatch.devices import list_device_profiles


def print_environment() -> None:
    print(f"MatchPatch {__version__}")
    print(f"Platform: {platform.platform()}")
    print(f"Python  : {sys.executable}")


def print_devices() -> None:
    for profile in list_device_profiles():
        print(f"{profile.name}\t{profile.display_name}")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "normalize":
        from matchpatch.normalize import main as normalize_main

        normalize_main(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(description="Normalize gain across audio processor presets")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--environment",
        action="store_true",
        help="Print the Python environment used for this invocation",
    )
    parser.add_argument(
        "--devices",
        action="store_true",
        help="List supported audio processor profiles",
    )
    parser.add_argument(
        "--export-default-config",
        metavar="PATH",
        help="Write a TOML configuration file populated with MatchPatch defaults",
    )
    args = parser.parse_args()

    if args.export_default_config:
        path = export_default_config(args.export_default_config)
        print(f"Wrote default config: {path}")
    elif args.environment:
        print_environment()
    elif args.devices:
        print_devices()
    else:
        parser.print_help()
        print("\nNormalization command:")
        print("  matchpatch normalize --device DEVICE --input PATCH_FILE [options]")


if __name__ == "__main__":  # pragma: no cover - console script entry point
    main()
