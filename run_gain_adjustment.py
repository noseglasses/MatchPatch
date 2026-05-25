#!/usr/bin/env python3

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
IO_SCRIPT = SCRIPT_DIR / "IO_to_reamp.py"
HELIX_SCRIPT = SCRIPT_DIR / "HelixAnalyzeSet.lua"
DEFAULT_PROJECT = SCRIPT_DIR / "Auto_Pegelsetup.rpp"
DEFAULT_REAPER_EXE = Path(
    "/mnt/c/Program Files/REAPER (x64)/reaper.exe"
)


def run_command(args, env=None, capture=False):
    return subprocess.run(
        [str(arg) for arg in args],
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None
    )


def wsl_path_to_windows(path):
    completed = run_command(
        ["wslpath", "-w", Path(path).resolve()],
        capture=True
    )

    return completed.stdout.strip()


def add_windows_env_bridge(env, names):
    existing = [
        item
        for item in env.get("WSLENV", "").split(":")
        if item
    ]

    existing_names = {
        item.split("/", 1)[0]
        for item in existing
    }

    for name in names:
        if name not in existing_names:
            existing.append(f"{name}/w")

    env["WSLENV"] = ":".join(existing)


def read_preset_assignments(input_path):
    completed = run_command(
        [
            sys.executable,
            IO_SCRIPT,
            "-i",
            input_path,
            "--list-presets"
        ],
        capture=True
    )

    return json.loads(completed.stdout)


def wait_for_done(done_path, timeout_seconds, process=None):
    start = time.monotonic()

    while True:
        if done_path.exists():
            return

        if process is not None:
            return_code = process.poll()

            if return_code not in (None, 0):
                raise RuntimeError(
                    "REAPER exited before analysis "
                    f"finished: {return_code}"
                )

        if timeout_seconds is not None:
            elapsed = time.monotonic() - start

            if elapsed > timeout_seconds:
                raise TimeoutError(
                    "Timed out waiting for REAPER "
                    "gain analysis to finish"
                )

        time.sleep(1.0)


def count_csv_rows(csv_path):
    if not csv_path.exists():
        return 0

    with csv_path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return sum(1 for _ in csv.DictReader(f))


def run_reaper_analysis(
    preset_ids,
    csv_path,
    done_path,
    reaper_exe,
    project_path,
    timeout_seconds
):
    env = os.environ.copy()
    env["HELIX_PRESET_SET"] = ",".join(
        str(preset_id) for preset_id in preset_ids
    )
    env["HELIX_CSV_PATH"] = wsl_path_to_windows(csv_path)
    env["HELIX_DONE_PATH"] = wsl_path_to_windows(done_path)

    add_windows_env_bridge(
        env,
        [
            "HELIX_PRESET_SET",
            "HELIX_CSV_PATH",
            "HELIX_DONE_PATH"
        ]
    )

    command = [
        reaper_exe,
        "-newinst",
        "-nosplash"
    ]

    if project_path:
        command.append(wsl_path_to_windows(project_path))

    command.append(
        wsl_path_to_windows(HELIX_SCRIPT)
    )

    process = subprocess.Popen(
        [str(arg) for arg in command],
        env=env
    )

    try:
        wait_for_done(
            done_path,
            timeout_seconds,
            process
        )
    finally:
        process.poll()


def apply_gain_csv(input_path, output_path, csv_path):
    run_command(
        [
            sys.executable,
            IO_SCRIPT,
            "-i",
            input_path,
            "-o",
            output_path,
            "--adjust-gain",
            "-g",
            csv_path
        ]
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Analyze non-default Helix presets "
            "via REAPER and write a gain-adjusted HLS"
        )
    )

    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input .hls file"
    )

    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output .hls file to create"
    )

    parser.add_argument(
        "--reaper-exe",
        default=os.getenv(
            "REAPER_EXE",
            str(DEFAULT_REAPER_EXE)
        ),
        help="WSL path to Windows reaper.exe"
    )

    parser.add_argument(
        "--project",
        default=os.getenv(
            "REAPER_PROJECT",
            str(DEFAULT_PROJECT)
        ),
        help="REAPER project to open before running the script"
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Maximum seconds to wait for REAPER analysis"
    )

    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        help=(
            "Only analyze the first N presets "
            "from the detected preset list"
        )
    )

    return parser.parse_args()


def main():
    args = parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    reaper_exe = Path(args.reaper_exe)
    project_path = (
        Path(args.project).resolve()
        if args.project
        else None
    )

    assignments = read_preset_assignments(
        input_path
    )

    preset_ids = [
        assignment["id"]
        for assignment in assignments
    ]

    if args.limit is not None:
        if args.limit < 1:
            raise ValueError(
                "-n/--limit must be at least 1"
            )

        preset_ids = preset_ids[:args.limit]

    if not preset_ids:
        raise ValueError(
            "Input HLS contains no non-default presets"
        )

    with tempfile.TemporaryDirectory(
        prefix="helix_gain_",
        dir=SCRIPT_DIR
    ) as temp_dir:
        temp_dir = Path(temp_dir)
        csv_path = temp_dir / "gain_correction.csv"
        done_path = temp_dir / "analysis.done"

        print(
            "Preset set: " +
            ",".join(str(preset_id) for preset_id in preset_ids)
        )
        print(f"Temp CSV  : {csv_path}")

        run_reaper_analysis(
            preset_ids,
            csv_path,
            done_path,
            reaper_exe,
            project_path,
            args.timeout
        )

        measured_rows = count_csv_rows(
            csv_path
        )

        if measured_rows != len(preset_ids):
            raise RuntimeError(
                "REAPER finished, but CSV contains "
                f"{measured_rows} rows for "
                f"{len(preset_ids)} presets"
            )

        apply_gain_csv(
            input_path,
            output_path,
            csv_path
        )

    print()
    print("[OK] Gain-adjusted HLS written")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, file=sys.stdout)

        if exc.stderr:
            print(exc.stderr, file=sys.stderr)

        sys.exit(exc.returncode)

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
