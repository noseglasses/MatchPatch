from __future__ import annotations

import base64
import binascii
import json
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from matchpatch.devices import get_device_profile
from matchpatch.devices.base import SteeringOptions
from matchpatch.devices.line6 import file_ops
from matchpatch.devices.line6.common import Line6MidiController


def _compressed_setlist_text(data: dict) -> str:
    raw = json.dumps(data, indent=1).encode("utf-8")
    return json.dumps(
        {
            "schema": "L6Setlist",
            "compression": {
                "crc32": binascii.crc32(raw) & 0xFFFFFFFF,
                "decompressed_size": len(raw),
                "type": "zlib",
            },
            "encoded_data": base64.b64encode(zlib.compress(raw, level=9)).decode("ascii"),
        }
    )


def test_banked_slot_helpers_parse_validate_and_preserve_first_occurrence() -> None:
    assert file_ops.banked_slot_label(0) == "01A"
    assert file_ops.banked_slot_label(127) == "32D"
    assert file_ops.banked_slot_index("32d", device_name="Line 6") == 127
    assert file_ops.parse_banked_slot_set(" 01a, 02B,01A ") == [1, 6]

    for invalid in ("", "0A", "33A", "01E"):
        with pytest.raises(ValueError, match="Line 6"):
            file_ops.parse_banked_slot_set(invalid, device_name="Line 6")


def test_compressed_setlist_helpers_preserve_wrapper_and_update_crc() -> None:
    original = _compressed_setlist_text({"presets": [{"tone": {}}]})
    modified_json = json.dumps({"presets": [{"tone": {"dsp0": {}}}]}, indent=1)

    rebuilt = file_ops.build_compressed_setlist_text(original, modified_json)
    wrapper = json.loads(rebuilt)
    raw = zlib.decompress(base64.b64decode(wrapper["encoded_data"]))

    assert wrapper["schema"] == "L6Setlist"
    assert raw.decode("utf-8") == modified_json
    assert wrapper["compression"]["decompressed_size"] == len(raw)
    assert wrapper["compression"]["crc32"] == binascii.crc32(raw) & 0xFFFFFFFF
    assert file_ops.decode_compressed_setlist_text(rebuilt) == modified_json


def test_preset_wrapping_and_safe_filename_are_extension_aware(tmp_path: Path) -> None:
    wrapped = file_ops.wrap_preset_data({"data": {"tone": {}, "meta": {"name": "Lead"}}})

    assert file_ops.unwrap_preset_data(wrapped) == {"tone": {}, "meta": {"name": "Lead"}}
    assert file_ops.safe_preset_filename("Bad/Name", "01A", preset_extension=".pgp") == (
        "Bad Name.pgp"
    )

    preset_path = tmp_path / "Lead.pgp"
    preset_path.write_text(json.dumps({"data": {"tone": {}, "meta": {"name": "Lead"}}}))
    preset, original = file_ops.load_line6_preset_file(preset_path, preset_extension=".pgp")

    assert preset == {"tone": {}, "meta": {"name": "Lead"}}
    assert original == {"data": {"tone": {}, "meta": {"name": "Lead"}}}


def test_line6_midi_controller_uses_pc_and_device_snapshot_limit(monkeypatch) -> None:
    class FourSnapshotController(Line6MidiController):
        display_name = "Test Device"
        max_snapshot_count = 4

    sent = []
    sleeps = []
    mido = SimpleNamespace(Message=lambda message_type, **kwargs: (message_type, kwargs))
    monkeypatch.setitem(__import__("sys").modules, "mido", mido)
    monkeypatch.setattr("matchpatch.devices.line6.common.time.sleep", sleeps.append)

    controller = FourSnapshotController(SteeringOptions("test", 4, 0.5, 0.1, 0.0))
    controller.port = SimpleNamespace(send=sent.append)
    controller.activate_preset(18)
    controller.activate_snapshot(4)

    assert sent == [
        ("program_change", {"channel": 3, "program": 17}),
        ("control_change", {"channel": 3, "control": 69, "value": 3}),
    ]
    assert sleeps == [0.5, 0.1]

    with pytest.raises(ValueError, match="Test Device snapshot"):
        controller.activate_snapshot(5)


def test_podgo_midi_controller_uses_pc_and_four_snapshot_limit(monkeypatch) -> None:
    sent = []
    mido = SimpleNamespace(Message=lambda message_type, **kwargs: (message_type, kwargs))
    monkeypatch.setitem(__import__("sys").modules, "mido", mido)
    monkeypatch.setattr("matchpatch.devices.line6.common.time.sleep", lambda seconds: None)

    profile = get_device_profile("podgo")
    controller = profile.create_controller(SteeringOptions("POD Go", 1, 0.0, 0.0, 0.0))
    controller.port = SimpleNamespace(send=sent.append)

    controller.activate_preset(1)
    controller.activate_preset(128)
    controller.activate_snapshot(4)

    assert sent == [
        ("program_change", {"channel": 0, "program": 0}),
        ("program_change", {"channel": 0, "program": 127}),
        ("control_change", {"channel": 0, "control": 69, "value": 3}),
    ]

    with pytest.raises(ValueError, match="Pod Go preset ID"):
        controller.activate_preset(129)
    with pytest.raises(ValueError, match="Pod Go snapshot"):
        controller.activate_snapshot(5)
