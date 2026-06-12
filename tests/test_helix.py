from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from matchpatch.devices.base import PatchAssignment, PatchFileAdjustments, SteeringOptions
from matchpatch.devices.helix import (
    HelixDeviceProfile,
    HelixMidiController,
    HelixPatchFileHandler,
)


def load_legacy_preset_handling():
    script_path = Path(__file__).resolve().parents[1] / "Python" / "preset_handling.py"
    spec = importlib.util.spec_from_file_location("preset_handling", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_handler(tmp_path: Path) -> HelixPatchFileHandler:
    return HelixPatchFileHandler(tmp_path)


def test_patch_file_validation_and_automation_path(tmp_path) -> None:
    handler = make_handler(tmp_path)
    handler.validate_input(Path("setlist.HLS"))
    handler.validate_input(Path("preset.hlx"))
    handler.validate_output(Path("preset.hlx"), Path("result.HLX"))

    with pytest.raises(ValueError, match=r"\.hls or \.hlx"):
        handler.validate_input(Path("setlist.json"))
    with pytest.raises(ValueError, match=r"\.hlx"):
        handler.validate_output(Path("preset.hlx"), Path("result.hls"))

    assert handler.automation_output_path(Path("preset.hlx"), "_measurement") == Path(
        "preset_measurement.hlx"
    )


def test_parse_and_format_patch_ids(tmp_path) -> None:
    handler = make_handler(tmp_path)

    assert handler.parse_patch_set(" 01a, 02B,01A ") == [1, 6]
    assert handler.format_patch_id(6) == "02B"

    for invalid in ("", "0A", "A", "01E"):
        with pytest.raises(ValueError, match="Helix"):
            handler.parse_patch_set(invalid)


@given(preset_ids=st.lists(st.integers(min_value=1, max_value=128), min_size=1))
def test_patch_ids_round_trip_and_preserve_first_occurrence(preset_ids: list[int]) -> None:
    handler = HelixPatchFileHandler(Path("."))
    formatted = ",".join(handler.format_patch_id(preset_id) for preset_id in preset_ids)

    assert handler.parse_patch_set(formatted) == list(dict.fromkeys(preset_ids))


def test_select_preset_ids_for_setlists_and_presets(tmp_path) -> None:
    handler = make_handler(tmp_path)
    assignments = [
        PatchAssignment(1, "01A", "Clean"),
        PatchAssignment(6, "02B", "Lead"),
    ]

    assert handler.select_preset_ids(Path("set.hls"), assignments, None) == [1, 6]
    assert handler.select_preset_ids(Path("set.hls"), assignments, [6]) == [6]
    assert handler.select_preset_ids(Path("one.hlx"), assignments, [10]) == [10]

    with pytest.raises(ValueError, match="missing"):
        handler.select_preset_ids(Path("set.hls"), assignments, [2])
    with pytest.raises(ValueError, match="exactly one"):
        handler.select_preset_ids(Path("one.hlx"), assignments, None)


def test_list_assignments_and_measurement_delegate_to_legacy_script(tmp_path, monkeypatch) -> None:
    handler = make_handler(tmp_path)
    calls = []
    payload = [
        {
            "id": 1,
            "helix_preset": "01A",
            "name": "Clean",
            "snapshot_names": ["Rhythm", "Solo"],
            "snapshot_output_levels": [[0.0], [-3.5, -4.0]],
        }
    ]

    def fake_run(*args, capture=False, log_output=True):
        calls.append((args, capture))
        return subprocess.CompletedProcess([], 0, stdout=json.dumps(payload))

    monkeypatch.setattr(handler, "_run", fake_run)

    assert handler.list_assignments(Path("set.hls")) == [
        PatchAssignment(1, "01A", "Clean", ("Rhythm", "Solo"), ((0.0,), (-3.5, -4.0)))
    ]
    handler.create_measurement_file(Path("set.hls"), Path("measurement.hls"))
    assert calls[1][0] == ("-i", Path("set.hls"), "-o", Path("measurement.hls"), "--measurement")


def test_metadata_delegates_to_legacy_script(tmp_path, monkeypatch) -> None:
    handler = make_handler(tmp_path)
    payload = {"file_type": "hls", "metadata": [{"path": "$.meta", "value": {"name": "Set"}}]}
    calls = []

    def fake_run(*args, capture=False, log_output=True):
        calls.append((args, capture, log_output))
        return subprocess.CompletedProcess([], 0, stdout=json.dumps(payload))

    monkeypatch.setattr(handler, "_run", fake_run)

    assert handler.metadata(Path("set.hls")) == payload
    assert calls == [
        (
            ("-i", Path("set.hls"), "--metadata"),
            True,
            False,
        )
    ]


def test_diff_preset_ids_delegates_to_legacy_script(tmp_path, monkeypatch) -> None:
    handler = make_handler(tmp_path)
    calls = []

    def fake_run(*args, capture=False, log_output=True):
        calls.append((args, capture, log_output))
        return subprocess.CompletedProcess([], 0, stdout="[1, 6]")

    monkeypatch.setattr(handler, "_run", fake_run)

    assert handler.diff_preset_ids(Path("set.hls"), Path("previous.hls")) == [1, 6]
    assert calls == [
        (
            ("-i", Path("set.hls"), "--diff-presets", Path("previous.hls")),
            True,
            False,
        )
    ]

    with pytest.raises(ValueError, match="same extension"):
        handler.diff_preset_ids(Path("set.hls"), Path("previous.hlx"))


def test_diff_snapshot_ids_delegates_to_legacy_script(tmp_path, monkeypatch) -> None:
    handler = make_handler(tmp_path)
    calls = []

    def fake_run(*args, capture=False, log_output=True):
        calls.append((args, capture, log_output))
        return subprocess.CompletedProcess([], 0, stdout='{"1": [1, 3], "6": [2]}')

    monkeypatch.setattr(handler, "_run", fake_run)

    assert handler.diff_snapshot_ids(Path("set.hls"), Path("previous.hls"), 4) == {
        1: (1, 3),
        6: (2,),
    }
    assert calls == [
        (
            (
                "-i",
                Path("set.hls"),
                "--diff-snapshots",
                Path("previous.hls"),
                "--snapshot-count",
                4,
            ),
            True,
            False,
        )
    ]

    with pytest.raises(ValueError, match="same extension"):
        handler.diff_snapshot_ids(Path("set.hls"), Path("previous.hlx"), 4)


def test_legacy_diff_signature_ignores_names_and_colors() -> None:
    legacy = load_legacy_preset_handling()
    first = {
        "meta": {"name": "Clean"},
        "tone": {
            "dsp0": {
                "block0": {"@model": "amp", "gain": 2.0, "@color": 3},
                "outputA": {"@output": 6, "gain": 0.0},
            },
            "snapshot0": {"@name": "Verse", "@pedalstate": {"block0": True}},
        },
    }
    renamed = {
        "meta": {"name": "Renamed"},
        "tone": {
            "dsp0": {
                "block0": {"@model": "amp", "gain": 2.0, "@color": 7},
                "outputA": {"@output": 6, "gain": 0.0},
            },
            "snapshot0": {"@name": "Intro", "@pedalstate": {"block0": True}},
        },
    }
    changed_parameter = {
        "meta": {"name": "Clean"},
        "tone": {
            "dsp0": {
                "block0": {"@model": "amp", "gain": 3.0, "@color": 3},
                "outputA": {"@output": 6, "gain": 0.0},
            },
            "snapshot0": {"@name": "Verse", "@pedalstate": {"block0": True}},
        },
    }

    assert legacy.canonical_preset_signal_content(first) == legacy.canonical_preset_signal_content(
        renamed
    )
    assert legacy.canonical_preset_signal_content(first) != legacy.canonical_preset_signal_content(
        changed_parameter
    )


def test_legacy_snapshot_diff_ignores_names_but_tracks_snapshot_assignments() -> None:
    legacy = load_legacy_preset_handling()
    current = {
        "tone": {
            "dsp0": {"block0": {"@model": "amp", "gain": 2.0}},
            "snapshot0": {"@name": "Verse", "@pedalstate": {"block0": True}},
            "snapshot1": {"@name": "Lead", "@pedalstate": {"block0": False}},
        },
    }
    renamed = {
        "tone": {
            "dsp0": {"block0": {"@model": "amp", "gain": 2.0}},
            "snapshot0": {"@name": "Intro", "@pedalstate": {"block0": True}},
            "snapshot1": {"@name": "Solo", "@pedalstate": {"block0": False}},
        },
    }
    snapshot_changed = {
        "tone": {
            "dsp0": {"block0": {"@model": "amp", "gain": 2.0}},
            "snapshot0": {"@name": "Verse", "@pedalstate": {"block0": True}},
            "snapshot1": {"@name": "Lead", "@pedalstate": {"block0": True}},
        },
    }
    layout_changed = {
        "tone": {
            "dsp0": {"block0": {"@model": "amp", "gain": 3.0}},
            "snapshot0": {"@name": "Verse", "@pedalstate": {"block0": True}},
            "snapshot1": {"@name": "Lead", "@pedalstate": {"block0": False}},
        },
    }

    assert legacy.canonical_snapshot_signal_content(current, 0) == (
        legacy.canonical_snapshot_signal_content(renamed, 0)
    )
    assert legacy.canonical_snapshot_signal_content(current, 1) != (
        legacy.canonical_snapshot_signal_content(snapshot_changed, 1)
    )
    assert legacy.canonical_non_snapshot_signal_content(current) != (
        legacy.canonical_non_snapshot_signal_content(layout_changed)
    )


def test_legacy_snapshot_diff_tracks_snapshot_assigned_parameter_values(tmp_path) -> None:
    legacy = load_legacy_preset_handling()
    previous_preset = {
        "meta": {"name": "Clean"},
        "tone": {
            "global": {"@current_snapshot": 0},
            "dsp0": {
                "block0": {"@model": "amp", "gain": 2.0},
            },
            "controller": {
                "dsp0": {
                    "block0": {
                        "gain": {"@controller": 19, "@snapshot_disable": False},
                    },
                },
            },
            "snapshot0": {
                "@name": "Verse",
                "controllers": {
                    "dsp0": {"block0": {"gain": {"@fs_enabled": False, "@value": 2.0}}},
                },
            },
            "snapshot1": {
                "@name": "Lead",
                "controllers": {
                    "dsp0": {"block0": {"gain": {"@fs_enabled": False, "@value": 4.0}}},
                },
            },
        },
    }
    current_preset = json.loads(json.dumps(previous_preset))
    current_preset["tone"]["global"]["@current_snapshot"] = 1
    current_preset["tone"]["dsp0"]["block0"]["gain"] = 4.5
    current_preset["tone"]["snapshot1"]["controllers"]["dsp0"]["block0"]["gain"]["@value"] = 4.5
    previous_path = tmp_path / "previous.hlx"
    current_path = tmp_path / "current.hlx"
    previous_path.write_text(json.dumps(previous_preset), encoding="utf-8")
    current_path.write_text(json.dumps(current_preset), encoding="utf-8")

    assert legacy.canonical_non_snapshot_signal_content(current_preset) == (
        legacy.canonical_non_snapshot_signal_content(previous_preset)
    )
    assert legacy.extract_diff_snapshot_ids(current_path, previous_path, snapshot_count=2) == {
        1: [2]
    }


def test_legacy_script_runner_builds_subprocess_call(tmp_path, monkeypatch) -> None:
    handler = make_handler(tmp_path)
    calls = []
    completed = subprocess.CompletedProcess([], 0, stdout="ok")
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)) or completed
    )

    assert handler._run("--list-presets", capture=True) is completed
    command, options = calls[0]
    assert command[0][0] == sys.executable
    assert command[0][-1] == "--list-presets"
    assert options["stdout"] is subprocess.PIPE
    assert options["stderr"] is subprocess.PIPE


