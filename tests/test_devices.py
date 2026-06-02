from __future__ import annotations

from pathlib import Path

import pytest

from matchpatch.devices import get_device_profile
from matchpatch.devices.base import DeviceController, validate_snapshot_count


def test_helix_profile_defines_processor_boundaries() -> None:
    profile = get_device_profile("helix")
    routing = profile.default_audio_routing()
    steering = profile.default_steering_options()
    handler = profile.create_patch_file_handler(Path("."))

    assert routing.input_mapping == (1, 2)
    assert routing.output_mapping == (3, 4)
    assert steering.output == "Helix"
    assert profile.snapshot_count == 4
    assert profile.max_snapshot_count == 8
    assert handler.parse_patch_set("01A,02B") == [1, 6]
    assert handler.format_patch_id(6) == "02B"


def test_helix_profile_rejects_more_than_eight_snapshots() -> None:
    with pytest.raises(ValueError, match="must not exceed 8"):
        validate_snapshot_count(get_device_profile("helix"), 9)


def test_unknown_device_profile_lists_supported_devices() -> None:
    with pytest.raises(ValueError, match="Unsupported device 'unknown'.*helix"):
        get_device_profile("unknown")


class EmptyController(DeviceController):
    def activate_preset(self, preset_id: int) -> None:
        return None

    def reapply_snapshot(self, snapshot: int) -> None:
        return None


def test_base_controller_context_manager_returns_and_closes_cleanly() -> None:
    controller = EmptyController()

    assert controller.__enter__() is controller
    assert controller.__exit__(None, None, None) is None
