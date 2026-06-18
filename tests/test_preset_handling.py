from __future__ import annotations

import base64
import binascii
import copy
import importlib
import json
import sys
import zlib
from types import ModuleType

import pytest


def _load_legacy_module() -> ModuleType:
    return importlib.import_module("matchpatch.devices.helix_preset_handling")


def _preset(name: str) -> dict:
    return {
        "meta": {"name": name},
        "tone": {
            "dsp0": {
                "inputA": {"@input": 1},
                "block0": {},
                "outputA": {"@output": 6, "gain": 0.0},
            },
            "snapshot0": {"@name": "Snapshot 1"},
        },
    }


def _preset_with_snapshot_assigned_properties(
    name: str,
    count: int,
    *,
    output_gain_assigned: bool = False,
) -> dict:
    preset = _preset(name)
    tone = preset["tone"]
    block = tone["dsp0"]["block0"]
    block_controller = (
        tone.setdefault("controller", {}).setdefault("dsp0", {}).setdefault("block0", {})
    )

    for index in range(count):
        parameter = f"param{index}"
        block[parameter] = index
        block_controller[parameter] = {
            "@controller": 19,
            "@snapshot_disable": False,
        }

    if output_gain_assigned:
        tone["controller"]["dsp0"]["outputA"] = {
            "gain": {
                "@controller": 19,
                "@max": 20.0,
                "@min": -120.0,
                "@snapshot_disable": False,
            }
        }

    return preset


def _hls_text(data: dict) -> str:
    raw = json.dumps(data, indent=1).encode("utf-8")
    wrapper = {
        "compression": {
            "crc32": binascii.crc32(raw) & 0xFFFFFFFF,
            "decompressed_size": len(raw),
            "type": "zlib",
        },
        "encoded_data": base64.b64encode(zlib.compress(raw, level=9)).decode("ascii"),
    }
    return json.dumps(wrapper)


def _decoded_hls_data(hls_text: str) -> dict:
    wrapper = json.loads(hls_text)
    raw = zlib.decompress(base64.b64decode(wrapper["encoded_data"]))
    return json.loads(raw)


def test_lufs_error_sentinel_is_retained_per_snapshot(tmp_path) -> None:
    module = _load_legacy_module()
    csv_path = tmp_path / "analysis.csv"
    csv_path.write_text(
        "HelixPreset,LUFS1,CrestFactor1,LUFS2,CrestFactor2\n01A,ERROR,ERROR,-17.0,12.0\n",
        encoding="utf-8",
    )

    deltas = module.load_lufs_analysis_file(csv_path, snapshot_count=2)

    assert deltas == {"01A": {0: None, 1: 1.0}}


def test_lufs_skip_sentinel_omits_snapshot(tmp_path) -> None:
    module = _load_legacy_module()
    csv_path = tmp_path / "analysis.csv"
    csv_path.write_text(
        "HelixPreset,LUFS1,CrestFactor1,LUFS2,CrestFactor2\n01A,SKIP,SKIP,-17.0,12.0\n",
        encoding="utf-8",
    )

    deltas = module.load_lufs_analysis_file(csv_path, snapshot_count=2)

    assert deltas == {"01A": {1: 1.0}}


def test_custom_adjustments_bump_snapshot_targets(tmp_path) -> None:
    module = _load_legacy_module()
    csv_path = tmp_path / "analysis.csv"
    csv_path.write_text(
        "HelixPreset,LUFS1,CrestFactor1,LUFS2,CrestFactor2\n01A,-17.0,12.0,-17.0,12.0\n",
        encoding="utf-8",
    )
    adjustments_path = tmp_path / "custom.csv"
    adjustments_path.write_text("01A|2.0|-1.0\n", encoding="utf-8")

    custom_adjustments = module.load_custom_adjustments_file(adjustments_path, snapshot_count=2)
    deltas = module.load_lufs_analysis_file(
        csv_path,
        snapshot_count=2,
        custom_adjustments=custom_adjustments,
    )

    assert deltas == {"01A": {0: 3.0, 1: 0.0}}


