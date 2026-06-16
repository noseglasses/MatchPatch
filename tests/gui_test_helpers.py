from __future__ import annotations

import wave
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QMessageBox

from matchpatch.gui import main_window
from matchpatch.gui.advanced_settings import GuiSettingsBinder
from matchpatch.normalize import DEFAULT_REFERENCE_DI, DEFAULT_WINDOWS_PYTHON
from matchpatch.workflow import NormalizationRequest


def request(**kwargs) -> NormalizationRequest:
    values = dict(
        device="helix",
        input_path=Path("input.hls"),
        backend="loopback",
        windows_python=str(DEFAULT_WINDOWS_PYTHON),
        reference_di=DEFAULT_REFERENCE_DI,
        automation=False,
    )
    values.update(kwargs)
    return NormalizationRequest(**values)


def write_silent_wav(path: Path, *, seconds: float, sample_rate: int = 48_000) -> None:
    frames = round(seconds * sample_rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\0\0" * frames * 2)


def mock_single_hlx_handler(
    monkeypatch,
    *,
    name: str = "example",
    snapshot_names: tuple[str, ...] = ("Clean", "Solo"),
    snapshot_output_levels: tuple[tuple[float, ...], ...] = ((0.0,), (-3.5, -4.0)),
    assignments: list[SimpleNamespace] | None = None,
) -> None:
    if assignments is None:
        assignments = [
            SimpleNamespace(
                device_patch="01A",
                name=name,
                snapshot_names=snapshot_names,
                snapshot_output_levels=snapshot_output_levels,
            )
        ]

    class Handler:
        @staticmethod
        def validate_input(path):
            return None

        @staticmethod
        def list_assignments(path):
            return assignments

        @staticmethod
        def metadata(path):
            return {"file_type": "hlx"}

    class Profile:
        @staticmethod
        def create_patch_file_handler(root):
            return Handler()

    monkeypatch.setattr(main_window, "get_device_profile", lambda device: Profile())


class StubGuiSettingsBinder:
    def __init__(self, request: NormalizationRequest) -> None:
        self.request = request

    def normalization_request(self, *, defer_export: bool = False) -> NormalizationRequest:
        return replace(self.request, defer_export=defer_export)

    def with_audio_capture_options(
        self,
        request: NormalizationRequest,
        *,
        record_device_output: bool | None = None,
        playback_toggle_path: Path | None = None,
    ) -> NormalizationRequest:
        return replace(
            request,
            record_device_output=(
                request.record_device_output
                if record_device_output is None
                else record_device_output
            ),
            playback_toggle_path=playback_toggle_path,
        )


def stub_gui_settings(monkeypatch, request: NormalizationRequest) -> StubGuiSettingsBinder:
    binder = StubGuiSettingsBinder(request)
    monkeypatch.setattr(
        GuiSettingsBinder,
        "from_widgets",
        staticmethod(lambda window: binder),
    )
    return binder


class SignalStub:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class FakePreflightWorker:
    instances = []

    def __init__(self, request, parent=None):
        self.request = request
        self.parent = parent
        self.completed = SignalStub()
        self.failed = SignalStub()
        self.finished = SignalStub()
        self.started = False
        FakePreflightWorker.instances.append(self)

    def start(self):
        self.started = True

    def deleteLater(self):
        return None


class FakeSaveChangesMessageBox:
    StandardButton = QMessageBox.StandardButton
    ButtonRole = QMessageBox.ButtonRole
    next_click = QMessageBox.StandardButton.Cancel
    instances = []

    def __init__(self, parent=None):
        self.parent = parent
        self.title = ""
        self.text = ""
        self.buttons = []
        self.default_button = None
        self._clicked_button = None
        FakeSaveChangesMessageBox.instances.append(self)

    def setWindowTitle(self, title):
        self.title = title

    def setText(self, text):
        self.text = text

    def addButton(self, button, role=None):
        button_ref = object()
        self.buttons.append((button, role, button_ref))
        return button_ref

    def setDefaultButton(self, button):
        self.default_button = button

    def exec(self):
        for button, _role, button_ref in self.buttons:
            if button == self.next_click:
                self._clicked_button = button_ref
                break
        return 0

    def clickedButton(self):
        return self._clicked_button
