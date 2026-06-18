from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from matchpatch.devices.base import DeviceSettingDescriptor
from matchpatch.devices.registry import get_device_profile
from matchpatch.gui import main_window
from matchpatch.gui.device_panels import create_settings_panel
from matchpatch.gui.main_window import MainWindow
from matchpatch.gui.normalization_workflow import NormalizationWorkflowController
from matchpatch.gui.settings_renderer import DescriptorSettingsPanel


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    QCoreApplication.setOrganizationName("MatchPatchTests")
    QCoreApplication.setApplicationName("MatchPatchTests")
    yield instance


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path):
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings().clear()
    yield
    QSettings().clear()


def test_main_window_lists_descriptor_only_device_with_rendered_panel(
    monkeypatch,
    app,
    tmp_path,
) -> None:
    helix = main_window.get_device_profile("helix")
    descriptors = _standard_fake_descriptors()
    fake = SimpleNamespace(
        name="fake",
        display_name="Fake Device",
        measurement_backends=lambda: ("offline",),
        setting_descriptors=lambda: descriptors,
        default_audio_routing=lambda: SimpleNamespace(
            device="Fake Audio",
            sample_rate=48000,
            input_mapping=(1, 2),
            output_mapping=(3, 4),
        ),
        default_steering_options=lambda: SimpleNamespace(
            output="Fake MIDI",
            channel=1,
            preset_wait_seconds=0.2,
            snapshot_wait_seconds=0.3,
            measurement_wait_seconds=0.4,
        ),
        validate_settings=lambda settings: None,
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[devices.fake.audio]
device = "Configured Fake"
sample_rate = 96000
input_mapping = [5, 6]
output_mapping = [7, 8]

[devices.fake.steering]
output = "Configured MIDI"
channel = 3
preset_wait_seconds = 0.7
snapshot_wait_seconds = 0.8
measurement_wait_seconds = 0.9
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_window, "list_device_profiles", lambda: [helix, fake])
    monkeypatch.setattr(
        main_window,
        "get_device_profile",
        lambda name: fake if name == "fake" else helix,
    )
    monkeypatch.setattr(
        "matchpatch.normalize.get_device_profile",
        lambda name: fake if name == "fake" else helix,
    )

    window = MainWindow()
    window.loading_controller.get_profile = lambda name: fake if name == "fake" else helix
    window.config_path.setText(str(config_path))
    errors: list[str] = []
    window.show_error = errors.append
    fake_index = window.device.findData("fake")
    window.device.setCurrentIndex(fake_index)
    app.processEvents()

    assert errors == []
    panel = window.device_panels["fake"]
    assert isinstance(panel, DescriptorSettingsPanel)
    assert window.device_stack.currentWidget() is panel
    assert panel.controls["audio_device"].text() == "Configured Fake"
    assert panel.controls["sample_rate"].value() == 96000
    assert panel.controls["input_mapping"].text() == "5,6"
    assert panel.controls["midi_output"].text() == "Configured MIDI"
    assert panel.controls["midi_channel"].value() == 3

    argv: list[str] = []
    panel.append_arguments(argv)

    assert ["--audio-device", "Configured Fake"] == argv[
        argv.index("--audio-device") : argv.index("--audio-device") + 2
    ]
    assert ["--input-mapping", "5,6"] == argv[
        argv.index("--input-mapping") : argv.index("--input-mapping") + 2
    ]
    assert ["--steering-output", "Configured MIDI"] == argv[
        argv.index("--steering-output") : argv.index("--steering-output") + 2
    ]

    window.close()


def test_demo_device_uses_descriptor_settings_panel(app) -> None:
    profile = get_device_profile("demo-device")
    panel = create_settings_panel(profile, QWidget())

    assert isinstance(panel, DescriptorSettingsPanel)
    panel.populate(SimpleNamespace())
    assert panel.controls["sample_rate"].value() == 48000
    assert panel.controls["input_mapping"].text() == "1,2"
    assert panel.controls["output_mapping"].text() == "1,2"
    assert panel.controls["demo_mode"].currentText() == "offline"
    assert "preset_wait" not in panel.controls
    assert "snapshot_wait" not in panel.controls
    assert "measurement_wait" not in panel.controls


def test_main_window_lists_demo_device_without_changing_default(app) -> None:
    window = MainWindow()

    assert window.device.currentData() == "helix"
    assert window.device.findData("demo-device") >= 0
    assert "demo-device" in window.device_panels

    window.close()


def test_selecting_demo_device_does_not_show_error_popup(monkeypatch, app) -> None:
    window = MainWindow()
    critical_messages = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: critical_messages.append(args))

    window.device.setCurrentIndex(window.device.findData("demo-device"))
    app.processEvents()

    assert critical_messages == []
    assert window.device.currentData() == "demo-device"

    window.close()


def test_demo_device_ignores_incompatible_opened_setlist_without_popup(
    monkeypatch,
    app,
    tmp_path,
) -> None:
    window = MainWindow()
    critical_messages = []
    input_path = tmp_path / "helix-setlist.hls"
    input_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: critical_messages.append(args))
    window.device.setCurrentIndex(window.device.findData("demo-device"))
    app.processEvents()
    window.input_path.setText(str(input_path))

    window.load_assignments()

    assert critical_messages == []
    assert window.preset_table.rowCount() == 0

    window.close()