def test_custom_adjustments_accept_comma_separator(tmp_path) -> None:
    module = _load_legacy_module()
    adjustments_path = tmp_path / "custom.csv"
    adjustments_path.write_text("01A,0.5,-2\n", encoding="utf-8")

    assert module.load_custom_adjustments_file(adjustments_path, snapshot_count=2) == {
        "01A": {0: 0.5, 1: -2.0}
    }


def test_assignment_extraction_includes_snapshot_names() -> None:
    module = _load_legacy_module()
    data = {
        "presets": [
            {
                "meta": {"name": "Lead"},
                "tone": {
                    "dsp0": {
                        "inputA": {"@input": 1},
                        "block0": {},
                        "outputA": {"@output": 6, "gain": -1.5},
                    },
                    "snapshot0": {
                        "@name": "Rhythm",
                        "controllers": {
                            "dsp0": {"outputA": {"gain": {"@value": -3.0}}},
                        },
                    },
                    "snapshot1": {"@name": "Solo"},
                },
            }
        ]
    }

    assignments = module.extract_preset_assignments(data)

    assert assignments[0]["snapshot_names"] == ["Rhythm", "Solo"]
    assert assignments[0]["snapshot_output_paths"] == ["dsp0.outputA"]
    assert assignments[0]["snapshot_output_levels"] == [[-3.0], [-1.5]]


def test_snapshot_level_assignment_includes_parallel_outputs() -> None:
    module = _load_legacy_module()
    data = {
        "presets": [
            {
                "meta": {"name": "Parallel"},
                "tone": {
                    "dsp0": {
                        "inputA": {"@input": 1},
                        "block0": {},
                        "outputA": {"@output": 6, "gain": -1.0},
                        "outputB": {"@output": 5, "gain": -3.0},
                    },
                    "snapshot0": {"@name": "Rhythm"},
                    "snapshot1": {"@name": "Lead"},
                },
            }
        ]
    }

    modified_json_text, snapshot_changes, gain_changes = module.process_json_structure(
        json.dumps(data),
        assign_output_gain=True,
    )
    modified = json.loads(modified_json_text)
    tone = modified["presets"][0]["tone"]

    assert snapshot_changes == 2
    assert gain_changes == 0
    assert "gain" in tone["controller"]["dsp0"]["outputA"]
    assert "gain" in tone["controller"]["dsp0"]["outputB"]
    assert tone["snapshot0"]["controllers"]["dsp0"]["outputA"]["gain"]["@value"] == -1.0
    assert tone["snapshot0"]["controllers"]["dsp0"]["outputB"]["gain"]["@value"] == -3.0
    assert tone["snapshot1"]["controllers"]["dsp0"]["outputA"]["gain"]["@value"] == -1.0
    assert tone["snapshot1"]["controllers"]["dsp0"]["outputB"]["gain"]["@value"] == -3.0


def test_snapshot_level_assignment_allows_helix_limit_boundary() -> None:
    module = _load_legacy_module()
    data = {"presets": [_preset_with_snapshot_assigned_properties("Boundary", 63)]}

    modified_json_text, snapshot_changes, gain_changes = module.process_json_structure(
        json.dumps(data),
        assign_output_gain=True,
    )
    modified = json.loads(modified_json_text)
    preset = modified["presets"][0]

    assert snapshot_changes == 1
    assert gain_changes == 0
    assert module.count_snapshot_assigned_properties(preset) == 64
    assert preset["tone"]["controller"]["dsp0"]["outputA"]["gain"]["@controller"] == 19


def test_snapshot_level_assignment_rejects_exceeding_helix_limit_without_mutation() -> None:
    module = _load_legacy_module()
    data = {"presets": [_preset_with_snapshot_assigned_properties("Full", 64)]}
    original = copy.deepcopy(data)

    with pytest.raises(ValueError, match="snapshot-assigned property limit"):
        module.process_json_structure(json.dumps(data), assign_output_gain=True)

    assert data == original