def test_frozen_legacy_script_runner_executes_in_process(tmp_path, monkeypatch) -> None:
    script = tmp_path / "Python" / "preset_handling.py"
    script.parent.mkdir()
    script.write_text(
        "import sys\n"
        "print('args=' + ','.join(sys.argv[1:]))\n"
        "print('error stream', file=sys.stderr)\n",
        encoding="utf-8",
    )
    handler = make_handler(tmp_path)
    original_argv = sys.argv[:]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("frozen legacy runner must not spawn a subprocess"),
    )

    completed = handler._run("--list-presets", capture=True)

    assert completed.args == [str(script), "--list-presets"]
    assert completed.returncode == 0
    assert completed.stdout == "args=--list-presets\n"
    assert completed.stderr == "error stream\n"
    assert sys.argv == original_argv


def test_frozen_legacy_script_runner_raises_called_process_error(tmp_path, monkeypatch) -> None:
    script = tmp_path / "Python" / "preset_handling.py"
    script.parent.mkdir()
    script.write_text(
        "import sys\nprint('before exit')\nprint('failed', file=sys.stderr)\nraise SystemExit(2)\n",
        encoding="utf-8",
    )
    handler = make_handler(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    with pytest.raises(subprocess.CalledProcessError) as exc:
        handler._run("--metadata", capture=True)

    assert exc.value.returncode == 2
    assert exc.value.stdout == "before exit\n"
    assert exc.value.stderr == "failed\n"


def test_legacy_script_runner_forwards_captured_output_to_logger(tmp_path, monkeypatch) -> None:
    handler = make_handler(tmp_path)
    messages = []
    handler.set_log_callback(messages.append)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, stdout="first\nsecond\n", stderr=""
        ),
    )

    handler._run("--measurement")

    assert messages == ["first", "second"]


