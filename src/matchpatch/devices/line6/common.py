"""Common Line 6 device primitives."""

from __future__ import annotations

import contextlib
import csv
import io
import json
import re
import runpy
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from types import TracebackType

from matchpatch.devices.base import (
    AudioRouting,
    DeviceController,
    DeviceFileKind,
    DeviceProfile,
    DeviceSettingDescriptor,
    DeviceTerminology,
    FileOperationCapabilities,
    GainPoint,
    NamingRules,
    NormalizationPolicy,
    PatchAssignment,
    PatchFileAdjustments,
    PatchFileHandler,
    SteeringOptions,
)
from matchpatch.devices.line6 import file_ops
from matchpatch.midi import midi_output_names

LINE6_NAME_PATTERN = re.compile(r"""^[A-Za-z0-9\-_+=!@#$&()?:'",./ ]*$""")
LINE6_NAME_CHAR_PATTERN = re.compile(r"""[A-Za-z0-9\-_+=!@#$&()?:'",./ ]""")
LINE6_REDUNDANT_PANEL_SETTINGS = frozenset({"preset_wait", "snapshot_wait", "measurement_wait"})


class Line6PatchFileHandler(PatchFileHandler):
    display_name = "Line 6"
    module = ""
    preset_extension = ""
    setlist_extension = ""
    assignment_patch_key = "device_patch"

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir
        self.log_callback: Callable[[str], None] | None = None

    def set_log_callback(self, callback: Callable[[str], None] | None) -> None:
        self.log_callback = callback

    def _run(
        self,
        *args: object,
        capture: bool = False,
        log_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if getattr(sys, "frozen", False):
            return self._run_in_process(*args, capture=capture, log_output=log_output)

        should_capture = capture or self.log_callback is not None

        try:
            completed = subprocess.run(
                [sys.executable, "-m", self.module, *(str(arg) for arg in args)],
                check=True,
                text=True,
                stdout=subprocess.PIPE if should_capture else None,
                stderr=subprocess.PIPE if should_capture else None,
            )
        except subprocess.CalledProcessError as exc:
            if log_output:
                self._log_output(exc.stdout)
                self._log_output(exc.stderr)
            raise

        if log_output:
            self._log_output(completed.stdout)
            self._log_output(completed.stderr)
        return completed

    def _run_in_process(
        self,
        *args: object,
        capture: bool = False,
        log_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        should_capture = capture or self.log_callback is not None
        command = [self.module, *(str(arg) for arg in args)]
        original_argv = sys.argv
        stdout = io.StringIO()
        stderr = io.StringIO()
        sys.argv = [self.module, *(str(arg) for arg in args)]
        try:
            stdout_context = (
                contextlib.redirect_stdout(stdout) if should_capture else contextlib.nullcontext()
            )
            stderr_context = (
                contextlib.redirect_stderr(stderr) if should_capture else contextlib.nullcontext()
            )
            with stdout_context, stderr_context:
                try:
                    runpy.run_module(self.module, run_name="__main__")
                    returncode = 0
                except SystemExit as exc:
                    returncode = exc.code if isinstance(exc.code, int) else 1
        finally:
            sys.argv = original_argv

        output = stdout.getvalue() if should_capture else None
        error = stderr.getvalue() if should_capture else None
        completed = subprocess.CompletedProcess(command, returncode, stdout=output, stderr=error)
        if completed.returncode:
            exc = subprocess.CalledProcessError(
                completed.returncode,
                command,
                output=completed.stdout,
                stderr=completed.stderr,
            )
            if log_output:
                self._log_output(exc.stdout)
                self._log_output(exc.stderr)
            raise exc

        if log_output:
            self._log_output(completed.stdout)
            self._log_output(completed.stderr)
        return completed

    def _log_output(self, output: str | None) -> None:
        if self.log_callback is None or not output:
            return

        for line in output.splitlines():
            if line.strip():
                self.log_callback(line)

    def validate_input(self, input_path: Path) -> None:
        if input_path.suffix.lower() not in {self.setlist_extension, self.preset_extension}:
            raise ValueError(
                f"{self.display_name} input must be an {self.setlist_extension} "
                f"or {self.preset_extension} file"
            )

    def validate_output(self, input_path: Path, output_path: Path) -> None:
        if output_path.suffix.lower() != input_path.suffix.lower():
            raise ValueError(
                f"{self.display_name} output must use the {input_path.suffix.lower()} extension"
            )

    def list_assignments(self, input_path: Path) -> list[PatchAssignment]:
        completed = self._run("-i", input_path, "--list-presets", capture=True, log_output=False)
        return [
            PatchAssignment(
                id=assignment["id"],
                device_patch=assignment[self.assignment_patch_key],
                name=assignment["name"],
                snapshot_names=tuple(assignment.get("snapshot_names", ())),
                snapshot_output_paths=tuple(
                    str(path) for path in assignment.get("snapshot_output_paths", ())
                ),
                snapshot_output_levels=tuple(
                    tuple(float(level) for level in levels)
                    for levels in assignment.get("snapshot_output_levels", ())
                ),
                original_filename=(
                    input_path.name if input_path.suffix.lower() == self.preset_extension else None
                ),
                gain_points=_assignment_gain_points(assignment),
            )
            for assignment in json.loads(completed.stdout)
        ]

    def metadata(self, input_path: Path) -> dict[str, object]:
        completed = self._run("-i", input_path, "--metadata", capture=True, log_output=False)
        metadata = json.loads(completed.stdout)
        if not isinstance(metadata, dict):
            raise ValueError(f"{self.display_name} metadata output must be a JSON object")
        return metadata

    def file_capabilities(self) -> FileOperationCapabilities:
        return FileOperationCapabilities(
            reads_preset_files=True,
            writes_preset_files=True,
            reads_setlist_files=True,
            writes_setlist_files=True,
            joins_presets_to_setlist=True,
            splits_setlist_to_presets=True,
            exports_selected_setlist_slots=True,
        )

    def file_kind(self, path: Path) -> DeviceFileKind:
        suffix = path.suffix.lower()
        if suffix == self.preset_extension:
            return "preset"
        if suffix == self.setlist_extension:
            return "setlist"
        return "unknown"

    def join_preset_files(
        self,
        preset_paths: list[Path],
        output_path: Path,
        *,
        slot_ids: list[int] | None = None,
    ) -> None:
        if self.file_kind(output_path) != "setlist":
            raise ValueError(
                f"{self.display_name} join output must be an {self.setlist_extension} file: "
                f"{output_path}"
            )
        args: list[object] = ["--join-presets", *preset_paths, "-o", output_path]
        if slot_ids is not None:
            args.extend(
                ["--slot-ids", ",".join(self.format_patch_id(slot_id) for slot_id in slot_ids)]
            )
        self._run(*args)

    def split_setlist_file(
        self,
        input_path: Path,
        output_dir: Path,
        *,
        selected_ids: list[int] | None = None,
        original_filenames: Mapping[int, str] | None = None,
    ) -> list[Path]:
        if self.file_kind(input_path) != "setlist":
            raise ValueError(
                f"{self.display_name} split input must be an {self.setlist_extension} file: "
                f"{input_path}"
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        split_presets = self._file_operations().split_setlist_to_preset_data(
            input_path,
            selected_ids=selected_ids,
            original_filenames=original_filenames,
        )
        created_paths = []
        for filename, preset_data in split_presets:
            output_path = output_dir / Path(filename).name
            with output_path.open("w", encoding="utf-8") as preset_file:
                json.dump(preset_data, preset_file, indent=1)
            created_paths.append(output_path)
        return created_paths

    def diff_preset_ids(self, input_path: Path, previous_input_path: Path) -> list[int]:
        if previous_input_path.suffix.lower() != input_path.suffix.lower():
            raise ValueError(
                f"{self.display_name} diff input must use the same extension as the active "
                "input file"
            )

        completed = self._run(
            "-i",
            input_path,
            "--diff-presets",
            previous_input_path,
            capture=True,
            log_output=False,
        )
        diff_ids = json.loads(completed.stdout)
        if not isinstance(diff_ids, list) or not all(isinstance(item, int) for item in diff_ids):
            raise ValueError(f"{self.display_name} diff output must be a JSON array of preset IDs")
        return diff_ids

    def diff_snapshot_ids(
        self,
        input_path: Path,
        previous_input_path: Path,
        snapshot_count: int,
    ) -> dict[int, tuple[int, ...]]:
        if previous_input_path.suffix.lower() != input_path.suffix.lower():
            raise ValueError(
                f"{self.display_name} diff input must use the same extension as the active "
                "input file"
            )

        completed = self._run(
            "-i",
            input_path,
            "--diff-snapshots",
            previous_input_path,
            "--snapshot-count",
            snapshot_count,
            capture=True,
            log_output=False,
        )
        raw_plan = json.loads(completed.stdout)
        if not isinstance(raw_plan, dict):
            raise ValueError(f"{self.display_name} snapshot diff output must be a JSON object")
        result: dict[int, tuple[int, ...]] = {}
        for preset_id, snapshots in raw_plan.items():
            if not str(preset_id).isdigit() or not isinstance(snapshots, list):
                raise ValueError(
                    f"{self.display_name} snapshot diff output has an invalid preset entry"
                )
            if not all(isinstance(snapshot, int) for snapshot in snapshots):
                raise ValueError(
                    f"{self.display_name} snapshot diff output has an invalid snapshot list"
                )
            result[int(preset_id)] = tuple(snapshots)
        return result

    def parse_patch_set(self, value: str) -> list[int]:
        return file_ops.parse_banked_slot_set(value, device_name=self.display_name)

    def select_preset_ids(
        self,
        input_path: Path,
        assignments: list[PatchAssignment],
        requested_ids: list[int] | None,
    ) -> list[int]:
        if input_path.suffix.lower() == self.preset_extension:
            if requested_ids is None or len(requested_ids) != 1:
                raise ValueError(
                    f"{self.display_name} {self.preset_extension} input requires exactly one "
                    "--preset-set value, for example --preset-set 12A"
                )

            return requested_ids

        available_ids = {assignment.id for assignment in assignments}

        if requested_ids is None:
            return [assignment.id for assignment in assignments]

        missing_ids = [preset_id for preset_id in requested_ids if preset_id not in available_ids]

        if missing_ids:
            missing = ",".join(self.format_patch_id(preset_id) for preset_id in missing_ids)
            raise ValueError(
                f"Requested {self.display_name} presets are missing or empty: {missing}"
            )

        requested = set(requested_ids)
        return [assignment.id for assignment in assignments if assignment.id in requested]

    def format_patch_id(self, preset_id: int) -> str:
        return file_ops.banked_slot_label(preset_id - 1)

    def create_measurement_file(self, input_path: Path, output_path: Path) -> None:
        self._run("-i", input_path, "-o", output_path, "--measurement")

    def apply_analysis_csv(
        self,
        input_path: Path,
        output_path: Path,
        csv_path: Path,
        ignore_bad_lufs: bool,
        target_lufs: float,
        policy: NormalizationPolicy = NormalizationPolicy(),
        custom_adjustments_path: Path | None = None,
        adjustments: PatchFileAdjustments | None = None,
    ) -> None:
        legacy_csv_path = self._create_legacy_analysis_csv(csv_path)
        adjustments_path = None

        try:
            adjustments_path = self._create_adjustments_json(csv_path, adjustments)
            args: list[object] = [
                "-i",
                input_path,
                "-o",
                output_path,
                "--adjust-gain",
                "-g",
                legacy_csv_path,
                "--target-lufs",
                target_lufs,
                "--snapshot-count",
                policy.snapshot_count,
                "--solo-regex",
                policy.solo_regex,
                "--ignore-snapshot-regex",
                policy.ignore_snapshot_regex,
                "--solo-gain-bump-db",
                policy.solo_gain_bump_db,
                "--crest-factor-reference-db",
                policy.crest_factor_reference_db,
                "--crest-factor-correction-ratio",
                policy.crest_factor_correction_ratio,
                "--max-crest-factor-correction-db",
                policy.max_crest_factor_correction_db,
                "--gain-deadband-db",
                policy.gain_deadband_db,
            ]

            args.append("--ignore-bad-lufs")
            if custom_adjustments_path is not None:
                args.extend(["--custom-adjustments-file", custom_adjustments_path])
            if adjustments_path is not None:
                args.extend(["--manual-adjustments", adjustments_path])

            try:
                self._run(*args, capture=True)
            except subprocess.CalledProcessError as exc:
                details = _error_details(exc)
                message = f"{self.display_name} gain adjustment failed"
                if details:
                    message += f":\n{details}"
                raise RuntimeError(message) from exc
        finally:
            legacy_csv_path.unlink(missing_ok=True)
            if adjustments_path is not None:
                adjustments_path.unlink(missing_ok=True)

    def _create_legacy_analysis_csv(self, csv_path: Path) -> Path:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            fieldnames = [
                "Preset",
                "HelixPreset",
                *(
                    field
                    for field in reader.fieldnames or []
                    if field not in {"Preset", "DevicePatch", "HelixPreset"}
                ),
            ]
            temporary = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="",
                suffix=f".{self.name_for_temp_files}.csv",
                dir=csv_path.parent,
                delete=False,
            )

            with temporary:
                writer = csv.DictWriter(temporary, fieldnames=fieldnames)
                writer.writeheader()

                for row in reader:
                    row["HelixPreset"] = row["DevicePatch"]
                    writer.writerow({field: row.get(field, "") for field in fieldnames})

        return Path(temporary.name)

    @property
    def name_for_temp_files(self) -> str:
        return self.display_name.lower().replace(" ", "-")

    def _create_adjustments_json(
        self,
        csv_path: Path,
        adjustments: PatchFileAdjustments | None,
    ) -> Path | None:
        if adjustments is None:
            return None

        temporary = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".adjustments.json",
            dir=csv_path.parent,
            delete=False,
        )
        with temporary:
            json.dump(
                {
                    "preset_names": adjustments.preset_names,
                    "snapshot_names": adjustments.snapshot_names,
                    "gain_deltas": adjustments.gain_deltas,
                },
                temporary,
            )
        return Path(temporary.name)

    def automation_output_path(self, input_path: Path, postfix: str) -> Path:
        self.validate_input(input_path)
        return input_path.with_name(input_path.stem + postfix + input_path.suffix)

    def _file_operations(self):  # noqa: ANN202
        return file_ops


class Line6MidiController(DeviceController):
    display_name = "Line 6"
    max_snapshot_count = 8
    snapshot_cc = 69

    def __init__(self, options: SteeringOptions) -> None:
        self.options = options
        self.port = None

    def __enter__(self) -> "Line6MidiController":
        import mido

        names = midi_output_names()
        query = self.options.output
        matches = (
            names
            if query is None
            else [name for name in names if query.casefold() in name.casefold()]
        )

        if len(matches) != 1:
            raise ValueError(
                f"{self.display_name} MIDI output query {query!r} matched {len(matches)} ports; "
                "use --steering-output with a unique substring"
            )

        self.port = mido.open_output(matches[0])
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.port is not None:
            self.port.close()

    def _send(self, message_type: str, **kwargs: int) -> None:
        import mido

        if self.port is None:
            raise RuntimeError(f"{self.display_name} MIDI output is not open")

        self.port.send(mido.Message(message_type, channel=self.options.channel - 1, **kwargs))

    def activate_preset(self, preset_id: int) -> None:
        value = preset_id - 1

        if value < 0 or value > 127:
            raise ValueError(f"Invalid {self.display_name} preset ID: {preset_id}")

        self._send("program_change", program=value)
        time.sleep(self.options.preset_wait_seconds)

    def activate_snapshot(self, snapshot: int) -> None:
        value = snapshot - 1

        if value < 0 or value >= self.max_snapshot_count:
            raise ValueError(f"Invalid {self.display_name} snapshot: {snapshot}")

        self._send("control_change", control=self.snapshot_cc, value=value)
        time.sleep(self.options.snapshot_wait_seconds)

    def reapply_snapshot(self, snapshot: int) -> None:
        self.activate_snapshot(snapshot)


class Line6DeviceProfile(DeviceProfile):
    device_label = "Line 6"
    preset_name_max_length = 16
    snapshot_name_max_length = 10
    name_pattern = r"""^[A-Za-z0-9\-_+=!@#$&()?:'",./ ]*$"""
    audio_device_query = "Line 6"
    audio_sample_rate = 48000
    audio_input_mapping = (1, 2)
    audio_output_mapping = (3, 4)
    steering_output_query = "Line 6"
    steering_preset_wait_seconds = 0.5
    steering_snapshot_wait_seconds = 0.2
    steering_measurement_wait_seconds = 0.1

    def terminology(self) -> DeviceTerminology:
        return DeviceTerminology(
            device=self.device_label,
            preset="preset",
            snapshot="snapshot",
            setlist="setlist",
        )

    def file_capabilities(self) -> FileOperationCapabilities:
        return FileOperationCapabilities(
            reads_preset_files=True,
            writes_preset_files=True,
            reads_setlist_files=True,
            writes_setlist_files=True,
            joins_presets_to_setlist=True,
            splits_setlist_to_presets=True,
            exports_selected_setlist_slots=True,
        )

    def naming_rules(self) -> NamingRules:
        return NamingRules(
            preset_name_max_length=self.preset_name_max_length,
            snapshot_name_max_length=self.snapshot_name_max_length,
            allowed_name_pattern=self.name_pattern,
        )

    def validate_preset_name(self, name: str) -> str:
        return self._validate_line6_name(name, self.preset_name_max_length)

    def validate_subdivision_name(self, name: str) -> str:
        return self._validate_line6_name(name, self.snapshot_name_max_length)

    def sanitize_preset_name(self, name: str) -> str:
        return self._sanitize_line6_name(name, self.preset_name_max_length)

    def sanitize_subdivision_name(self, name: str) -> str:
        return self._sanitize_line6_name(name, self.snapshot_name_max_length)

    def _validate_line6_name(self, name: str, max_length: int | None = None) -> str:
        if LINE6_NAME_PATTERN.fullmatch(name) is None:
            raise ValueError(f"Invalid {self.device_label} name: {name!r}")
        if max_length is not None and len(name) > max_length:
            raise ValueError(f"{self.device_label} name exceeds {max_length} characters: {name!r}")
        return name

    @staticmethod
    def _sanitize_line6_name(name: str, max_length: int | None = None) -> str:
        sanitized = "".join(
            character for character in name if LINE6_NAME_CHAR_PATTERN.fullmatch(character)
        )
        return sanitized[:max_length] if max_length is not None else sanitized

    def format_patch_id(self, preset_id: int) -> str:
        return file_ops.banked_slot_label(preset_id - 1)

    def default_audio_routing(self) -> AudioRouting:
        return AudioRouting(
            device=self.audio_device_query,
            sample_rate=self.audio_sample_rate,
            input_mapping=self.audio_input_mapping,
            output_mapping=self.audio_output_mapping,
        )

    def default_steering_options(self) -> SteeringOptions:
        return SteeringOptions(
            output=self.steering_output_query,
            channel=1,
            preset_wait_seconds=self.steering_preset_wait_seconds,
            snapshot_wait_seconds=self.steering_snapshot_wait_seconds,
            measurement_wait_seconds=self.steering_measurement_wait_seconds,
        )

    def setting_descriptors(self) -> tuple[DeviceSettingDescriptor, ...]:
        audio = self.default_audio_routing()
        steering = self.default_steering_options()
        audio_path = ("devices", self.name, "audio")
        steering_path = ("devices", self.name, "steering")
        descriptors = (
            DeviceSettingDescriptor(
                name="audio_device",
                scope="audio",
                kind="string",
                default=audio.device,
                config_path=(*audio_path, "device"),
                cli_flags=("--audio-device",),
                label="Audio device",
                help=f"{self.device_label} USB audio device query.",
            ),
            DeviceSettingDescriptor(
                name="sample_rate",
                scope="audio",
                kind="integer",
                default=audio.sample_rate,
                config_path=(*audio_path, "sample_rate"),
                cli_flags=("--sample-rate",),
                label="Sample rate",
                help=f"{self.device_label} USB audio sample rate in hertz.",
                minimum=1,
            ),
            DeviceSettingDescriptor(
                name="input_mapping",
                scope="audio",
                kind="channel_mapping",
                default=audio.input_mapping,
                config_path=(*audio_path, "input_mapping"),
                cli_flags=("--input-mapping",),
                label="Input mapping",
                help=f"One-based {self.device_label} USB input channel mapping.",
            ),
            DeviceSettingDescriptor(
                name="output_mapping",
                scope="audio",
                kind="channel_mapping",
                default=audio.output_mapping,
                config_path=(*audio_path, "output_mapping"),
                cli_flags=("--output-mapping",),
                label="Output mapping",
                help=f"One-based {self.device_label} USB output channel mapping.",
            ),
            DeviceSettingDescriptor(
                name="blocksize",
                scope="audio",
                kind="integer",
                default=0,
                config_path=(*audio_path, "blocksize"),
                cli_flags=("--blocksize",),
                label="Blocksize",
                help="Audio block size, or zero for the backend default.",
                minimum=0,
            ),
            DeviceSettingDescriptor(
                name="midi_output",
                scope="steering",
                kind="string",
                default=steering.output,
                config_path=(*steering_path, "output"),
                cli_flags=("--steering-output", "--midi-output"),
                label="MIDI output",
                help=f"{self.device_label} MIDI output port query.",
            ),
            DeviceSettingDescriptor(
                name="midi_channel",
                scope="steering",
                kind="integer",
                default=steering.channel,
                config_path=(*steering_path, "channel"),
                cli_flags=("--midi-channel",),
                label="MIDI channel",
                help=f"One-based MIDI channel used for {self.device_label} program changes.",
                minimum=1,
                maximum=16,
            ),
            DeviceSettingDescriptor(
                name="preset_wait",
                scope="steering",
                kind="float",
                default=steering.preset_wait_seconds,
                config_path=(*steering_path, "preset_wait_seconds"),
                cli_flags=("--preset-wait",),
                label="Preset wait",
                help=f"Seconds to wait after sending a {self.device_label} preset change.",
                minimum=0.0,
            ),
            DeviceSettingDescriptor(
                name="snapshot_wait",
                scope="steering",
                kind="float",
                default=steering.snapshot_wait_seconds,
                config_path=(*steering_path, "snapshot_wait_seconds"),
                cli_flags=("--snapshot-wait",),
                label="Snapshot wait",
                help=f"Seconds to wait after sending a {self.device_label} snapshot change.",
                minimum=0.0,
            ),
            DeviceSettingDescriptor(
                name="measurement_wait",
                scope="steering",
                kind="float",
                default=steering.measurement_wait_seconds,
                config_path=(*steering_path, "measurement_wait_seconds"),
                cli_flags=("--measurement-wait",),
                label="Measurement wait",
                help=f"Seconds to wait before recording each {self.device_label} measurement.",
                minimum=0.0,
            ),
        )
        return tuple(
            replace(descriptor, show_in_gui=False)
            if descriptor.name in LINE6_REDUNDANT_PANEL_SETTINGS
            else descriptor
            for descriptor in descriptors
        )


def _error_details(exc: subprocess.CalledProcessError) -> str:
    lines = (exc.stderr or "").splitlines() + (exc.stdout or "").splitlines()
    errors = [line for line in lines if line.strip().startswith("ERROR:")]

    if errors:
        return "\n".join(errors)

    return lines[-1].strip() if lines else ""


def _assignment_gain_points(assignment: Mapping[str, object]) -> tuple[GainPoint, ...]:
    paths = assignment.get("snapshot_output_paths", ())
    if not isinstance(paths, list | tuple):
        return ()

    return tuple(
        GainPoint(
            id=str(path),
            label=str(path),
            current_db=0.0,
            minimum_db=-120.0,
            maximum_db=20.0,
            scope="subdivision",
            path=str(path),
        )
        for path in paths
    )
