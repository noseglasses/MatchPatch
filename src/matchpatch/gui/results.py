"""Normalization result parsing and display-state helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from matchpatch.devices.base import NormalizationPolicy
from matchpatch.gui.table_roles import OUTPUT_LEVEL_MAX_DB, OUTPUT_LEVEL_MIN_DB
from matchpatch.progress import ProgressEvent

GAIN_CORRECTION_PATTERN = re.compile(
    r"^\[GAIN\] (?P<patch>\d{2}[A-D]) (?P<label>.*?) \| "
    r"(?:\S+\s+)?(?P<before>-?\d+(?:\.\d+)?) dB -> (?P<after>-?\d+(?:\.\d+)?) dB "
    r"\(Delta: (?P<delta>[+-]\d+(?:\.\d+)?) dB\)$"
)
GAIN_STABLE_PATTERN = re.compile(
    r"^\[GAIN\] (?P<patch>\d{2}[A-D]) (?P<label>.*?) \| "
    r"stable at (?:\S+\s+)?(?P<after>-?\d+(?:\.\d+)?) dB "
    r"\(Delta: (?P<delta>[+-]\d+(?:\.\d+)?) dB\)$"
)
GAIN_BAD_LUFS_PATTERN = re.compile(
    r"^\[GAIN\] (?P<patch>\d{2}[A-D]) (?P<label>.*?) \| "
    r"(?:bad LUFS|measurement unavailable)(?: \((?P<detail>.*)\))?$"
)
GAIN_PRESET_SYNC_PATTERN = re.compile(r"^\[GAIN\] (?P<patch>\d{2}[A-D]): synchronized\b")


@dataclass(frozen=True)
class GainCorrectionEvent:
    patch: str
    label: str
    kind: Literal["changed", "stable", "bad_lufs"]
    before_db: float | None
    after_db: float | None
    delta_db: float | None
    delta_text: str | None
    detail: str | None
    is_solo: bool = False

    @property
    def snapshot_label(self) -> str:
        return self.label[:-4] if self.is_solo else self.label


@dataclass(frozen=True)
class SnapshotMeasurementDisplay:
    patch: str
    snapshot_index: int
    adjustment_text: str
    adjustment_value: float | None
    measured_adjustment: float | None
    tooltip: str
    status: Literal["measured", "ignored", "failed", "implausible"]
    custom_adjustment: float | None = None
    display_adjustment: float | None = None
    implausible_output_gain: float | None = None


@dataclass(frozen=True)
class ManualAdjustmentSnapshot:
    patch: str
    preset: str
    snapshot_index: int
    snapshot_name: str = ""


def gain_preset_sync_patch(message: str) -> str | None:
    match = GAIN_PRESET_SYNC_PATTERN.match(message)
    return match["patch"] if match is not None else None


def gain_correction_match(message: str) -> re.Match[str] | None:
    return (
        GAIN_CORRECTION_PATTERN.match(message)
        or GAIN_STABLE_PATTERN.match(message)
        or GAIN_BAD_LUFS_PATTERN.match(message)
    )


def is_gain_correction_log(message: str) -> bool:
    return gain_correction_match(message) is not None


def parse_gain_correction_log(message: str) -> GainCorrectionEvent | None:
    match = gain_correction_match(message)
    if match is None:
        return None

    label = match["label"]
    is_solo = label.endswith(" (S)")
    kind: Literal["changed", "stable", "bad_lufs"]
    if match.re is GAIN_BAD_LUFS_PATTERN:
        kind = "bad_lufs"
    elif match.re is GAIN_STABLE_PATTERN:
        kind = "stable"
    else:
        kind = "changed"

    groups = match.groupdict()
    return GainCorrectionEvent(
        patch=match["patch"],
        label=label,
        kind=kind,
        before_db=_float_group(groups.get("before")),
        after_db=_float_group(groups.get("after")),
        delta_db=_float_group(groups.get("delta")),
        delta_text=groups.get("delta"),
        detail=groups.get("detail"),
        is_solo=is_solo,
    )


def measurement_gain_delta(
    *,
    target_lufs: float,
    lufs: float | None,
    crest_factor_db: float | None,
    policy: NormalizationPolicy,
) -> float:
    crest_factor_correction = 0.0
    if crest_factor_db is not None:
        crest_factor_correction = min(
            max(
                (policy.crest_factor_reference_db - crest_factor_db)
                * policy.crest_factor_correction_ratio,
                0.0,
            ),
            policy.max_crest_factor_correction_db,
        )
    if lufs is None:
        return 0.0
    return round(target_lufs - lufs - crest_factor_correction, 1)


def implausible_snapshot_output_gain(
    output_levels: tuple[float, ...],
    gain_delta: float,
    *,
    minimum_db: float = OUTPUT_LEVEL_MIN_DB,
    maximum_db: float = OUTPUT_LEVEL_MAX_DB,
) -> float | None:
    for value in output_levels:
        output_gain = round(value + gain_delta, 2)
        if not minimum_db <= output_gain <= maximum_db:
            return output_gain
    return None


def snapshot_measurement_display(
    event: ProgressEvent,
    *,
    policy: NormalizationPolicy,
    target_lufs: float,
    output_levels: tuple[float, ...],
    is_solo: bool,
    is_ignored: bool,
    custom_adjustment: float | None,
) -> SnapshotMeasurementDisplay | None:
    if event.device_patch is None or event.snapshot is None or event.lufs is None:
        return None

    snapshot_index = event.snapshot - 1
    if is_ignored:
        return SnapshotMeasurementDisplay(
            patch=event.device_patch,
            snapshot_index=snapshot_index,
            adjustment_text="Ignore",
            adjustment_value=None,
            measured_adjustment=None,
            tooltip="This snapshot is skipped during normalization.",
            status="ignored",
        )

    gain_delta = measurement_gain_delta(
        target_lufs=target_lufs,
        lufs=event.lufs,
        crest_factor_db=event.crest_factor_db,
        policy=policy,
    )
    if is_solo:
        gain_delta += policy.solo_gain_bump_db
    if custom_adjustment is not None:
        gain_delta += custom_adjustment
    display_adjustment = (
        gain_delta - custom_adjustment if custom_adjustment is not None else gain_delta
    )
    implausible_output_gain = implausible_snapshot_output_gain(output_levels, gain_delta)
    if implausible_output_gain is not None:
        return SnapshotMeasurementDisplay(
            patch=event.device_patch,
            snapshot_index=snapshot_index,
            adjustment_text="",
            adjustment_value=None,
            measured_adjustment=display_adjustment,
            tooltip=f"Implausible output gain {implausible_output_gain:g} dB",
            status="implausible",
            custom_adjustment=custom_adjustment,
            display_adjustment=display_adjustment,
            implausible_output_gain=implausible_output_gain,
        )

    return SnapshotMeasurementDisplay(
        patch=event.device_patch,
        snapshot_index=snapshot_index,
        adjustment_text="",
        adjustment_value=gain_delta,
        measured_adjustment=display_adjustment if custom_adjustment is not None else None,
        tooltip="",
        status="measured",
        custom_adjustment=custom_adjustment,
        display_adjustment=display_adjustment,
    )


def snapshot_measurement_failure_display(
    event: ProgressEvent,
) -> SnapshotMeasurementDisplay | None:
    if event.device_patch is None or event.snapshot is None:
        return None
    return SnapshotMeasurementDisplay(
        patch=event.device_patch,
        snapshot_index=event.snapshot - 1,
        adjustment_text="Measurement failed ⚠️",
        adjustment_value=None,
        measured_adjustment=None,
        tooltip=event.message or "",
        status="failed",
    )


def manual_adjustment_target(snapshot: ManualAdjustmentSnapshot) -> str:
    prefix = " ".join(part for part in (snapshot.patch, snapshot.preset) if part)
    snapshot_label = f"snapshot {snapshot.snapshot_index + 1}"
    if snapshot.snapshot_name:
        snapshot_label = f"{snapshot_label} ({snapshot.snapshot_name})"
    return f"{prefix}: {snapshot_label}" if prefix else snapshot_label


def manual_adjustment_targets(snapshots: list[ManualAdjustmentSnapshot]) -> list[str]:
    return [manual_adjustment_target(snapshot) for snapshot in snapshots]


def _float_group(value: str | None) -> float | None:
    return float(value) if value is not None else None
