"""TOML configuration helpers shared by MatchPatch entry points."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from matchpatch.devices import list_device_profiles
from matchpatch.devices.base import NormalizationPolicy

Config = dict[str, Any]


def default_config_path() -> Path:
    return Path.home() / ".config" / "matchpatch" / "config.toml"


def load_config(path: str | Path | None) -> Config:
    config_path = Path(path).expanduser() if path is not None else default_config_path()

    if not config_path.is_file():
        if path is None:
            return {}

        raise ValueError(f"MatchPatch config file does not exist: {config_path}")

    with config_path.open("rb") as config_file:
        return tomllib.load(config_file)


def config_value(config: Config, *keys: str, default: Any = None) -> Any:  # noqa: ANN401
    value: Any = config

    for key in keys:
        if not isinstance(value, dict):
            return default

        value = value.get(key, default)

    return value


def prefer(cli_value: object, config: Config, *keys: str, default: object = None) -> object:
    if cli_value is not None:
        return cli_value

    return config_value(config, *keys, default=default)


def parse_channel_mapping(value: object) -> tuple[int, int]:
    if isinstance(value, str):
        channels = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    elif isinstance(value, (list, tuple)):
        channels = tuple(value)
    else:
        raise ValueError("Channel mapping must contain two positive IDs")

    if len(channels) != 2 or any(
        not isinstance(channel, int) or channel < 1 for channel in channels
    ):
        raise ValueError("Channel mapping must contain two positive IDs")

    first, second = channels
    assert isinstance(first, int) and isinstance(second, int)
    return first, second


def default_config() -> Config:
    from matchpatch.normalize import DEFAULT_REFERENCE_DI, DEFAULT_WINDOWS_PYTHON

    policy = NormalizationPolicy()
    config: Config = {
        "normalize": {
            "backend": "hardware",
            "windows_python": str(DEFAULT_WINDOWS_PYTHON),
            "reference_di": str(DEFAULT_REFERENCE_DI),
            "target_lufs": -16.0,
        },
        "analysis": {
            "window_seconds": 3.0,
            "interval_seconds": 0.1,
            "minimum_valid_lufs": -100.0,
            "pre_roll_seconds": 0.2,
            "post_roll_seconds": 0.1,
            "round_trip_latency_seconds": 0.02,
        },
        "policy": {
            "measured_snapshots": policy.snapshot_count,
            "solo_regex": policy.solo_regex,
            "solo_gain_bump_db": policy.solo_gain_bump_db,
            "crest_factor_reference_db": policy.crest_factor_reference_db,
            "crest_factor_correction_ratio": policy.crest_factor_correction_ratio,
            "max_crest_factor_correction_db": policy.max_crest_factor_correction_db,
            "gain_deadband_db": policy.gain_deadband_db,
        },
        "devices": {},
    }

    devices = config["devices"]
    assert isinstance(devices, dict)
    for profile in list_device_profiles():
        audio = profile.default_audio_routing()
        steering = profile.default_steering_options()
        devices[profile.name] = {
            "audio": {
                "device": audio.device,
                "sample_rate": audio.sample_rate,
                "input_mapping": list(audio.input_mapping),
                "output_mapping": list(audio.output_mapping),
                "blocksize": 0,
            },
            "steering": {
                "output": steering.output,
                "channel": steering.channel,
                "preset_wait_seconds": steering.preset_wait_seconds,
                "snapshot_wait_seconds": steering.snapshot_wait_seconds,
                "measurement_wait_seconds": steering.measurement_wait_seconds,
            },
        }

    return config


def export_default_config(path: str | Path) -> Path:
    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_toml_document(default_config()), encoding="utf-8")
    return config_path


def _toml_document(config: Config) -> str:
    lines: list[str] = []

    for key, value in config.items():
        if not isinstance(value, dict):
            continue
        _append_toml_table(lines, (key,), value)

    return "\n".join(lines).rstrip() + "\n"


def _append_toml_table(lines: list[str], path: tuple[str, ...], table: dict[str, Any]) -> None:
    scalar_items = [
        (key, value)
        for key, value in table.items()
        if value is not None and not isinstance(value, dict)
    ]
    nested_items = [(key, value) for key, value in table.items() if isinstance(value, dict)]

    if scalar_items:
        if lines:
            lines.append("")
        lines.append(f"[{'.'.join(path)}]")
        for key, value in scalar_items:
            lines.append(f"{key} = {_toml_value(value)}")

    for key, value in nested_items:
        _append_toml_table(lines, (*path, key), value)


def _toml_value(value: object) -> str:
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise TypeError(f"Unsupported default config value: {value!r}")
