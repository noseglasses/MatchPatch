from __future__ import annotations

import builtins
import csv
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from hypothesis import given
from hypothesis import strategies as st

from matchpatch.devices import get_device_profile
from matchpatch.devices.base import (
    AudioRouting,
    DeviceProfile,
    PatchFileHandler,
    SteeringOptions,
)
from matchpatch.measure import (
    HardwareBackend,
    LoopbackBackend,
    SimulatedHardwareBackend,
    csv_fields,
    list_devices,
    load_reference_audio,
    main,
    measure,
    measure_presets,
    parse_args,
    parse_channel_mapping,
    parse_int_list,
    resolve_audio_config,
    resolve_steering_options,
)


def test_loopback_backend_writes_compatible_csv(tmp_path) -> None:
    sample_rate = 48000
    times = np.arange(sample_rate * 4) / sample_rate
    reference = np.sin(2 * np.pi * 1000 * times)[:, np.newaxis]
    csv_path = tmp_path / "lufs_analysis.csv"

    measure_presets(
        get_device_profile("helix"),
        [1, 6],
        csv_path,
        reference,
        sample_rate,
        LoopbackBackend(),
    )

    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert [row["DevicePatch"] for row in rows] == ["01A", "02B"]
    assert rows[0]["LUFS1"] == rows[0]["LUFS4"]
    assert rows[0]["CrestFactor1"] == rows[0]["CrestFactor4"]


def test_measure_presets_emits_structured_progress(tmp_path) -> None:
    sample_rate = 48000
    times = np.arange(sample_rate * 4) / sample_rate
    reference = np.sin(2 * np.pi * 1000 * times)[:, np.newaxis]
    events = []

    measure_presets(
        get_device_profile("helix"),
        [1],
        tmp_path / "events.csv",
        reference,
        sample_rate,
        LoopbackBackend(),
        snapshot_count=2,
        on_progress=events.append,
        log_output=False,
    )

    assert [event.kind for event in events] == [
        "preset_started",
        "snapshot_started",
        "snapshot_completed",
        "snapshot_started",
        "snapshot_completed",
        "measurement_completed",
    ]
    assert events[0].device_patch == "01A"
    assert events[2].snapshot == 1
    assert events[2].lufs is not None


class FakePatchFileHandler(PatchFileHandler):
    def validate_input(self, input_path: Path) -> None:
        return None

    def validate_output(self, input_path: Path, output_path: Path) -> None:
        return None

    def list_assignments(self, input_path: Path) -> list:
        return []

    def parse_patch_set(self, value: str) -> list[int]:
        return []

    def select_preset_ids(
        self, input_path: Path, assignments: list, requested_ids: list[int] | None
    ) -> list[int]:
        return []

    def format_patch_id(self, preset_id: int) -> str:
        return f"patch-{preset_id}"

    def create_reamp_file(self, input_path: Path, output_path: Path) -> None:
        return None

    def apply_analysis_csv(
        self,
        input_path: Path,
        output_path: Path,
        csv_path: Path,
        ignore_bad_lufs: bool,
        target_lufs: float,
    ) -> None:
        return None

    def automation_output_path(self, input_path: Path, postfix: str) -> Path:
        return input_path


class FakeDeviceProfile(DeviceProfile):
    name = "fake"
    display_name = "Fake Processor"

    def create_patch_file_handler(self, project_dir: Path) -> PatchFileHandler:
        return FakePatchFileHandler()

    def default_audio_routing(self) -> AudioRouting:
        raise AssertionError("Loopback must not resolve USB routing")

    def default_steering_options(self) -> SteeringOptions:
        raise AssertionError("Loopback must not resolve steering")

    def create_controller(self, options: SteeringOptions):
        raise AssertionError("Loopback must not create a controller")


def test_loopback_is_device_independent(tmp_path) -> None:
    sample_rate = 48000
    times = np.arange(sample_rate * 4) / sample_rate
    reference = np.sin(2 * np.pi * 1000 * times)[:, np.newaxis]
    csv_path = tmp_path / "generic.csv"

    measure_presets(
        FakeDeviceProfile(),
        [7],
        csv_path,
        reference,
        sample_rate,
        LoopbackBackend(),
    )

    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        row = next(csv.DictReader(csv_file))

    assert row["DevicePatch"] == "patch-7"
    assert "HelixPreset" not in row


