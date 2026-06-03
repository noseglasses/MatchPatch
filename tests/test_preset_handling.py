from __future__ import annotations

import base64
import binascii
import importlib.util
import json
import zlib
from pathlib import Path
from types import ModuleType

import pytest


def _load_legacy_module() -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "Python" / "preset_handling.py"
    spec = importlib.util.spec_from_file_location("preset_handling", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lufs_error_sentinel_is_retained_per_snapshot(tmp_path) -> None:
    module = _load_legacy_module()
    csv_path = tmp_path / "analysis.csv"
    csv_path.write_text(
        "HelixPreset,LUFS1,CrestFactor1,LUFS2,CrestFactor2\n01A,ERROR,ERROR,-17.0,12.0\n",
        encoding="utf-8",
    )

    deltas = module.load_lufs_analysis_file(csv_path, snapshot_count=2)

    assert deltas == {"01A": {0: None, 1: 1.0}}


def test_assignment_extraction_includes_snapshot_names() -> None:
    module = _load_legacy_module()
    data = {
        "presets": [
            {
                "meta": {"name": "Lead"},
                "tone": {
                    "dsp0": {"block0": {}},
                    "snapshot0": {"@name": "Rhythm"},
                    "snapshot1": {"@name": "Solo"},
                },
            }
        ]
    }

    assignments = module.extract_preset_assignments(data)

    assert assignments[0]["snapshot_names"] == ["Rhythm", "Solo"]


def test_metadata_extraction_keeps_wrapper_and_meta_nodes() -> None:
    module = _load_legacy_module()
    data = {
        "meta": {"app": "HX Edit"},
        "presets": [
            {
                "meta": {"name": "Lead"},
                "tone": {"snapshot0": {"@name": "Rhythm"}},
            }
        ],
    }
    wrapper = {
        "compression": {"type": "zlib"},
        "encoded_data": "omitted",
    }

    metadata = module.extract_metadata("set.hls", json.dumps(data), json.dumps(wrapper))

    assert metadata == {
        "file_type": "hls",
        "metadata": [
            {"path": "$.meta", "value": {"app": "HX Edit"}},
            {"path": "$.presets[0].meta", "value": {"name": "Lead"}},
        ],
        "wrapper": {"compression": {"type": "zlib"}},
    }


def test_manual_adjustments_rename_and_override_final_solo_delta() -> None:
    module = _load_legacy_module()
    data = {
        "presets": [
            {
                "meta": {"name": "Lead"},
                "tone": {
                    "dsp0": {
                        "block0": {},
                        "inputA": {"@input": 1},
                        "outputA": {"@output": 6, "gain": 0.0},
                    },
                    "snapshot0": {"@name": "Solo"},
                },
            }
        ]
    }
    adjustments = {
        "preset_names": {"01A": "Lead 2"},
        "snapshot_names": {"01A": {"0": "Solo!"}},
        "gain_deltas": {"01A": {"0": 4.5}},
    }

    module.apply_manual_adjustments(data, adjustments)
    module.adjust_snapshot_gains(
        data,
        {"01A": {0: 1.0}},
        solo_gain_bump_db=3.0,
        manual_gain_deltas=adjustments["gain_deltas"],
    )

    assert data["presets"][0]["meta"]["name"] == "Lead 2"
    snapshot = data["presets"][0]["tone"]["snapshot0"]
    assert snapshot["@name"] == "Solo!"
    assert snapshot["controllers"]["dsp0"]["outputA"]["gain"]["@value"] == 4.5


def test_manual_adjustments_reject_invalid_helix_name() -> None:
    module = _load_legacy_module()

    with pytest.raises(ValueError, match="Invalid Helix name"):
        module.apply_manual_adjustments(
            {"presets": [{"tone": {}}]},
            {"preset_names": {"01A": "Invalid%"}},
        )


def test_build_hls_text_updates_crc32_for_encoded_data() -> None:
    module = _load_legacy_module()
    original = json.dumps(
        {
            "compression": {"crc32": 0, "decompressed_size": 0, "type": "zlib"},
            "encoded_data": "",
        }
    )

    rebuilt = json.loads(module.build_hls_text(original, '{"presets": []}'))
    raw = zlib.decompress(base64.b64decode(rebuilt["encoded_data"]))

    assert rebuilt["compression"]["crc32"] == binascii.crc32(raw) & 0xFFFFFFFF
    assert rebuilt["compression"]["decompressed_size"] == len(raw)


def test_save_output_packs_crc32_for_encoded_data(tmp_path) -> None:
    module = _load_legacy_module()
    output_path = tmp_path / "setlist.hls"

    module.save_output('{"presets": []}', output_path)

    wrapper = json.loads(output_path.read_text(encoding="utf-8"))
    raw = zlib.decompress(base64.b64decode(wrapper["encoded_data"]))

    assert wrapper["compression"]["crc32"] == binascii.crc32(raw) & 0xFFFFFFFF
    assert wrapper["compression"]["decompressed_size"] == len(raw)
