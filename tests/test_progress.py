from __future__ import annotations

import json

import pytest

from matchpatch.progress import ProgressEvent


def test_progress_event_round_trips_json() -> None:
    event = ProgressEvent(
        "snapshot_completed",
        preset_id=6,
        device_patch="02B",
        snapshot=3,
        snapshot_total=4,
        lufs=-16.2,
        crest_factor_db=11.7,
    )

    assert ProgressEvent.from_json(event.to_json()) == event


@pytest.mark.parametrize("payload", ["[]", '{"unknown": true}', "{"])
def test_progress_event_rejects_invalid_json(payload: str) -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        ProgressEvent.from_json(payload)