def test_apply_analysis_csv_translates_generic_patch_column(tmp_path, monkeypatch) -> None:
    handler = make_handler(tmp_path)
    csv_path = tmp_path / "measurements.csv"
    csv_path.write_text("Preset,DevicePatch,LUFS1\n1,01A,-15.5\n", encoding="utf-8")
    seen = {}

    def fake_run(*args, capture=False):
        legacy = Path(args[args.index("-g") + 1])
        with legacy.open(newline="", encoding="utf-8") as csv_file:
            seen["rows"] = list(csv.DictReader(csv_file))
        seen["args"] = args
        seen["legacy"] = legacy
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(handler, "_run", fake_run)
    handler.apply_analysis_csv(Path("set.hls"), Path("adjusted.hls"), csv_path, True, -16.0)

    assert seen["rows"] == [{"Preset": "1", "HelixPreset": "01A", "LUFS1": "-15.5"}]
    assert "--ignore-bad-lufs" in seen["args"]
    assert seen["args"][seen["args"].index("--solo-regex") + 1] == r"(?i)\bsolo\b"
    assert (
        seen["args"][seen["args"].index("--ignore-snapshot-regex") + 1]
        == r"(?i)^SNAPSHOT [1-9]\d*$"
    )
    assert not seen["legacy"].exists()


