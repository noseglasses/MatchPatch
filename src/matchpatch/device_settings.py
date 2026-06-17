"""Descriptor-based device setting resolution."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from matchpatch.config import Config, config_value, parse_channel_mapping
from matchpatch.devices.base import (
    AudioRouting,
    DeviceProfile,
    DeviceSettingDescriptor,
    SteeringOptions,
)

DeviceSettings = dict[str, object]

_ARG_ATTRS = {
    "midi_output": "steering_output",
    "midi_channel": "steering_channel",
}


def resolve_device_settings(
    profile: DeviceProfile,
    config: Config,
    args: object,
) -> DeviceSettings:
    """Resolve descriptor defaults, TOML config values, and CLI args."""
    settings: DeviceSettings = {}

    for descriptor in _setting_descriptors(profile):
        value = _arg_value(args, descriptor)
        if value is None and descriptor.config_path:
            value = config_value(config, *descriptor.config_path, default=None)
        if value is None:
            value = descriptor.default
        settings[descriptor.name] = _coerce_setting_value(descriptor, value)

    if hasattr(profile, "validate_settings"):
        profile.validate_settings(settings)
    return settings


def settings_to_audio_routing(
    profile: DeviceProfile,
    settings: Mapping[str, object],
) -> AudioRouting:
    defaults = profile.default_audio_routing()
    return AudioRouting(
        device=cast("str | int | None", settings.get("audio_device", defaults.device)),
        sample_rate=cast("int", settings.get("sample_rate", defaults.sample_rate)),
        input_mapping=cast(
            "tuple[int, int]", settings.get("input_mapping", defaults.input_mapping)
        ),
        output_mapping=cast(
            "tuple[int, int]", settings.get("output_mapping", defaults.output_mapping)
        ),
    )


def settings_to_steering_options(
    profile: DeviceProfile,
    settings: Mapping[str, object],
) -> SteeringOptions:
    defaults = profile.default_steering_options()
    return SteeringOptions(
        output=cast("str | None", settings.get("midi_output", defaults.output)),
        channel=cast("int", settings.get("midi_channel", defaults.channel)),
        preset_wait_seconds=cast(
            "float", settings.get("preset_wait", defaults.preset_wait_seconds)
        ),
        snapshot_wait_seconds=cast(
            "float", settings.get("snapshot_wait", defaults.snapshot_wait_seconds)
        ),
        measurement_wait_seconds=cast(
            "float", settings.get("measurement_wait", defaults.measurement_wait_seconds)
        ),
    )


def setting_diagnostics(settings: Mapping[str, object]) -> dict[str, object]:
    """Return non-sensitive setting values suitable for diagnostics output."""
    diagnostics = dict(settings)
    if "midi_output" in diagnostics:
        diagnostics["steering_output"] = diagnostics["midi_output"]
    if "midi_channel" in diagnostics:
        diagnostics["steering_channel"] = diagnostics["midi_channel"]
    return diagnostics


def _arg_value(args: object, descriptor: DeviceSettingDescriptor) -> object | None:
    attr = _ARG_ATTRS.get(descriptor.name, descriptor.name)
    return getattr(args, attr, None)


def _setting_descriptors(profile: DeviceProfile) -> tuple[DeviceSettingDescriptor, ...]:
    if hasattr(profile, "setting_descriptors"):
        return profile.setting_descriptors()

    audio = _default_audio(profile)
    steering = _default_steering(profile)
    name = getattr(profile, "name", "device")
    audio_path = ("devices", name, "audio")
    steering_path = ("devices", name, "steering")
    return (
        DeviceSettingDescriptor(
            name="audio_device",
            scope="audio",
            kind="string",
            default=getattr(audio, "device", None),
            config_path=(*audio_path, "device"),
        ),
        DeviceSettingDescriptor(
            name="sample_rate",
            scope="audio",
            kind="integer",
            default=getattr(audio, "sample_rate", None),
            config_path=(*audio_path, "sample_rate"),
        ),
        DeviceSettingDescriptor(
            name="input_mapping",
            scope="audio",
            kind="channel_mapping",
            default=getattr(audio, "input_mapping", None),
            config_path=(*audio_path, "input_mapping"),
        ),
        DeviceSettingDescriptor(
            name="output_mapping",
            scope="audio",
            kind="channel_mapping",
            default=getattr(audio, "output_mapping", None),
            config_path=(*audio_path, "output_mapping"),
        ),
        DeviceSettingDescriptor(
            name="blocksize",
            scope="audio",
            kind="integer",
            default=0,
            config_path=(*audio_path, "blocksize"),
        ),
        DeviceSettingDescriptor(
            name="midi_output",
            scope="steering",
            kind="string",
            default=getattr(steering, "output", None),
            config_path=(*steering_path, "output"),
        ),
        DeviceSettingDescriptor(
            name="midi_channel",
            scope="steering",
            kind="integer",
            default=getattr(steering, "channel", None),
            config_path=(*steering_path, "channel"),
        ),
        DeviceSettingDescriptor(
            name="preset_wait",
            scope="steering",
            kind="float",
            default=getattr(steering, "preset_wait_seconds", None),
            config_path=(*steering_path, "preset_wait_seconds"),
        ),
        DeviceSettingDescriptor(
            name="snapshot_wait",
            scope="steering",
            kind="float",
            default=getattr(steering, "snapshot_wait_seconds", None),
            config_path=(*steering_path, "snapshot_wait_seconds"),
        ),
        DeviceSettingDescriptor(
            name="measurement_wait",
            scope="steering",
            kind="float",
            default=getattr(steering, "measurement_wait_seconds", None),
            config_path=(*steering_path, "measurement_wait_seconds"),
        ),
    )


def _default_audio(profile: DeviceProfile) -> object:
    if hasattr(profile, "default_audio_routing"):
        return profile.default_audio_routing()
    return object()


def _default_steering(profile: DeviceProfile) -> object:
    if hasattr(profile, "default_steering_options"):
        return profile.default_steering_options()
    return object()


def _coerce_setting_value(
    descriptor: DeviceSettingDescriptor,
    value: object | None,
) -> object | None:
    if value is None:
        return None
    if descriptor.kind == "channel_mapping":
        return parse_channel_mapping(value)
    if descriptor.kind == "integer" and not isinstance(value, bool):
        return int(cast(Any, value))
    if descriptor.kind == "float" and not isinstance(value, bool):
        return float(cast(Any, value))
    if descriptor.kind == "path" and isinstance(value, Path):
        return value
    if descriptor.kind == "path":
        return str(value)
    return value