def test_demo_device_normalization_shows_clear_unavailable_message(monkeypatch, app) -> None:
    window = SimpleNamespace(
        device=SimpleNamespace(currentData=lambda: "demo-device"),
        worker=None,
    )
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args))

    NormalizationWorkflowController(window).start_normalization()

    assert len(messages) == 1
    assert messages[0][1] == "Normalization unavailable"
    assert "Demo Device" in messages[0][2]
    assert "cannot normalize files" in messages[0][2]
    assert window.worker is None


def test_descriptor_settings_panel_renders_all_descriptor_kinds(app) -> None:
    panel = DescriptorSettingsPanel(
        (
            DeviceSettingDescriptor(
                name="name",
                scope="device",
                kind="string",
                default="Initial",
                cli_flags=("--name",),
            ),
            DeviceSettingDescriptor(
                name="count",
                scope="device",
                kind="integer",
                default=2,
                cli_flags=("--count",),
                minimum=0,
                maximum=10,
            ),
            DeviceSettingDescriptor(
                name="gain",
                scope="processing",
                kind="float",
                default=1.5,
                cli_flags=("--gain",),
                minimum=0.0,
            ),
            DeviceSettingDescriptor(
                name="enabled",
                scope="processing",
                kind="boolean",
                default=False,
                cli_flags=("--enabled",),
            ),
            DeviceSettingDescriptor(
                name="mode",
                scope="processing",
                kind="choice",
                default="fast",
                choices=("fast", "careful"),
                cli_flags=("--mode",),
            ),
            DeviceSettingDescriptor(
                name="cache_path",
                scope="diagnostics",
                kind="path",
                default="/tmp/cache",
                cli_flags=("--cache-path",),
            ),
            DeviceSettingDescriptor(
                name="channels",
                scope="audio",
                kind="channel_mapping",
                default=(1, 2),
                cli_flags=("--channels",),
            ),
        )
    )

    panel.populate(
        SimpleNamespace(
            name="Configured",
            count=4,
            gain=2.25,
            enabled=True,
            mode="careful",
            cache_path="/tmp/configured",
            channels="3,4",
        )
    )

    assert panel.collect_settings() == {
        "name": "Configured",
        "count": 4,
        "gain": 2.25,
        "enabled": True,
        "mode": "careful",
        "cache_path": "/tmp/configured",
        "channels": (3, 4),
    }
    argv: list[str] = []
    panel.append_arguments(argv)
    assert argv == [
        "--name",
        "Configured",
        "--count",
        "4",
        "--gain",
        "2.25",
        "--enabled",
        "--mode",
        "careful",
        "--cache-path",
        "/tmp/configured",
        "--channels",
        "3,4",
    ]


def _standard_fake_descriptors() -> tuple[DeviceSettingDescriptor, ...]:
    return (
        DeviceSettingDescriptor(
            name="audio_device",
            scope="audio",
            kind="string",
            default="Fake Audio",
            config_path=("devices", "fake", "audio", "device"),
            cli_flags=("--audio-device",),
            label="Audio device",
        ),
        DeviceSettingDescriptor(
            name="sample_rate",
            scope="audio",
            kind="integer",
            default=48000,
            config_path=("devices", "fake", "audio", "sample_rate"),
            cli_flags=("--sample-rate",),
            minimum=1,
        ),
        DeviceSettingDescriptor(
            name="input_mapping",
            scope="audio",
            kind="channel_mapping",
            default=(1, 2),
            config_path=("devices", "fake", "audio", "input_mapping"),
            cli_flags=("--input-mapping",),
        ),
        DeviceSettingDescriptor(
            name="output_mapping",
            scope="audio",
            kind="channel_mapping",
            default=(3, 4),
            config_path=("devices", "fake", "audio", "output_mapping"),
            cli_flags=("--output-mapping",),
        ),
        DeviceSettingDescriptor(
            name="blocksize",
            scope="audio",
            kind="integer",
            default=0,
            config_path=("devices", "fake", "audio", "blocksize"),
            cli_flags=("--blocksize",),
            minimum=0,
        ),
        DeviceSettingDescriptor(
            name="midi_output",
            scope="steering",
            kind="string",
            default="Fake MIDI",
            config_path=("devices", "fake", "steering", "output"),
            cli_flags=("--steering-output", "--midi-output"),
        ),
        DeviceSettingDescriptor(
            name="midi_channel",
            scope="steering",
            kind="integer",
            default=1,
            config_path=("devices", "fake", "steering", "channel"),
            cli_flags=("--steering-channel", "--midi-channel"),
            minimum=0,
            maximum=15,
        ),
        DeviceSettingDescriptor(
            name="preset_wait",
            scope="steering",
            kind="float",
            default=0.2,
            config_path=("devices", "fake", "steering", "preset_wait_seconds"),
            cli_flags=("--preset-wait",),
            minimum=0.0,
        ),
        DeviceSettingDescriptor(
            name="snapshot_wait",
            scope="steering",
            kind="float",
            default=0.3,
            config_path=("devices", "fake", "steering", "snapshot_wait_seconds"),
            cli_flags=("--snapshot-wait",),
            minimum=0.0,
        ),
        DeviceSettingDescriptor(
            name="measurement_wait",
            scope="steering",
            kind="float",
            default=0.4,
            config_path=("devices", "fake", "steering", "measurement_wait_seconds"),
            cli_flags=("--measurement-wait",),
            minimum=0.0,
        ),
    )