def test_apply_analysis_csv_passes_manual_adjustments_json(tmp_path, monkeypatch) -> None:
    handler = make_handler(tmp_path)
    csv_path = tmp_path / "measurements.csv"
    csv_path.write_text("Preset,DevicePatch,LUFS1\n1,01A,-15.5\n", encoding="utf-8")
    seen = {}

    def fake_run(*args, capture=False):
        adjustments_path = Path(args[args.index("--manual-adjustments") + 1])
        seen["adjustments"] = json.loads(adjustments_path.read_text(encoding="utf-8"))
        seen["path"] = adjustments_path
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(handler, "_run", fake_run)
    handler.apply_analysis_csv(
        Path("set.hls"),
        Path("adjusted.hls"),
        csv_path,
        True,
        -16.0,
        adjustments=PatchFileAdjustments(
            {"01A": "Lead"},
            {"01A": {0: "Solo"}},
            {"01A": {0: 1.5}},
        ),
    )

    assert seen["adjustments"] == {
        "preset_names": {"01A": "Lead"},
        "snapshot_names": {"01A": {"0": "Solo"}},
        "gain_deltas": {"01A": {"0": 1.5}},
    }
    assert not seen["path"].exists()


def test_apply_analysis_csv_passes_custom_adjustments_file(tmp_path, monkeypatch) -> None:
    handler = make_handler(tmp_path)
    csv_path = tmp_path / "measurements.csv"
    custom_path = tmp_path / "custom.csv"
    csv_path.write_text("Preset,DevicePatch,LUFS1\n1,01A,-15.5\n", encoding="utf-8")
    custom_path.write_text("01A,1.0\n", encoding="utf-8")
    seen = {}

    def fake_run(*args, capture=False):
        seen["args"] = args
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(handler, "_run", fake_run)
    handler.apply_analysis_csv(
        Path("set.hls"),
        Path("adjusted.hls"),
        csv_path,
        True,
        -16.0,
        custom_adjustments_path=custom_path,
    )

    assert seen["args"][seen["args"].index("--custom-adjustments-file") + 1] == custom_path


