"""Device-specific settings panels for the MatchPatch GUI."""

from __future__ import annotations

import argparse

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class HelixSettingsPanel(QWidget):
    def __init__(self, backend_selector: QWidget | None = None) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.audio_group = QGroupBox("Audio routing")
        self.steering_group = QGroupBox("MIDI steering")
        layout.addWidget(self.audio_group)
        layout.addWidget(self.steering_group)
        if backend_selector is not None:
            backend = QFormLayout()
            backend.addRow(
                _label(
                    "Backend", "Select loopback for testing or hardware for a connected device."
                ),
                backend_selector,
            )
            layout.addLayout(backend)
        layout.addStretch()

        audio = QFormLayout(self.audio_group)
        self.audio_device = QLineEdit()
        self.sample_rate = QSpinBox()
        self.sample_rate.setRange(1, 384000)
        self.input_mapping = QLineEdit()
        self.output_mapping = QLineEdit()
        self.blocksize = QSpinBox()
        self.blocksize.setRange(0, 65536)
        audio.addRow(
            _label("Audio device", "Windows audio-interface name used for Helix I/O."),
            self.audio_device,
        )
        audio.addRow(
            _label(
                "Sample rate",
                "Audio sample rate used while replaying and recording the reference DI.",
            ),
            self.sample_rate,
        )
        audio.addRow(
            _label(
                "Recording channels", "Input channels carrying the Helix-processed stereo signal."
            ),
            self.input_mapping,
        )
        audio.addRow(
            _label("Playback channels", "Output channels sending the reference DI to the Helix."),
            self.output_mapping,
        )
        audio.addRow(
            _label("Block size", "Audio buffer size. Use 0 to let the audio backend decide."),
            self.blocksize,
        )

        steering = QFormLayout(self.steering_group)
        self.steering_output = QLineEdit()
        self.steering_channel = QSpinBox()
        self.steering_channel.setRange(0, 15)
        self.preset_wait = QLineEdit()
        self.snapshot_wait = QLineEdit()
        self.measurement_wait = QLineEdit()
        steering.addRow(
            _label("MIDI output", "MIDI port substring used to find the connected Helix."),
            self.steering_output,
        )
        steering.addRow(
            _label("MIDI channel", "Zero-based MIDI channel used for preset and snapshot changes."),
            self.steering_channel,
        )
        steering.addRow(
            _label("Preset wait (s)", "Pause after switching presets before continuing."),
            self.preset_wait,
        )
        steering.addRow(
            _label("Snapshot wait (s)", "Pause after switching snapshots before continuing."),
            self.snapshot_wait,
        )
        steering.addRow(
            _label(
                "Measurement wait (s)", "Pause before capturing loudness after a snapshot change."
            ),
            self.measurement_wait,
        )

    def populate(self, args: argparse.Namespace) -> None:
        self.audio_device.setText(_text(args.audio_device or "Helix"))
        self.sample_rate.setValue(args.sample_rate or 48000)
        self.input_mapping.setText(args.input_mapping or "1,2")
        self.output_mapping.setText(args.output_mapping or "3,4")
        self.blocksize.setValue(args.blocksize or 0)
        self.steering_output.setText(_text(args.steering_output or "Helix"))
        self.steering_channel.setValue(args.steering_channel or 0)
        self.preset_wait.setText(_text(args.preset_wait if args.preset_wait is not None else 0.5))
        self.snapshot_wait.setText(
            _text(args.snapshot_wait if args.snapshot_wait is not None else 0.2)
        )
        self.measurement_wait.setText(
            _text(args.measurement_wait if args.measurement_wait is not None else 0.1)
        )

    def append_arguments(self, argv: list[str]) -> None:
        _append(argv, "--audio-device", self.audio_device.text())
        _append(argv, "--sample-rate", self.sample_rate.value())
        _append(argv, "--input-mapping", self.input_mapping.text())
        _append(argv, "--output-mapping", self.output_mapping.text())
        _append(argv, "--blocksize", self.blocksize.value())
        _append(argv, "--steering-output", self.steering_output.text())
        _append(argv, "--steering-channel", self.steering_channel.value())
        _append(argv, "--preset-wait", self.preset_wait.text())
        _append(argv, "--snapshot-wait", self.snapshot_wait.text())
        _append(argv, "--measurement-wait", self.measurement_wait.text())


def _append(argv: list[str], name: str, value: object) -> None:
    if str(value).strip():
        argv.extend([name, str(value)])


def _text(value: object | None) -> str:
    return "" if value is None else str(value)


def _label(text: str, tooltip: str) -> QLabel:
    label = QLabel(text)
    label.setToolTip(tooltip)
    return label
