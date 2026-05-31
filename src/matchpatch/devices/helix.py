"""Line 6 Helix profile: patch files, MIDI steering, and USB routing."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import TracebackType

from matchpatch.devices.base import (
    AudioRouting,
    DeviceController,
    DeviceProfile,
    NormalizationPolicy,
    PatchAssignment,
    PatchFileHandler,
    SteeringOptions,
)


class HelixPatchFileHandler(PatchFileHandler):
    def __init__(self, project_dir: Path) -> None:
        self.script = project_dir / "Python" / "preset_handling.py"

    def _run(self, *args: object, capture: bool = False) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), *(str(arg) for arg in args)],
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )

    def validate_input(self, input_path: Path) -> None:
        if input_path.suffix.lower() not in {".hls", ".hlx"}:
            raise ValueError("Helix input must be an .hls or .hlx file")

    def validate_output(self, input_path: Path, output_path: Path) -> None:
        if output_path.suffix.lower() != input_path.suffix.lower():
            raise ValueError(f"Helix output must use the {input_path.suffix.lower()} extension")

    def list_assignments(self, input_path: Path) -> list[PatchAssignment]:
        completed = self._run("-i", input_path, "--list-presets", capture=True)
        return [
            PatchAssignment(
                id=assignment["id"],
                device_patch=assignment["helix_preset"],
                name=assignment["name"],
            )
            for assignment in json.loads(completed.stdout)
        ]

    def parse_patch_set(self, value: str) -> list[int]:
        preset_ids = []

        for token in value.split(","):
            text = token.strip().upper()

            if len(text) < 2 or not text[:-1].isdigit() or text[-1] not in "ABCD":
                raise ValueError(f"Invalid Helix preset ID: {token}")

            bank = int(text[:-1])

            if bank < 1:
                raise ValueError(f"Invalid Helix preset ID: {token}")

            preset_id = (bank - 1) * 4 + "ABCD".index(text[-1]) + 1

            if preset_id not in preset_ids:
                preset_ids.append(preset_id)

        if not preset_ids:  # pragma: no cover - guarded by token validation
            raise ValueError("Preset set did not contain Helix presets")

        return preset_ids

    def select_preset_ids(
        self,
        input_path: Path,
        assignments: list[PatchAssignment],
        requested_ids: list[int] | None,
    ) -> list[int]:
        if input_path.suffix.lower() == ".hlx":
            if requested_ids is None or len(requested_ids) != 1:
                raise ValueError(
                    "Helix .hlx input requires exactly one --preset-set value, "
                    "for example --preset-set 12A"
                )

            return requested_ids

        available_ids = {assignment.id for assignment in assignments}

        if requested_ids is None:
            return [assignment.id for assignment in assignments]

        missing_ids = [preset_id for preset_id in requested_ids if preset_id not in available_ids]

        if missing_ids:
            missing = ",".join(self.format_patch_id(preset_id) for preset_id in missing_ids)
            raise ValueError(f"Requested Helix presets are missing or empty: {missing}")

        requested = set(requested_ids)
        return [assignment.id for assignment in assignments if assignment.id in requested]

    def format_patch_id(self, preset_id: int) -> str:
        zero_based = preset_id - 1
        return f"{zero_based // 4 + 1:02d}{'ABCD'[zero_based % 4]}"

    def create_reamp_file(self, input_path: Path, output_path: Path) -> None:
        self._run("-i", input_path, "-o", output_path, "--reamp")

    def apply_analysis_csv(
        self,
        input_path: Path,
        output_path: Path,
        csv_path: Path,
        ignore_bad_lufs: bool,
        target_lufs: float,
        policy: NormalizationPolicy = NormalizationPolicy(),
    ) -> None:
        legacy_csv_path = self._create_legacy_analysis_csv(csv_path)

        try:
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
                "--solo-marker",
                policy.solo_marker,
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

            if ignore_bad_lufs:
                args.append("--ignore-bad-lufs")

            self._run(*args)
        finally:
            legacy_csv_path.unlink(missing_ok=True)

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
                suffix=".helix.csv",
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

    def automation_output_path(self, input_path: Path, postfix: str) -> Path:
        self.validate_input(input_path)
        return input_path.with_name(input_path.stem + postfix + input_path.suffix)


class HelixMidiController(DeviceController):
    def __init__(self, options: SteeringOptions) -> None:
        self.options = options
        self.port = None

    def __enter__(self) -> "HelixMidiController":
        import mido

        names = mido.get_output_names()
        query = self.options.output
        matches = (
            names
            if query is None
            else [name for name in names if query.casefold() in name.casefold()]
        )

        if len(matches) != 1:
            raise ValueError(
                f"Helix MIDI output query {query!r} matched {len(matches)} ports; "
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
            raise RuntimeError("Helix MIDI output is not open")

        self.port.send(mido.Message(message_type, channel=self.options.channel, **kwargs))

    def activate_preset(self, preset_id: int) -> None:
        value = preset_id - 1

        if value < 0 or value > 127:
            raise ValueError(f"Invalid Helix preset ID: {preset_id}")

        self._send("program_change", program=value)
        time.sleep(self.options.preset_wait_seconds)

    def activate_snapshot(self, snapshot: int) -> None:
        value = snapshot - 1

        if value < 0 or value > 7:
            raise ValueError(f"Invalid Helix snapshot: {snapshot}")

        self._send("control_change", control=69, value=value)
        time.sleep(self.options.snapshot_wait_seconds)

    def reapply_snapshot(self, snapshot: int) -> None:
        self.activate_snapshot(2 if snapshot == 1 else 1)
        self.activate_snapshot(snapshot)


class HelixDeviceProfile(DeviceProfile):
    name = "helix"
    display_name = "Line 6 Helix"

    def create_patch_file_handler(self, project_dir: Path) -> PatchFileHandler:
        return HelixPatchFileHandler(project_dir)

    def default_audio_routing(self) -> AudioRouting:
        return AudioRouting(
            device="Helix",
            sample_rate=48000,
            input_mapping=(1, 2),
            output_mapping=(3, 4),
        )

    def default_steering_options(self) -> SteeringOptions:
        return SteeringOptions(
            output="Helix",
            channel=0,
            preset_wait_seconds=0.5,
            snapshot_wait_seconds=0.05,
            measurement_wait_seconds=0.5,
        )

    def create_controller(self, options: SteeringOptions) -> DeviceController:
        return HelixMidiController(options)
