#!/usr/bin/env python3

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import time
import shutil
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
REAPER_DIR = PROJECT_DIR / "Reaper"

IO_SCRIPT = SCRIPT_DIR / "hls_adjust.py"
HELIX_SCRIPT = REAPER_DIR / "HelixAnalyzeSet.lua"
DEFAULT_PROJECT = REAPER_DIR / "Auto_Pegelsetup.rpp"
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


def check_reaper_not_running():
    completed = subprocess.run(
        [
            "/mnt/c/Windows/System32/tasklist.exe",
            "/FI",
            "IMAGENAME eq reaper.exe"
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "Could not check whether REAPER is running: "
            + completed.stderr.decode(
                "utf-8",
                errors="replace"
            ).strip()
        )

    if b"reaper.exe" in completed.stdout.lower():
        raise RuntimeError(
            "REAPER is already running. "
            "Please close any running REAPER instances "
            "before starting gain adjustment."
        )


def helix_preset_to_id(value):
    text = value.strip().upper()

    if len(text) < 2:
        raise ValueError(
            f"Invalid Helix preset ID: {value}"
        )

    bank_text = text[:-1]
    slot_text = text[-1]

    if not bank_text.isdigit() or slot_text not in "ABCD":
        raise ValueError(
            f"Invalid Helix preset ID: {value}"
        )

    bank = int(bank_text)

    if bank < 1:
        raise ValueError(
            f"Invalid Helix preset ID: {value}"
        )

    return (bank - 1) * 4 + "ABCD".index(slot_text) + 1


def id_to_helix_preset(preset_id):
    zero_based = preset_id - 1
    bank = zero_based // 4 + 1
    slot = "ABCD"[zero_based % 4]

    return f"{bank:02d}{slot}"


def parse_helix_preset_set(value):
    preset_ids = []
    seen = set()

    for token in value.split(","):
        token = token.strip()

        if not token:
            raise ValueError(
                "Empty entry in -S/--preset-set"
            )

        preset_id = helix_preset_to_id(token)

        if preset_id not in seen:
            preset_ids.append(preset_id)
            seen.add(preset_id)

    if not preset_ids:
        raise ValueError(
            "-S/--preset-set did not contain presets"
        )

    return preset_ids


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


def close_reaper_process(process, timeout_seconds=10.0):
    if process.poll() is not None:
        return

    try:
        process.wait(timeout=timeout_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    process.terminate()

    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_seconds)


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
    env["HELIX_QUIT_WHEN_DONE"] = "1"

    check_reaper_not_running()

    add_windows_env_bridge(
        env,
        [
            "HELIX_PRESET_SET",
            "HELIX_CSV_PATH",
            "HELIX_DONE_PATH",
            "HELIX_QUIT_WHEN_DONE"
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
        close_reaper_process(process)


def apply_gain_csv(
    input_path,
    output_path,
    csv_path,
    ignore_bad_lufs=False
):
    command = [
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

    if ignore_bad_lufs:
        command.append("--ignore-bad-lufs")

    run_command(command)


def run_reamp_conversion(input_path, output_path):
    run_command(
        [
            sys.executable,
            IO_SCRIPT,
            "-i",
            input_path,
            "-o",
            output_path,
            "-r"
        ]
    )


def synthesize_helix_path(input_path, postfix):
    if input_path.suffix.lower() not in [".hls", ".hlx"]:
        raise ValueError(
            "Automation mode requires an .hls or .hlx input file"
        )

    return input_path.with_name(
        input_path.stem + postfix + input_path.suffix
    )


def wait_for_user_confirmation(message):
    print()
    print(message)
    input("Press Enter to continue...")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Analyze non-default Helix presets "
            "via REAPER and write a gain-adjusted HLS/HLX"
        )
    )

    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input .hls or .hlx file"
    )

    parser.add_argument(
        "-o",
        "--output",
        help="Output .hls or .hlx file to create"
    )

    parser.add_argument(
        "-a",
        "--automation",
        action="store_true",
        help=(
            "Run the complete workflow: create "
            "*_reamp.hls/.hlx, wait for Helix import, "
            "measure, create *_adjusted.hls/.hlx, and "
            "request final Helix import"
        )
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

    parser.add_argument(
        "-S",
        "--preset-set",
        help=(
            "Comma-separated Helix preset IDs "
            "to analyze, e.g. 01B,02A,16D"
        )
    )

    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help=(
            "Keep the temporary LUFS analysis CSV "
            "and completion marker for debugging"
        )
    )

    parser.add_argument(
        "--ignore-bad-lufs",
        action="store_true",
        help=(
            "Skip implausible LUFS-derived gain values "
            "when writing the adjusted HLS"
        )
    )

    return parser.parse_args()


def main():
    args = parse_args()

    input_path = Path(args.input).resolve()
    input_ext = input_path.suffix.lower()
    requested_ids = None

    if input_ext not in [".hls", ".hlx"]:
        raise ValueError(
            "Input must be an .hls or .hlx file"
        )

    if args.preset_set:
        requested_ids = parse_helix_preset_set(
            args.preset_set
        )

    if input_ext == ".hlx":
        if requested_ids is None:
            raise ValueError(
                "When input is an .hlx preset file, "
                "-S/--preset-set is required and must contain "
                "exactly one Helix preset ID, e.g. -S 12A. "
                "This tells REAPER which imported Helix preset "
                "slot to analyze."
            )

        if len(requested_ids) != 1:
            raise ValueError(
                "When input is an .hlx preset file, "
                "-S/--preset-set must contain exactly one "
                "Helix preset ID."
            )

    if args.automation:
        if args.output:
            raise ValueError(
                "-o/--output must not be specified "
                "when -a/--automation is used"
            )

        reamp_path = synthesize_helix_path(
            input_path,
            "_reamp"
        )
        output_path = synthesize_helix_path(
            input_path,
            "_adjusted"
        )

        print(
            f"Creating reamp file: {reamp_path}"
        )

        run_reamp_conversion(
            input_path,
            reamp_path
        )

        wait_for_user_confirmation(
            "Please import this reamp file on the Helix:\n"
            f"{reamp_path}"
        )

    else:
        if not args.output:
            raise ValueError(
                "-o/--output is required unless "
                "-a/--automation is used"
            )

        output_path = Path(args.output).resolve()

        if input_ext == ".hlx" and output_path.suffix.lower() != ".hlx":
            raise ValueError(
                "Output must be an .hlx file when input is .hlx"
            )

        if input_ext == ".hls" and output_path.suffix.lower() != ".hls":
            raise ValueError(
                "Output must be an .hls file when input is .hls"
            )

    reaper_exe = Path(args.reaper_exe)
    project_path = (
        Path(args.project).resolve()
        if args.project
        else None
    )

    assignments = read_preset_assignments(
        input_path
    )

    available_ids = {
        assignment["id"]
        for assignment in assignments
    }

    if input_ext == ".hlx":
        preset_ids = requested_ids

    else:
        preset_ids = [
            assignment["id"]
            for assignment in assignments
        ]

    if input_ext == ".hls" and requested_ids is not None:

        missing_ids = [
            preset_id
            for preset_id in requested_ids
            if preset_id not in available_ids
        ]

        if missing_ids:
            missing = ",".join(
                id_to_helix_preset(preset_id)
                for preset_id in missing_ids
            )

            raise ValueError(
                "Requested presets are not present "
                f"or are named New Preset: {missing}"
            )

        requested = set(requested_ids)
        preset_ids = [
            preset_id
            for preset_id in preset_ids
            if preset_id in requested
        ]

    if args.limit is not None:
        if args.limit < 1:
            raise ValueError(
                "-n/--limit must be at least 1"
            )

        preset_ids = preset_ids[:args.limit]

    if not preset_ids:
        raise ValueError(
            "Input file contains no non-default presets"
        )

    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="helix_gain_",
            dir=PROJECT_DIR
        )
    )

    success = False

    try:
        temp_dir = Path(temp_dir)
        csv_path = temp_dir / "lufs_analysis.csv"
        done_path = temp_dir / "analysis.done"

        print(
            "Preset set: " +
            ",".join(str(preset_id) for preset_id in preset_ids)
        )
        print(
            "Helix IDs : " +
            ",".join(
                id_to_helix_preset(preset_id)
                for preset_id in preset_ids
            )
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
            csv_path,
            args.ignore_bad_lufs
        )

        success = True

    finally:
        if args.keep_temp or not success:
            print(f"Kept temp : {temp_dir}")
        else:
            shutil.rmtree(
                temp_dir,
                ignore_errors=True
            )

    print()
    print("[OK] Gain-adjusted Helix file written")
    print(f"Output: {output_path}")

    if args.automation:
        wait_for_user_confirmation(
            "Please import this adjusted file on the Helix "
            "to complete the adjustment procedure:\n"
            f"{output_path}"
        )


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
