from __future__ import annotations

import base64
import binascii
import copy
import csv
import json
import zlib
from pathlib import Path

import pytest

from matchpatch.devices.base import PatchFileAdjustments
from matchpatch.devices.line6.podgo import PodGoPatchFileHandler
from matchpatch.devices.line6.podgo import preset_handling as podgo
from matchpatch.workflow import NormalizationPolicy

TEST_DATA_DIR = Path("tests/input_files/line6/podgo")
PGP_FIXTURES = [
    TEST_DATA_DIR / "Highgain.pgp",
    TEST_DATA_DIR / "Fender.pgp",
    TEST_DATA_DIR / "Marshall.pgp",
]
PGS_FIXTURE = TEST_DATA_DIR / "Setlist.pgs"


def _load_pgp(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _decode_pgs(path: Path = PGS_FIXTURE) -> tuple[dict, dict]:
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    raw = zlib.decompress(base64.b64decode(wrapper["encoded_data"]))
    return wrapper, json.loads(raw)


def test_podgo_sample_pgp_shape_and_known_io_values() -> None:
    for path in PGP_FIXTURES:
        wrapper = _load_pgp(path)
        preset = wrapper["data"]
        tone = preset["tone"]

        assert wrapper["schema"] == "L6Preset"
        assert "tone" in preset
        assert tone["dsp0"]["input"]["@input"] == podgo.PODGO_INPUT_GUITAR
        assert tone["dsp0"]["input"]["@model"] == "P34_AppDSPFlowInput"
        assert tone["dsp0"]["output"]["@output"] == podgo.PODGO_OUTPUT_MAIN
        assert tone["dsp0"]["output"]["@model"] == "P34_AppDSPFlowOutput"
        assert "gain" in tone["dsp0"]["output"]
        assert tone.get("dsp1") in ({}, None)
        assert {key for key in tone if key.startswith("snapshot")} == {
            "snapshot0",
            "snapshot1",
            "snapshot2",
            "snapshot3",
        }


def test_podgo_sample_pgs_decodes_to_128_banked_presets() -> None:
    wrapper, data = _decode_pgs()

    assert wrapper["schema"] == "L6Setlist"
    assert len(data["presets"]) == 128
    assert [podgo.preset_index_to_podgo(index) for index in range(5)] == [
        "01A",
        "01B",
        "01C",
        "01D",
        "02A",
    ]


def test_podgo_list_assignments_metadata_and_measurement_stage_conversion() -> None:
    json_text, original = podgo.load_input(PGP_FIXTURES[0])
    data = json.loads(json_text)

    assignments = podgo.extract_preset_assignments(data)
    assert assignments[0]["id"] == 1
    assert assignments[0]["device_patch"] == "01A"
    assert assignments[0]["name"] == "Highgain"
    assert assignments[0]["snapshot_output_paths"] == ["dsp0.output"]
    assert len(assignments[0]["snapshot_names"]) == 4

    metadata = podgo.extract_metadata(PGP_FIXTURES[0], json_text, original)
    assert metadata["file_type"] == "pgp"
    assert metadata["wrapper"]["schema"] == "L6Preset"

    measurement_text, input_changes, output_changes = podgo.convert_json_text(
        json_text, "measurement"
    )
    measurement = json.loads(measurement_text)
    measurement_dsp0 = measurement["presets"][0]["tone"]["dsp0"]
    assert input_changes == 1
    assert output_changes == 1
    assert measurement_dsp0["input"]["@input"] == podgo.PODGO_INPUT_USB_3_4
    assert measurement_dsp0["output"]["@output"] == podgo.PODGO_OUTPUT_USB_1_2

    stage_text, input_changes, output_changes = podgo.convert_json_text(measurement_text, "stage")
    stage = json.loads(stage_text)
    stage_dsp0 = stage["presets"][0]["tone"]["dsp0"]
    assert input_changes == 1
    assert output_changes == 1
    assert stage_dsp0["input"]["@input"] == podgo.PODGO_INPUT_GUITAR
    assert stage_dsp0["output"]["@output"] == podgo.PODGO_OUTPUT_MAIN


def test_podgo_measurement_conversion_replaces_non_guitar_input() -> None:
    json_text, _ = podgo.load_input(PGP_FIXTURES[1])
    data = json.loads(json_text)
    data["presets"][0]["tone"]["dsp0"]["input"]["@input"] = 2

    measurement_text, input_changes, _ = podgo.convert_json_text(json.dumps(data), "measurement")
    measurement = json.loads(measurement_text)

    assert input_changes == 1
    assert measurement["presets"][0]["tone"]["dsp0"]["input"]["@input"] == podgo.PODGO_INPUT_USB_3_4


def test_podgo_output_gain_assignment_preserves_pan_and_fills_snapshots() -> None:
    json_text, _ = podgo.load_input(PGP_FIXTURES[0])
    data = json.loads(json_text)
    preset = data["presets"][0]
    tone = preset["tone"]
    existing_pan = copy.deepcopy(tone["controller"]["dsp0"]["output"]["pan"])

    changes = podgo.assign_snapshot_level(data)

    assert changes == 1
    assert tone["controller"]["dsp0"]["output"]["pan"] == existing_pan
    assert tone["controller"]["dsp0"]["output"]["gain"] == {
        "@controller": podgo.PODGO_SNAPSHOT_CONTROLLER,
        "@max": 20.0,
        "@min": -120.0,
    }
    for snapshot_index in range(4):
        snapshot_gain = tone[f"snapshot{snapshot_index}"]["controllers"]["dsp0"]["output"]["gain"]
        assert snapshot_gain == {
            "@fs_enabled": False,
            "@value": preset["tone"]["dsp0"]["output"]["gain"],
        }


def test_podgo_output_gain_assignment_enforces_capacity() -> None:
    json_text, _ = podgo.load_input(PGP_FIXTURES[0])
    data = json.loads(json_text)
    preset = data["presets"][0]
    controller = preset["tone"].setdefault("controller", {}).setdefault("dsp0", {})
    dsp0 = preset["tone"]["dsp0"]

    for index in range(64):
        block_name = f"block{index}"
        dsp0[block_name] = {"param": 0}
        controller[block_name] = {"param": {"@controller": podgo.PODGO_SNAPSHOT_CONTROLLER}}

    with pytest.raises(ValueError, match="Pod Go snapshot-assigned parameter limit"):
        podgo.validate_controller_assignment_capacity(data)


def test_podgo_output_gain_assignment_repairs_helix_style_snapshot_controller() -> None:
    json_text, _ = podgo.load_input(PGP_FIXTURES[0])
    data = json.loads(json_text)
    tone = data["presets"][0]["tone"]
    tone.setdefault("controller", {}).setdefault("dsp0", {}).setdefault("output", {})["gain"] = {
        "@controller": 19,
        "@max": 20.0,
        "@min": -120.0,
        "@snapshot_disable": False,
    }

    changes = podgo.assign_snapshot_level(data)

    assert changes == 1
    assert tone["controller"]["dsp0"]["output"]["gain"] == {
        "@controller": podgo.PODGO_SNAPSHOT_CONTROLLER,
        "@max": 20.0,
        "@min": -120.0,
    }


def test_podgo_gain_adjustment_updates_snapshot_output_gain() -> None:
    json_text, _ = podgo.load_input(PGP_FIXTURES[1])
    data = json.loads(json_text)

    changes = podgo.adjust_snapshot_gains(
        data,
        {"01A": {0: 1.5}},
        gain_deadband_db=0.0,
    )

    snapshot_gain = data["presets"][0]["tone"]["snapshot0"]["controllers"]["dsp0"]["output"]["gain"]
    assert changes == 1
    assert data["presets"][0]["tone"]["dsp0"]["output"]["gain"] == 1.5
    assert snapshot_gain["@value"] == 1.5


def test_podgo_gain_adjustment_syncs_output_gain_to_current_snapshot() -> None:
    json_text, _ = podgo.load_input(PGP_FIXTURES[2])
    data = json.loads(json_text)
    tone = data["presets"][0]["tone"]

    assert tone["global"]["@current_snapshot"] == 3

    changes = podgo.adjust_snapshot_gains(
        data,
        {"01A": {0: 1.0, 1: 2.0, 2: 3.0, 3: 4.0}},
        gain_deadband_db=0.0,
    )

    assert changes == 4
    assert tone["dsp0"]["output"]["gain"] == 4.0
    assert tone["snapshot3"]["controllers"]["dsp0"]["output"]["gain"]["@value"] == 4.0


def test_podgo_gui_save_as_manual_adjustments_snapshot_assign_output_gain(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "analysis.csv"
    fieldnames = [
        "DevicePatch",
        "LUFS1",
        "CrestFactor1",
        "LUFS2",
        "CrestFactor2",
        "LUFS3",
        "CrestFactor3",
        "LUFS4",
        "CrestFactor4",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "DevicePatch": "01A",
                "LUFS1": "-16",
                "CrestFactor1": "12",
                "LUFS2": "-16",
                "CrestFactor2": "12",
                "LUFS3": "-16",
                "CrestFactor3": "12",
                "LUFS4": "-16",
                "CrestFactor4": "12",
            }
        )
    output_path = tmp_path / "adjusted.pgs"
    handler = PodGoPatchFileHandler(Path("."))

    handler.apply_analysis_csv(
        PGS_FIXTURE,
        output_path,
        csv_path,
        False,
        -16.0,
        NormalizationPolicy(snapshot_count=4),
        None,
        PatchFileAdjustments({}, {}, {"01A": {0: 1.0, 1: 2.0, 2: 3.0, 3: 4.0}}),
    )

    _, data = _decode_pgs(output_path)
    tone = data["presets"][0]["tone"]

    assert tone["controller"]["dsp0"]["output"]["gain"] == {
        "@controller": podgo.PODGO_SNAPSHOT_CONTROLLER,
        "@max": 20.0,
        "@min": -120.0,
    }
    assert [
        tone[f"snapshot{snapshot}"]["controllers"]["dsp0"]["output"]["gain"]["@value"]
        for snapshot in range(4)
    ] == [1.0, 2.0, 3.0, 4.0]


def test_podgo_parser_accepts_shared_normalization_policy_flags(monkeypatch) -> None:
    seen = {}

    def fake_load_lufs_analysis_file(
        filename,
        target_lufs,
        snapshot_count,
        crest_factor_reference_db,
        crest_factor_correction_ratio,
        max_crest_factor_correction_db,
        custom_adjustments=None,
    ):
        seen["args"] = (
            filename,
            target_lufs,
            snapshot_count,
            crest_factor_reference_db,
            crest_factor_correction_ratio,
            max_crest_factor_correction_db,
            custom_adjustments,
        )
        return {"01A": {0: 1.0}}

    monkeypatch.setattr(podgo.helix_common, "load_lufs_analysis_file", fake_load_lufs_analysis_file)
    args = podgo._build_parser().parse_args(
        [
            "-i",
            "setlist.pgs",
            "-o",
            "adjusted.pgs",
            "--adjust-gain",
            "-g",
            "analysis.csv",
            "--target-lufs",
            "-16.0",
            "--snapshot-count",
            "4",
            "--solo-regex",
            r"(?i)\bsolo\b",
            "--ignore-snapshot-regex",
            r"(?i)^SNAPSHOT [1-9]\d*$",
            "--solo-gain-bump-db",
            "3.0",
            "--crest-factor-reference-db",
            "12.0",
            "--crest-factor-correction-ratio",
            "0.4",
            "--max-crest-factor-correction-db",
            "3.0",
            "--gain-deadband-db",
            "0.05",
        ]
    )

    assert podgo._load_gain_deltas(args) == {"01A": {0: 1.0}}
    assert seen["args"] == ("analysis.csv", -16.0, 4, 12.0, 0.4, 3.0, None)
    assert args.solo_regex == r"(?i)\bsolo\b"
    assert args.ignore_snapshot_regex == r"(?i)^SNAPSHOT [1-9]\d*$"
    assert args.solo_gain_bump_db == 3.0
    assert args.gain_deadband_db == 0.05


def test_podgo_adjusted_preset_restores_original_input_value() -> None:
    original_text, _ = podgo.load_input(PGP_FIXTURES[0])
    modified_text, _, _ = podgo.convert_json_text(original_text, "measurement")

    restored = json.loads(podgo.restore_original_input_values(modified_text, original_text))

    assert restored["presets"][0]["tone"]["dsp0"]["input"]["@input"] == podgo.PODGO_INPUT_GUITAR
    assert restored["presets"][0]["tone"]["dsp0"]["output"]["@output"] == (
        podgo.PODGO_OUTPUT_USB_1_2
    )


def test_podgo_adjusted_setlist_restores_original_input_values_by_slot() -> None:
    original_text, _ = podgo.load_input(PGS_FIXTURE)
    modified = json.loads(original_text)
    modified["presets"][0]["tone"]["dsp0"]["input"]["@input"] = podgo.PODGO_INPUT_USB_3_4
    modified["presets"][1]["tone"]["dsp0"]["input"]["@input"] = podgo.PODGO_INPUT_USB_3_4

    restored = json.loads(podgo.restore_original_input_values(json.dumps(modified), original_text))
    original = json.loads(original_text)

    assert (
        restored["presets"][0]["tone"]["dsp0"]["input"]["@input"]
        == (original["presets"][0]["tone"]["dsp0"]["input"]["@input"])
    )
    assert (
        restored["presets"][1]["tone"]["dsp0"]["input"]["@input"]
        == (original["presets"][1]["tone"]["dsp0"]["input"]["@input"])
    )


def test_podgo_diff_presets_and_snapshots_ignore_names_but_track_signal(tmp_path: Path) -> None:
    original = _load_pgp(PGP_FIXTURES[1])
    renamed = copy.deepcopy(original)
    renamed["data"]["meta"]["name"] = "Renamed"
    renamed["data"]["tone"]["snapshot0"]["@name"] = "Intro"
    changed = copy.deepcopy(renamed)
    changed["data"]["tone"]["snapshot1"]["controllers"]["dsp0"]["output"]["pan"]["@value"] = 0.75

    original_path = tmp_path / "original.pgp"
    renamed_path = tmp_path / "renamed.pgp"
    changed_path = tmp_path / "changed.pgp"
    original_path.write_text(json.dumps(original), encoding="utf-8")
    renamed_path.write_text(json.dumps(renamed), encoding="utf-8")
    changed_path.write_text(json.dumps(changed), encoding="utf-8")

    assert podgo.extract_diff_preset_ids(renamed_path, original_path) == []
    assert podgo.extract_diff_snapshot_ids(renamed_path, original_path) == {}
    assert podgo.extract_diff_preset_ids(changed_path, original_path) == [1]
    assert podgo.extract_diff_snapshot_ids(changed_path, original_path) == {1: [2]}


def test_podgo_split_and_join_preserve_wrapper_and_compression(tmp_path: Path) -> None:
    split = podgo.split_setlist_to_preset_data(PGS_FIXTURE, selected_ids=[1, "01B"])

    assert [filename for filename, _ in split] == ["Fender.pgp", "Marshall.pgp"]
    assert split[0][1]["schema"] == "L6Preset"
    assert split[0][1]["data"]["meta"]["name"] == "Fender"

    first = tmp_path / "first.pgp"
    second = tmp_path / "second.pgp"
    first.write_text(json.dumps(split[0][1]), encoding="utf-8")
    second.write_text(json.dumps(split[1][1]), encoding="utf-8")

    joined_text, metadata = podgo.join_preset_files_to_setlist(
        [first, second],
        slot_ids=["01A", "01B"],
    )
    wrapper = json.loads(joined_text)
    raw = zlib.decompress(base64.b64decode(wrapper["encoded_data"]))
    data = json.loads(raw)

    assert wrapper["schema"] == "L6Setlist"
    assert wrapper["compression"]["decompressed_size"] == len(raw)
    assert wrapper["compression"]["crc32"] == binascii.crc32(raw) & 0xFFFFFFFF
    assert [preset["meta"]["name"] for preset in data["presets"][:2]] == [
        "Fender",
        "Marshall",
    ]
    assert metadata["source_filenames"] == {"01A": "first.pgp", "01B": "second.pgp"}
