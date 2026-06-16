"""Progress display helpers for the GUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from matchpatch.progress import ProgressEvent
from matchpatch.workflow import NormalizationRequest


@dataclass(frozen=True)
class MeasurementProgressEstimate:
    preset_wait: float
    snapshot_wait: float
    measurement_wait: float
    pre_roll: float
    post_roll: float
    round_trip_latency: float
    reference_audio_seconds: float = 0.0

    @classmethod
    def from_request(cls, request: NormalizationRequest) -> MeasurementProgressEstimate:
        return cls(
            preset_wait=_float_or_zero(request.preset_wait),
            snapshot_wait=_float_or_zero(request.snapshot_wait),
            measurement_wait=_float_or_zero(request.measurement_wait),
            pre_roll=_float_or_zero(request.pre_roll),
            post_roll=_float_or_zero(request.post_roll),
            round_trip_latency=_float_or_zero(request.round_trip_latency),
            reference_audio_seconds=reference_audio_seconds(request.reference_di),
        )

    @property
    def snapshot_seconds(self) -> float:
        return (
            self.snapshot_wait
            + self.measurement_wait
            + self.pre_roll
            + self.post_roll
            + self.round_trip_latency
            + self.reference_audio_seconds
        )

    def total_seconds(self, preset_total: int, snapshot_total: int) -> float:
        return (
            preset_total * self.preset_wait + preset_total * snapshot_total * self.snapshot_seconds
        )

    def total_seconds_for_counts(self, preset_total: int, measured_snapshot_total: int) -> float:
        return preset_total * self.preset_wait + measured_snapshot_total * self.snapshot_seconds

    def seconds_per_snapshot(self, preset_total: int, snapshot_total: int) -> float:
        measured_snapshots = max(1, preset_total) * max(1, snapshot_total)
        return self.total_seconds(preset_total, snapshot_total) / measured_snapshots

    def seconds_per_measured_snapshot(
        self,
        preset_total: int,
        measured_snapshot_total: int,
    ) -> float:
        return self.total_seconds_for_counts(
            preset_total,
            measured_snapshot_total,
        ) / max(1, measured_snapshot_total)

    def remaining_seconds(
        self, event: ProgressEvent, preset_total: int, snapshot_total: int
    ) -> float:
        completed_presets = max(0, (event.preset_index or 1) - 1)
        completed_snapshots = completed_presets * snapshot_total
        if event.snapshot is not None:
            completed_snapshots += max(0, event.snapshot - 1)
            if event.kind == "snapshot_completed":
                completed_snapshots += 1
        remaining_preset_waits = (
            preset_total - completed_presets
            if event.snapshot is None
            else preset_total - (event.preset_index or 1)
        )
        remaining_snapshots = max(0, preset_total * snapshot_total - completed_snapshots)
        return max(0, remaining_preset_waits) * self.preset_wait + (
            remaining_snapshots * self.snapshot_seconds
        )

    def remaining_seconds_for_plan(
        self,
        event: ProgressEvent,
        plan: MeasurementProgressPlan,
    ) -> float:
        completed_presets = max(0, (event.preset_index or 1) - 1)
        completed_snapshots = plan.completed_snapshots(event)
        remaining_preset_waits = (
            plan.preset_total - completed_presets
            if event.snapshot is None
            else plan.preset_total - (event.preset_index or 1)
        )
        remaining_snapshots = max(0, plan.measured_snapshot_total - completed_snapshots)
        return max(0, remaining_preset_waits) * self.preset_wait + (
            remaining_snapshots * self.snapshot_seconds
        )


@dataclass(frozen=True)
class MeasurementProgressPlan:
    preset_snapshots: tuple[tuple[str, tuple[int, ...]], ...]

    @property
    def preset_total(self) -> int:
        return len(self.preset_snapshots)

    @property
    def measured_snapshot_total(self) -> int:
        return sum(len(snapshots) for _, snapshots in self.preset_snapshots)

    def completed_snapshots(self, event: ProgressEvent) -> int:
        if not self.preset_snapshots:
            return 0

        preset_index = max(1, event.preset_index or 1)
        completed = sum(
            len(snapshots) for _, snapshots in self.preset_snapshots[: preset_index - 1]
        )
        current = self._snapshots_for_event(event)
        if event.snapshot is not None:
            completed += sum(1 for snapshot in current if snapshot < event.snapshot)
            if event.kind == "snapshot_completed" and event.snapshot in current:
                completed += 1
        return completed

    def progress_value(self, event: ProgressEvent) -> int:
        completed = self.completed_snapshots(event)
        if event.kind == "snapshot_started" and event.snapshot in self._snapshots_for_event(event):
            return completed + 1
        return completed

    def _snapshots_for_event(self, event: ProgressEvent) -> tuple[int, ...]:
        if event.device_patch:
            for patch, snapshots in self.preset_snapshots:
                if patch == event.device_patch:
                    return snapshots

        preset_index = event.preset_index or 1
        if 1 <= preset_index <= len(self.preset_snapshots):
            return self.preset_snapshots[preset_index - 1][1]
        return ()


IN_PROGRESS_PHASES = {
    "starting",
    "preflight_checks",
    "preparing_measurement",
    "waiting_for_measurement_import",
    "measuring",
    "applying",
    "waiting_for_adjusted_import",
    "cancelling",
}


def phase_text(phase: str) -> str:
    if phase == "normalization_cancelled_by_user":
        return "Normalization cancelled by user"
    if phase == "preflight_checks":
        return "Running pre flight checks..."
    text = phase.replace("_", " ").title()
    return f"{text}..." if phase in IN_PROGRESS_PHASES else text


def reference_audio_seconds(path: Path | str) -> float:
    try:
        import soundfile as sf

        info = sf.info(str(path))
    except Exception:  # noqa: BLE001
        return 0.0

    if info.frames <= 0 or info.samplerate <= 0:
        return 0.0
    return max(0.0, info.frames / info.samplerate)


def _float_or_zero(value: float | None) -> float:
    return float(value) if value is not None else 0.0
