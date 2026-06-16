from __future__ import annotations

import pytest

from matchpatch.gui.progress_widgets import MeasurementProgressEstimate, phase_text
from matchpatch.progress import ProgressEvent


@pytest.mark.parametrize(
    ("phase", "text"),
    [
        ("ready", "Ready"),
        ("starting", "Starting..."),
        ("preflight_checks", "Running pre flight checks..."),
        ("preparing_measurement", "Preparing Measurement..."),
        ("waiting_for_measurement_import", "Waiting For Measurement Import..."),
        ("measuring", "Measuring..."),
        ("applying", "Applying..."),
        ("waiting_for_adjusted_import", "Waiting For Adjusted Import..."),
        ("completed", "Completed"),
        ("error", "Error"),
        ("cancelling", "Cancelling..."),
        ("normalization_cancelled_by_user", "Normalization cancelled by user"),
    ],
)
def test_phase_text_marks_in_progress_statuses(phase: str, text: str) -> None:
    assert phase_text(phase) == text


def test_measurement_progress_estimate_calculates_snapshot_and_remaining_time() -> None:
    estimate = MeasurementProgressEstimate(
        preset_wait=0.5,
        snapshot_wait=0.2,
        measurement_wait=0.4,
        pre_roll=0.2,
        post_roll=0.3,
        round_trip_latency=0.1,
        reference_audio_seconds=1.0,
    )

    assert estimate.snapshot_seconds == pytest.approx(2.2)
    assert estimate.total_seconds(2, 3) == pytest.approx(14.2)
    assert estimate.remaining_seconds(
        ProgressEvent("snapshot_completed", preset_index=1, snapshot=2),
        preset_total=2,
        snapshot_total=3,
    ) == pytest.approx(9.3)