def test_simulated_backend_tracks_state_and_modifies_audio() -> None:
    routing = AudioRouting("processor", 48000, (1, 2), (3, 4))
    backend = SimulatedHardwareBackend(routing, snapshot_count=4)
    reference = np.array([[0.1, -0.2], [0.3, -0.4]])

    backend.activate_preset(1)
    backend.reapply_snapshot(1)
    first = backend.record(reference)
    backend.reapply_snapshot(2)
    second = backend.record(reference)

    assert backend.steering_events == [
        ("preset", 1),
        ("snapshot", 2),
        ("snapshot", 1),
        ("snapshot", 1),
        ("snapshot", 2),
    ]
    assert first == pytest.approx(reference * 10.0 ** (-4.0 / 20.0))
    assert second == pytest.approx(np.tanh(reference * 10.0 ** (-3.0 / 20.0) * 2.0) / 2.0)


@pytest.mark.parametrize(
    ("input_mapping", "output_mapping", "message"),
    [
        ((7, 8), None, "input mapping"),
        (None, (7, 8), "output mapping"),
    ],
)
def test_simulated_backend_validates_routing(input_mapping, output_mapping, message) -> None:
    routing = AudioRouting("processor", 48000, (1, 2), (3, 4))

    with pytest.raises(ValueError, match=message):
        SimulatedHardwareBackend(routing, 4, input_mapping, output_mapping)


def test_simulated_backend_validates_state_and_injected_failures() -> None:
    backend = SimulatedHardwareBackend(
        AudioRouting("processor", 48000, (1, 2), (3, 4)),
        snapshot_count=1,
        failing_preset_ids=frozenset({6}),
    )
    reference = np.ones((2, 2))

    with pytest.raises(RuntimeError, match="must be active"):
        backend.record(reference)
    with pytest.raises(RuntimeError, match="preset is not active"):
        backend.reapply_snapshot(1)
    with pytest.raises(ValueError, match="preset ID"):
        backend.activate_preset(0)
    with pytest.raises(RuntimeError, match="failure"):
        backend.activate_preset(6)

    backend.activate_preset(1)
    with pytest.raises(RuntimeError, match="must be active"):
        backend.record(reference)
    with pytest.raises(ValueError, match="snapshot"):
        backend.reapply_snapshot(0)
    with pytest.raises(ValueError, match="snapshot"):
        backend.reapply_snapshot(2)

    backend.reapply_snapshot(1)
    assert backend.steering_events == [("preset", 1), ("snapshot", 1), ("snapshot", 1)]


def test_parse_worker_lists_and_channels() -> None:
    assert parse_int_list("1, 2,,3") == [1, 2, 3]
    assert parse_channel_mapping("3,4") == (3, 4)
    assert csv_fields(2) == [
        "Preset",
        "DevicePatch",
        "LUFS1",
        "LUFS2",
        "CrestFactor1",
        "CrestFactor2",
    ]

    for invalid in ("1", "0,2", "1,2,3"):
        with pytest.raises(Exception, match="two positive"):
            parse_channel_mapping(invalid)


@given(
    first=st.integers(min_value=1, max_value=128),
    second=st.integers(min_value=1, max_value=128),
)
def test_channel_mapping_round_trips_positive_channel_ids(first: int, second: int) -> None:
    assert parse_channel_mapping(f" {first}, {second} ") == (first, second)


@given(
    first=st.integers(min_value=-128, max_value=0),
    second=st.integers(min_value=-128, max_value=0),
)
def test_channel_mapping_rejects_non_positive_channel_ids(first: int, second: int) -> None:
    with pytest.raises(Exception, match="two positive"):
        parse_channel_mapping(f"{first},{second}")


def test_load_reference_audio_repeats_mono_and_trims_extra_channels(tmp_path) -> None:
    mono_path = tmp_path / "mono.wav"
    stereo_path = tmp_path / "stereo.wav"
    wide_path = tmp_path / "wide.wav"
    sf.write(mono_path, np.ones((20, 1)), 48000)
    sf.write(stereo_path, np.ones((20, 2)), 48000)
    sf.write(wide_path, np.ones((20, 3)), 48000)

    assert load_reference_audio(mono_path, 48000).shape == (20, 2)
    assert load_reference_audio(stereo_path, 48000).shape == (20, 2)
    assert load_reference_audio(wide_path, 48000).shape == (20, 2)

    with pytest.raises(ValueError, match="sample rate"):
        load_reference_audio(mono_path, 44100)


class FailingBackend(LoopbackBackend):
    def activate_preset(self, preset_id: int) -> None:
        raise RuntimeError("processor unavailable")


def test_measure_presets_writes_error_row_when_backend_fails(tmp_path) -> None:
    csv_path = tmp_path / "errors.csv"

    measure_presets(
        get_device_profile("helix"),
        [1],
        csv_path,
        np.ones((400, 2)),
        100,
        FailingBackend(),
    )

    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        row = next(csv.DictReader(csv_file))

    assert row["DevicePatch"] == "01A"
    assert row["LUFS1"] == "ERROR"
    assert row["CrestFactor4"] == "ERROR"


