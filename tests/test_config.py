from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from matchpatch import config


def test_load_config_reads_toml_and_uses_nested_values(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[normalize]\nbackend = "loopback"\n', encoding="utf-8")
    loaded = config.load_config(path)

    assert config.config_value(loaded, "normalize", "backend") == "loopback"
    assert config.config_value(loaded, "normalize", "missing", default="fallback") == "fallback"
    assert config.config_value(loaded, "normalize", "backend", "nested", default=None) is None
    assert config.prefer("cli", loaded, "normalize", "backend") == "cli"
    assert config.prefer(None, loaded, "normalize", "backend") == "loopback"


def test_load_config_handles_default_and_missing_explicit_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert config.default_config_path() == tmp_path / ".config" / "matchpatch" / "config.toml"
    assert config.load_config(None) == {}

    with pytest.raises(ValueError, match="does not exist"):
        config.load_config(tmp_path / "missing.toml")


def test_export_default_config_writes_loadable_toml(tmp_path) -> None:
    path = config.export_default_config(tmp_path / "defaults.toml")

    loaded = tomllib.loads(path.read_text(encoding="utf-8"))

    assert loaded["normalize"]["backend"] == "hardware"
    assert loaded["normalize"]["target_lufs"] == -16.0
    assert loaded["analysis"]["window_seconds"] == 3.0
    assert loaded["analysis"]["round_trip_latency_seconds"] == 0.02
    assert loaded["policy"]["measured_snapshots"] == 4
    assert loaded["policy"]["solo_regex"] == r"(?i)\bsolo\b"
    assert loaded["devices"]["helix"]["audio"]["device"] == "Helix"
    assert loaded["devices"]["helix"]["audio"]["input_mapping"] == [1, 2]
    assert loaded["devices"]["helix"]["steering"]["snapshot_wait_seconds"] == 0.2


@pytest.mark.parametrize("value", ["1, 2", [3, 4], (5, 6)])
def test_parse_channel_mapping_accepts_supported_shapes(value) -> None:
    assert config.parse_channel_mapping(value)[1] % 2 == 0


@pytest.mark.parametrize("value", [None, [1], [1, "2"], [0, 2]])
def test_parse_channel_mapping_rejects_invalid_values(value) -> None:
    with pytest.raises(ValueError, match="two positive"):
        config.parse_channel_mapping(value)
