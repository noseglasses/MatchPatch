"""Declarative device settings renderer for descriptor-only profiles."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from matchpatch.config import parse_channel_mapping
from matchpatch.devices.base import DeviceSettingDescriptor

_ARG_ATTRS = {
    "midi_output": "steering_output",
    "midi_channel": "steering_channel",
}

_SCOPE_TITLES = {
    "audio": "Audio routing",
    "steering": "MIDI steering",
    "processing": "Processing",
    "diagnostics": "Diagnostics",
    "device": "Device",
}


class DescriptorSettingsPanel(QWidget):
    """Settings panel rendered from ``DeviceSettingDescriptor`` metadata."""

    def __init__(self, descriptors: tuple[DeviceSettingDescriptor, ...]) -> None:
        super().__init__()
        self.descriptors = descriptors
        self.controls: dict[str, QWidget] = {}

        layout = QVBoxLayout(self)
        grouped = _group_descriptors(descriptors)
        for scope, scope_descriptors in grouped:
            group = QGroupBox(_SCOPE_TITLES.get(scope, scope.title()))
            form = QFormLayout(group)
            for descriptor in scope_descriptors:
                control = _create_control(descriptor)
                control.setObjectName(descriptor.name)
                self.controls[descriptor.name] = control
                form.addRow(_label(descriptor), control)
            layout.addWidget(group)
        layout.addStretch()

    def populate(self, args: object) -> None:
        for descriptor in self.descriptors:
            value = _argument_value(args, descriptor)
            if value is None:
                value = descriptor.default
            _set_control_value(self.controls[descriptor.name], descriptor, value)

    def append_arguments(self, argv: list[str]) -> None:
        for descriptor in self.descriptors:
            if not descriptor.cli_flags:
                continue
            flag = descriptor.cli_flags[0]
            value = _control_argument_value(self.controls[descriptor.name], descriptor)
            if descriptor.kind == "boolean":
                if value:
                    argv.append(flag)
                continue
            if str(value).strip():
                argv.extend([flag, str(value)])

    def collect_settings(self) -> dict[str, object]:
        return {
            descriptor.name: _collect_control_value(self.controls[descriptor.name], descriptor)
            for descriptor in self.descriptors
        }


def _group_descriptors(
    descriptors: tuple[DeviceSettingDescriptor, ...],
) -> list[tuple[str, list[DeviceSettingDescriptor]]]:
    groups: dict[str, list[DeviceSettingDescriptor]] = {}
    order: list[str] = []
    for descriptor in descriptors:
        if descriptor.scope not in groups:
            groups[descriptor.scope] = []
            order.append(descriptor.scope)
        groups[descriptor.scope].append(descriptor)
    return [(scope, groups[scope]) for scope in order]


def _create_control(descriptor: DeviceSettingDescriptor) -> QWidget:
    builders: dict[str, Callable[[DeviceSettingDescriptor], QWidget]] = {
        "integer": _integer_control,
        "float": _float_control,
        "boolean": _boolean_control,
        "choice": _choice_control,
    }
    return builders.get(descriptor.kind, _line_control)(descriptor)


def _line_control(descriptor: DeviceSettingDescriptor) -> QLineEdit:
    control = QLineEdit()
    if descriptor.kind == "float":
        control.setValidator(QDoubleValidator(control))
    return control


def _integer_control(descriptor: DeviceSettingDescriptor) -> QSpinBox:
    control = QSpinBox()
    minimum = int(descriptor.minimum) if descriptor.minimum is not None else -(2**31)
    maximum = int(descriptor.maximum) if descriptor.maximum is not None else 2**31 - 1
    control.setRange(minimum, maximum)
    return control


def _float_control(descriptor: DeviceSettingDescriptor) -> QDoubleSpinBox:
    control = QDoubleSpinBox()
    minimum = float(descriptor.minimum) if descriptor.minimum is not None else -1_000_000_000.0
    maximum = float(descriptor.maximum) if descriptor.maximum is not None else 1_000_000_000.0
    control.setRange(minimum, maximum)
    control.setDecimals(6)
    control.setSingleStep(0.1)
    return control


def _boolean_control(descriptor: DeviceSettingDescriptor) -> QCheckBox:
    control = QCheckBox()
    control.setText(descriptor.label or descriptor.name.replace("_", " ").title())
    return control


def _choice_control(descriptor: DeviceSettingDescriptor) -> QComboBox:
    control = QComboBox()
    control.addItems(list(descriptor.choices))
    return control


def _label(descriptor: DeviceSettingDescriptor) -> QLabel:
    label = QLabel(descriptor.label or descriptor.name.replace("_", " ").title())
    if descriptor.help:
        label.setToolTip(descriptor.help)
    return label


def _argument_value(args: object, descriptor: DeviceSettingDescriptor) -> object | None:
    for attr in _argument_attrs(descriptor):
        value = getattr(args, attr, None)
        if value is not None:
            return value
    return None


def _argument_attrs(descriptor: DeviceSettingDescriptor) -> tuple[str, ...]:
    attrs = [_ARG_ATTRS.get(descriptor.name, descriptor.name)]
    attrs.extend(flag.removeprefix("--").replace("-", "_") for flag in descriptor.cli_flags)
    return tuple(dict.fromkeys(attrs))


def _set_control_value(
    control: QWidget,
    descriptor: DeviceSettingDescriptor,
    value: object | None,
) -> None:
    if isinstance(control, QLineEdit):
        control.setText(_text(_format_value(descriptor, value)))
    elif isinstance(control, QSpinBox):
        control.setValue(_int_value(value, descriptor.default))
    elif isinstance(control, QDoubleSpinBox):
        control.setValue(_float_value(value, descriptor.default))
    elif isinstance(control, QCheckBox):
        control.setChecked(bool(value))
    elif isinstance(control, QComboBox):
        text = _text(value)
        index = control.findText(text)
        if index >= 0:
            control.setCurrentIndex(index)


def _control_argument_value(control: QWidget, descriptor: DeviceSettingDescriptor) -> object:
    if isinstance(control, QLineEdit):
        return control.text()
    value = _collect_control_value(control, descriptor)
    if descriptor.kind == "channel_mapping" and isinstance(value, tuple):
        return ",".join(str(channel) for channel in value)
    return value


def _collect_control_value(control: QWidget, descriptor: DeviceSettingDescriptor) -> object:
    if isinstance(control, QLineEdit):
        text = control.text()
        if descriptor.kind == "channel_mapping":
            return parse_channel_mapping(text)
        if descriptor.kind == "float":
            return float(text)
        return text
    if isinstance(control, QSpinBox):
        return control.value()
    if isinstance(control, QDoubleSpinBox):
        return control.value()
    if isinstance(control, QCheckBox):
        return control.isChecked()
    if isinstance(control, QComboBox):
        return control.currentText()
    raise TypeError(f"Unsupported control for descriptor {descriptor.name}")


def _format_value(descriptor: DeviceSettingDescriptor, value: object | None) -> object | None:
    if descriptor.kind == "channel_mapping" and isinstance(value, list | tuple):
        return ",".join(str(channel) for channel in value)
    return value


def _int_value(value: object | None, default: object | None) -> int:
    candidate = value if value is not None else default
    if isinstance(candidate, bool) or candidate is None:
        return 0
    if isinstance(candidate, int | float | str):
        return int(candidate)
    return 0


def _float_value(value: object | None, default: object | None) -> float:
    candidate = value if value is not None else default
    if isinstance(candidate, bool) or candidate is None:
        return 0.0
    if isinstance(candidate, int | float | str):
        return float(candidate)
    return 0.0


def _text(value: object | None) -> str:
    return "" if value is None else str(value)