def test_apply_analysis_csv_always_tolerates_bad_lufs_and_cleans_up_on_failure(
    tmp_path, monkeypatch
) -> None:
    handler = make_handler(tmp_path)
    csv_path = tmp_path / "measurements.csv"
    csv_path.write_text("Preset,DevicePatch\n1,01A\n", encoding="utf-8")
    seen = {}

    def fail(*args, capture=False):
        seen["args"] = args
        seen["legacy"] = Path(args[args.index("-g") + 1])
        raise RuntimeError("legacy failure")

    monkeypatch.setattr(handler, "_run", fail)

    with pytest.raises(RuntimeError, match="legacy failure"):
        handler.apply_analysis_csv(Path("set.hls"), Path("out.hls"), csv_path, False, -16)

    assert "--ignore-bad-lufs" in seen["args"]
    assert not seen["legacy"].exists()


def test_apply_analysis_csv_reports_legacy_stderr(tmp_path, monkeypatch) -> None:
    handler = make_handler(tmp_path)
    csv_path = tmp_path / "measurements.csv"
    csv_path.write_text("Preset,DevicePatch\n1,01A\n", encoding="utf-8")

    def fail(*args, capture=False):
        raise subprocess.CalledProcessError(
            1,
            ["legacy"],
            stderr="ERROR: Implausible output gain 21.9 dB for 17B Solo.",
        )

    monkeypatch.setattr(handler, "_run", fail)

    with pytest.raises(RuntimeError, match="Implausible output gain 21.9 dB for 17B Solo"):
        handler.apply_analysis_csv(Path("set.hls"), Path("out.hls"), csv_path, False, -16)


def test_apply_analysis_csv_filters_gain_lines_from_error_popup(tmp_path, monkeypatch) -> None:
    handler = make_handler(tmp_path)
    csv_path = tmp_path / "measurements.csv"
    csv_path.write_text("Preset,DevicePatch\n1,01A\n", encoding="utf-8")

    def fail(*args, capture=False, log_output=True):
        raise subprocess.CalledProcessError(
            1,
            ["legacy"],
            output=(
                "[GAIN] 01A SNAPSHOT 1 | 0.0 dB -> 8.1 dB (Delta: +8.1 dB)\n"
                "ERROR: Implausible output gain 21.9 dB for 17B Solo.\n"
            ),
        )

    monkeypatch.setattr(handler, "_run", fail)

    with pytest.raises(RuntimeError) as exc:
        handler.apply_analysis_csv(Path("set.hls"), Path("out.hls"), csv_path, False, -16)

    assert "Implausible output gain" in str(exc.value)
    assert "[GAIN]" not in str(exc.value)


def test_midi_controller_sends_program_and_snapshot_messages(monkeypatch) -> None:
    sent = []
    sleeps = []
    port = SimpleNamespace(send=sent.append, close=lambda: sent.append("closed"))
    mido = SimpleNamespace(
        get_output_names=lambda: ["Other", "Line 6 Helix MIDI"],
        open_output=lambda name: port,
        Message=lambda message_type, **kwargs: (message_type, kwargs),
    )
    monkeypatch.setitem(sys.modules, "mido", mido)
    monkeypatch.setattr("matchpatch.devices.helix.time.sleep", sleeps.append)
    options = SteeringOptions("helix", 2, 0.5, 0.05, 0.25)

    with HelixMidiController(options) as controller:
        controller.activate_preset(6)
        controller.reapply_snapshot(1)
        controller.reapply_snapshot(2)

    assert sent[:3] == [
        ("program_change", {"channel": 2, "program": 5}),
        ("control_change", {"channel": 2, "control": 69, "value": 0}),
        ("control_change", {"channel": 2, "control": 69, "value": 1}),
    ]
    assert sleeps == [0.5, 0.05, 0.05]
    assert sent[-1] == "closed"


def test_midi_controller_validates_port_and_ids(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "mido",
        SimpleNamespace(get_output_names=lambda: [], Message=lambda *args, **kwargs: None),
    )
    options = SteeringOptions("helix", 0, 0, 0, 0)
    controller = HelixMidiController(options)

    with pytest.raises(ValueError, match="matched 0 ports"):
        controller.__enter__()
    with pytest.raises(RuntimeError, match="not open"):
        controller.activate_preset(1)
    with pytest.raises(ValueError, match="preset"):
        controller.activate_preset(129)
    with pytest.raises(ValueError, match="snapshot"):
        controller.activate_snapshot(9)

    assert controller.__exit__(None, None, None) is None


def test_profile_creates_midi_controller() -> None:
    profile = HelixDeviceProfile()
    options = profile.default_steering_options()

    assert isinstance(profile.create_controller(options), HelixMidiController)