def test_hardware_backend_delegates_and_waits(monkeypatch) -> None:
    events = []
    controller = SimpleNamespace(
        activate_preset=lambda preset: events.append(("preset", preset)),
        reapply_snapshot=lambda snapshot: events.append(("snapshot", snapshot)),
    )
    audio = SimpleNamespace(
        record_processed_audio=lambda reference, config: (
            events.append(("record", reference, config)) or reference
        )
    )
    monkeypatch.setitem(sys.modules, "matchpatch.audio", audio)
    monkeypatch.setattr(
        "matchpatch.measure.time.sleep", lambda delay: events.append(("sleep", delay))
    )
    backend = HardwareBackend("config", controller, 0.25)
    reference = np.ones((4, 2))

    backend.activate_preset(6)
    backend.reapply_snapshot(2)
    assert backend.record(reference) is reference
    assert events == [
        ("preset", 6),
        ("snapshot", 2),
        ("sleep", 0.25),
        ("record", reference, "config"),
    ]


def test_resolve_steering_options_uses_defaults_and_overrides() -> None:
    args = SimpleNamespace(
        steering_output=None,
        steering_channel=4,
        preset_wait=None,
        snapshot_wait=0.2,
        measurement_wait=None,
    )

    options = resolve_steering_options(args, get_device_profile("helix"))

    assert options.output == "Helix"
    assert options.channel == 4
    assert options.preset_wait_seconds == 0.5
    assert options.snapshot_wait_seconds == 0.2


def test_resolve_audio_config_uses_defaults_and_overrides(monkeypatch) -> None:
    class AudioConfig:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    monkeypatch.setitem(sys.modules, "matchpatch.audio", SimpleNamespace(AudioConfig=AudioConfig))
    args = SimpleNamespace(
        audio_device=None,
        sample_rate=44100,
        input_mapping=None,
        output_mapping=(7, 8),
        blocksize=128,
    )

    config = resolve_audio_config(args, get_device_profile("helix"))

    assert config.device == "Helix"
    assert config.sample_rate == 44100
    assert config.input_mapping == (1, 2)
    assert config.output_mapping == (7, 8)
    assert config.blocksize == 128
    assert config.pre_roll_seconds == 1.0
    assert config.post_roll_seconds == 1.0
    assert config.round_trip_latency_seconds == 0.02