def test_snapshot_level_assignment_does_not_double_count_existing_output_gain() -> None:
    module = _load_legacy_module()
    data = {
        "presets": [
            _preset_with_snapshot_assigned_properties(
                "Already Assigned",
                63,
                output_gain_assigned=True,
            )
        ]
    }

    modified_json_text, snapshot_changes, gain_changes = module.process_json_structure(
        json.dumps(data),
        assign_output_gain=True,
    )
    preset = json.loads(modified_json_text)["presets"][0]

    assert snapshot_changes == 0
    assert gain_changes == 0
    assert module.count_snapshot_assigned_properties(preset) == 64
    assert preset["tone"]["snapshot0"]["controllers"]["dsp0"]["outputA"]["gain"]["@value"] == 0.0


def test_snapshot_level_assignment_rejects_setlist_before_partial_mutation() -> None:
    module = _load_legacy_module()
    data = {
        "presets": [
            _preset_with_snapshot_assigned_properties("Would Mutate", 0),
            _preset_with_snapshot_assigned_properties("Too Full", 64),
        ]
    }
    original = copy.deepcopy(data)

    with pytest.raises(ValueError, match=r'01B, "Too Full"'):
        module.process_json_structure(json.dumps(data), assign_output_gain=True)

    assert data == original


def test_snapshot_assignment_limit_error_does_not_write_partial_setlist(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_legacy_module()
    input_path = tmp_path / "input.hls"
    output_path = tmp_path / "output.hls"
    input_path.write_text(
        _hls_text(
            {
                "presets": [
                    _preset_with_snapshot_assigned_properties("Would Mutate", 0),
                    _preset_with_snapshot_assigned_properties("Too Full", 64),
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "helix_preset_handling",
            "-i",
            str(input_path),
            "-o",
            str(output_path),
            "--measurement",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert exc.value.code == 1
    assert "snapshot-assigned property limit" in capsys.readouterr().out
    assert not output_path.exists()


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


def test_adjust_snapshot_gains_applies_delta_to_parallel_outputs() -> None:
    module = _load_legacy_module()
    data = {
        "presets": [
            {
                "meta": {"name": "Parallel"},
                "tone": {
                    "global": {"@current_snapshot": 0},
                    "dsp0": {
                        "inputA": {"@input": 1},
                        "block0": {},
                        "outputA": {"@output": 10, "gain": -1.0},
                        "outputB": {"@output": 10, "gain": -3.0},
                    },
                    "snapshot0": {
                        "@name": "Rhythm",
                        "controllers": {
                            "dsp0": {
                                "outputA": {"gain": {"@value": -1.0}},
                                "outputB": {"gain": {"@value": -3.0}},
                            }
                        },
                    },
                },
            }
        ]
    }

    changes = module.adjust_snapshot_gains(data, {"01A": {0: 2.0}}, snapshot_count=1)
    tone = data["presets"][0]["tone"]
    snapshot = tone["snapshot0"]

    assert changes == 2
    assert tone["dsp0"]["outputA"]["@output"] == module.OUTPUT_XLR
    assert tone["dsp0"]["outputB"]["@output"] == module.OUTPUT_XLR
    assert tone["dsp0"]["outputA"]["gain"] == 1.0
    assert tone["dsp0"]["outputB"]["gain"] == -1.0
    assert snapshot["controllers"]["dsp0"]["outputA"]["gain"]["@value"] == 1.0
    assert snapshot["controllers"]["dsp0"]["outputB"]["gain"]["@value"] == -1.0


def test_adjust_snapshot_gains_ignores_default_snapshot_names() -> None:
    module = _load_legacy_module()
    data = {
        "presets": [
            {
                "meta": {"name": "Song"},
                "tone": {
                    "dsp0": {"outputA": {"@output": 10, "gain": -1.0}},
                    "snapshot0": {
                        "@name": "SNAPSHOT 1",
                        "controllers": {"dsp0": {"outputA": {"gain": {"@value": -1.0}}}},
                    },
                },
            }
        ]
    }

    changes = module.adjust_snapshot_gains(data, {"01A": {0: 2.0}}, snapshot_count=1)

    assert changes == 0
    assert (
        data["presets"][0]["tone"]["snapshot0"]["controllers"]["dsp0"]["outputA"]["gain"]["@value"]
        == -1.0
    )


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


def test_join_preset_files_to_setlist_contains_joined_presets(tmp_path) -> None:
    module = _load_legacy_module()
    first_path = tmp_path / "first.hlx"
    second_path = tmp_path / "second.hlx"
    first_path.write_text(json.dumps(_preset("First")), encoding="utf-8")
    second_path.write_text(json.dumps({"data": _preset("Second"), "meta": {"app": "HX Edit"}}))

    hls_text, metadata = module.join_preset_files_to_setlist([first_path, second_path])

    data = _decoded_hls_data(hls_text)
    assert [preset["meta"]["name"] for preset in data["presets"]] == ["First", "Second"]
    assert metadata["source_filenames"] == {"01A": "first.hlx", "01B": "second.hlx"}


def test_join_preset_files_to_setlist_uses_slot_ids(tmp_path) -> None:
    module = _load_legacy_module()
    preset_path = tmp_path / "lead.hlx"
    preset_path.write_text(json.dumps(_preset("Lead")), encoding="utf-8")

    hls_text, _ = module.join_preset_files_to_setlist([preset_path], slot_ids=["01B"])

    data = _decoded_hls_data(hls_text)
    assert module.is_default_preset(data["presets"][0])
    assert data["presets"][1]["meta"]["name"] == "Lead"


def test_split_setlist_to_preset_data_skips_empty_presets(tmp_path) -> None:
    module = _load_legacy_module()
    setlist_path = tmp_path / "setlist.hls"
    setlist_path.write_text(
        _hls_text({"presets": [_preset("Lead"), {"meta": {"name": "Empty"}, "tone": {}}]}),
        encoding="utf-8",
    )

    split_presets = module.split_setlist_to_preset_data(setlist_path)

    assert split_presets == [("Lead.hlx", _preset("Lead"))]


def test_split_setlist_reuses_original_filename_when_supplied(tmp_path) -> None:
    module = _load_legacy_module()
    setlist_path = tmp_path / "setlist.hls"
    setlist_path.write_text(_hls_text({"presets": [_preset("Lead")]}), encoding="utf-8")

    split_presets = module.split_setlist_to_preset_data(
        setlist_path, original_filenames={"01A": "Original Lead.hlx"}
    )

    assert split_presets[0][0] == "Original Lead.hlx"


def test_split_setlist_synthesizes_safe_filename_from_preset_name(tmp_path) -> None:
    module = _load_legacy_module()
    setlist_path = tmp_path / "setlist.hls"
    setlist_path.write_text(_hls_text({"presets": [_preset('Lead: / "A"')]}), encoding="utf-8")

    split_presets = module.split_setlist_to_preset_data(setlist_path)

    assert split_presets[0][0] == "Lead A.hlx"


def test_split_setlist_disambiguates_duplicate_synthesized_names(tmp_path) -> None:
    module = _load_legacy_module()
    setlist_path = tmp_path / "setlist.hls"
    setlist_path.write_text(
        _hls_text({"presets": [_preset("Lead"), _preset("Lead")]}),
        encoding="utf-8",
    )

    split_presets = module.split_setlist_to_preset_data(setlist_path)

    assert [filename for filename, _ in split_presets] == ["Lead 01A.hlx", "Lead 01B.hlx"]


def test_load_and_rebuild_hlx_preserves_wrapper_shape(tmp_path) -> None:
    module = _load_legacy_module()
    hlx_path = tmp_path / "wrapped.hlx"
    hlx_path.write_text(
        json.dumps({"data": _preset("Wrapped"), "meta": {"app": "HX Edit"}}),
        encoding="utf-8",
    )

    preset, wrapper = module.load_preset_file(hlx_path)
    preset["meta"]["name"] = "Renamed"
    rebuilt = module.rebuild_hlx_data(wrapper, preset)

    assert rebuilt["data"]["meta"]["name"] == "Renamed"
    assert rebuilt["meta"] == {"app": "HX Edit"}
