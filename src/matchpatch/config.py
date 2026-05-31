"""TOML configuration helpers shared by MatchPatch entry points."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

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
