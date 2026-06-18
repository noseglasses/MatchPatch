"""Command-line entry point for MatchPatch."""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

from matchpatch import __version__
from matchpatch.config import export_default_config
from matchpatch.devices import get_device_profile, list_device_profiles


def print_environment() -> None:
    print(f"MatchPatch {__version__}")
    print(f"Platform: {platform.platform()}")
    print(f"Python  : {sys.executable}")


def print_devices() -> None:
    for profile in list_device_profiles():
        print(f"{profile.name}\t{profile.display_name}")


def _parse_preset_set(device: str, value: str | None) -> list[int] | None:
    if value is None:
        return None
    profile = get_device_profile(device)
    handler = profile.create_patch_file_handler(Path(__file__).resolve().parents[2])
    return handler.parse_patch_set(value)


def _run_files_command(args: argparse.Namespace) -> None:
    from matchpatch import file_operations

    if args.files_command == "join":
        slot_ids = _parse_preset_set(args.device, args.preset_set)
        result = file_operations.join_preset_files(
            args.device,
            [Path(path) for path in args.preset_files],
            Path(args.output),
            slot_ids=slot_ids,
        )
        print(f"Joined {len(args.preset_files)} preset files into {result.output_path}")
        return

    if args.files_command == "split":
        selected_ids = _parse_preset_set(args.device, args.preset_set)
        result = file_operations.split_setlist_file(
            args.device,
            Path(args.input),
            Path(args.output_dir),
            selected_ids=selected_ids,
        )
        print(f"Split {len(result.created_paths)} preset files into {Path(args.output_dir)}")
        for path in result.created_paths:
            print(path)
        return

    raise ValueError(f"Unsupported files command: {args.files_command}")


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "normalize":
        from matchpatch.normalize import main as normalize_main

        normalize_main(args[1:])
        return
    if args and args[0] == "measure":
        from matchpatch.measure import main as measure_main

        measure_main(args[1:])
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
    subparsers = parser.add_subparsers(dest="command")
    files_parser = subparsers.add_parser("files", help="Run processor file operations")
    files_subparsers = files_parser.add_subparsers(dest="files_command", required=True)

    join_parser = files_subparsers.add_parser("join", help="Join preset files into a setlist")
    join_parser.add_argument("--device", required=True, help="Audio processor profile")
    join_parser.add_argument("--output", required=True, help="Output setlist path")
    join_parser.add_argument(
        "--preset-set",
        help="Comma-separated destination slots, for example 01A,01B",
    )
    join_parser.add_argument("preset_files", nargs="+", help="Input preset files")

    split_parser = files_subparsers.add_parser("split", help="Split a setlist into preset files")
    split_parser.add_argument("--device", required=True, help="Audio processor profile")
    split_parser.add_argument("--input", required=True, help="Input setlist path")
    split_parser.add_argument("--output-dir", required=True, help="Directory for preset files")
    split_parser.add_argument(
        "--preset-set",
        help="Comma-separated setlist slots to export, for example 01A,01B",
    )
    args = parser.parse_args(args)

    if args.command == "files":
        _run_files_command(args)
    elif args.export_default_config:
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