def worker_args(**overrides):
    values = {
        "device": "helix",
        "backend": "loopback",
        "preset_ids": [1],
        "csv": "results.csv",
        "reference_di": "reference.wav",
        "audio_device": None,
        "steering_output": None,
        "steering_channel": None,
        "sample_rate": None,
        "input_mapping": None,
        "output_mapping": None,
        "blocksize": 0,
        "preset_wait": None,
        "snapshot_wait": None,
        "measurement_wait": None,
        "pre_roll": 1.0,
        "post_roll": 1.0,
        "round_trip_latency": 0.02,
        "simulate_fail_presets": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_measure_dispatches_loopback_without_audio_module(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("matchpatch.measure.load_reference_audio", lambda path, rate: "reference")
    monkeypatch.setattr(
        "matchpatch.measure.measure_presets", lambda *args, **kwargs: calls.append(args)
    )

    measure(worker_args())

    assert isinstance(calls[0][-1], LoopbackBackend)
    assert calls[0][4] == 48000


def test_measure_dispatches_stateful_simulator_without_audio_module(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("matchpatch.measure.load_reference_audio", lambda path, rate: "reference")
    monkeypatch.setattr(
        "matchpatch.measure.measure_presets", lambda *args, **kwargs: calls.append(args)
    )

    measure(
        worker_args(
            backend="simulated",
            input_mapping=(1, 2),
            output_mapping=(3, 4),
            simulate_fail_presets=[6],
        )
    )

    backend = calls[0][-1]
    assert isinstance(backend, SimulatedHardwareBackend)
    assert backend.failing_preset_ids == frozenset({6})


def test_measure_configures_hardware_backend(monkeypatch) -> None:
    calls = []
    controller = SimpleNamespace(__enter__=lambda self: self, __exit__=lambda *args: None)

    class ContextController:
        def __enter__(self):
            return controller

        def __exit__(self, *args):
            return None

    profile = get_device_profile("helix")
    monkeypatch.setattr("matchpatch.measure.get_device_profile", lambda device: profile)
    monkeypatch.setattr("matchpatch.measure.load_reference_audio", lambda path, rate: "reference")
    monkeypatch.setattr(
        "matchpatch.measure.measure_presets", lambda *args, **kwargs: calls.append(args)
    )
    monkeypatch.setattr(profile, "create_controller", lambda options: ContextController())
    monkeypatch.setitem(
        sys.modules,
        "matchpatch.audio",
        SimpleNamespace(
            AudioConfig=lambda **kwargs: SimpleNamespace(**kwargs),
            resolve_audio_device=lambda device: calls.append(("resolved", device)),
        ),
    )

    measure(worker_args(backend="hardware", audio_device="processor", sample_rate=44100))

    assert calls[0] == ("resolved", "processor")
    assert isinstance(calls[1][-1], HardwareBackend)


def fake_sounddevice():
    apis = [{"name": "ASIO"}]
    devices = [
        {
            "name": "Processor",
            "hostapi": 0,
            "max_input_channels": 2,
            "max_output_channels": 4,
        }
    ]
    return SimpleNamespace(
        query_hostapis=lambda index=None: apis if index is None else apis[index],
        query_devices=lambda: devices,
    )


def test_list_devices_prints_audio_and_midi(monkeypatch, capsys) -> None:
    monkeypatch.setitem(sys.modules, "matchpatch.audio", SimpleNamespace(sd=fake_sounddevice()))
    monkeypatch.setitem(
        sys.modules, "mido", SimpleNamespace(get_output_names=lambda: ["Processor MIDI"])
    )

    list_devices()

    output = capsys.readouterr().out
    assert "helix: Line 6 Helix" in output
    assert "[0] Processor | ASIO | in=2 out=4" in output
    assert "Processor MIDI" in output


def test_list_devices_reports_missing_mido(monkeypatch, capsys) -> None:
    original_import = builtins.__import__

    def fail_mido(name, *args, **kwargs):
        if name == "mido":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setitem(sys.modules, "matchpatch.audio", SimpleNamespace(sd=fake_sounddevice()))
    monkeypatch.delitem(sys.modules, "mido", raising=False)
    monkeypatch.setattr(builtins, "__import__", fail_mido)

    list_devices()

    assert "unavailable: mido is not installed" in capsys.readouterr().out


def test_worker_parse_args_supports_hardware_aliases(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure",
            "measure",
            "--device",
            "helix",
            "--preset-ids",
            "1,6",
            "--csv",
            "results.csv",
            "--reference-di",
            "reference.wav",
            "--midi-output",
            "port",
            "--input-mapping",
            "1,2",
            "--simulate-fail-presets",
            "6,7",
        ],
    )

    args = parse_args()

    assert args.preset_ids == [1, 6]
    assert args.steering_output == "port"
    assert args.input_mapping == (1, 2)
    assert args.simulate_fail_presets == [6, 7]


def test_worker_parse_args_reads_toml_defaults(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[normalize]
backend = "loopback"

[devices.helix.audio]
input_mapping = [3, 4]
blocksize = 64

[policy]
measured_snapshots = 2

[analysis]
window_seconds = 1.5
pre_roll_seconds = 1.5
post_roll_seconds = 2.0
round_trip_latency_seconds = 0.03
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure",
            "measure",
            "--config",
            str(config_path),
            "--device",
            "helix",
            "--preset-ids",
            "1",
            "--csv",
            "results.csv",
            "--reference-di",
            "reference.wav",
        ],
    )

    args = parse_args()

    assert args.backend == "loopback"
    assert args.input_mapping == (3, 4)
    assert args.blocksize == 64
    assert args.snapshot_count == 2
    assert args.analysis_options.window_seconds == 1.5
    assert args.pre_roll == 1.5
    assert args.post_roll == 2.0
    assert args.round_trip_latency == 0.03


def test_worker_parse_args_rejects_invalid_snapshot_count(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure",
            "measure",
            "--device",
            "helix",
            "--preset-ids",
            "1",
            "--csv",
            "results.csv",
            "--reference-di",
            "reference.wav",
            "--snapshot-count",
            "0",
        ],
    )

    with pytest.raises(ValueError, match="at least 1"):
        parse_args()


def test_worker_main_dispatches_devices_and_legacy_helix_backend(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("matchpatch.measure.list_devices", lambda: calls.append("devices"))
    monkeypatch.setattr("matchpatch.measure.measure", lambda args: calls.append(args.backend))
    monkeypatch.setattr("matchpatch.measure.parse_args", lambda: SimpleNamespace(command="devices"))
    main()
    monkeypatch.setattr(
        "matchpatch.measure.parse_args",
        lambda: SimpleNamespace(command="measure", backend="helix"),
    )
    main()
    monkeypatch.setattr(
        "matchpatch.measure.parse_args",
        lambda: SimpleNamespace(command="measure", backend="loopback"),
    )
    main()
    monkeypatch.setattr(
        "matchpatch.measure.parse_args",
        lambda: SimpleNamespace(command="measure", backend="simulated"),
    )
    main()

    assert calls == ["devices", "hardware", "loopback", "simulated"]
