from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from matchpatch import config
from matchpatch.devices.base import NormalizationPolicy, normalize_regex_pattern


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
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    assert config.default_config_path() == tmp_path / ".config" / "matchpatch" / "config.toml"
    assert config.default_config_paths() == [tmp_path / ".config" / "matchpatch" / "config.toml"]
    assert config.load_config(None) == {}

    with pytest.raises(ValueError, match="does not exist"):
        config.load_config(tmp_path / "missing.toml")


def test_load_config_uses_first_existing_default_path(tmp_path, monkeypatch) -> None:
    xdg_home = tmp_path / "xdg"
    legacy = tmp_path / "home" / ".config" / "matchpatch" / "config.toml"
    primary = xdg_home / "matchpatch" / "config.toml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('[normalize]\nbackend = "legacy"\n', encoding="utf-8")
    primary.parent.mkdir(parents=True)
    primary.write_text('[normalize]\nbackend = "primary"\n', encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))

    assert config.default_config_paths() == [primary, legacy]
    assert config.config_value(config.load_config(None), "normalize", "backend") == "primary"


def test_windows_default_config_paths_use_appdata_then_legacy_path(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    appdata = tmp_path / "AppData" / "Roaming"
    primary = appdata / "MatchPatch" / "config.toml"
    legacy = home / ".config" / "matchpatch" / "config.toml"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert config.default_config_path() == primary
    assert config.default_config_paths() == [primary, legacy]


def test_windows_default_config_path_falls_back_when_appdata_is_missing(
    tmp_path, monkeypatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)

    assert config.default_config_path() == (
        home / "AppData" / "Roaming" / "MatchPatch" / "config.toml"
    )


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


@pytest.mark.parametrize("snapshot_name", ["solo", "Solo Pitch", "solo 1", "clean SOLO boost"])
def test_default_solo_regex_matches_names_containing_solo(snapshot_name) -> None:
    assert re.search(NormalizationPolicy().solo_regex, snapshot_name)


@pytest.mark.parametrize("snapshot_name", ["asolo", "solob", "asoloc"])
def test_default_solo_regex_does_not_match_solo_inside_words(snapshot_name) -> None:
    assert not re.search(NormalizationPolicy().solo_regex, snapshot_name)


def test_regex_pattern_normalization_preserves_decoded_word_boundaries() -> None:
    pattern = normalize_regex_pattern("(?i)\bsolo\b")

    assert pattern == r"(?i)\bsolo\b"
    assert re.search(pattern, "Solo Pitch")
    assert not re.search(pattern, "asolo")


@pytest.mark.parametrize("value", ["1, 2", [3, 4], (5, 6)])
def test_parse_channel_mapping_accepts_supported_shapes(value) -> None:
    assert config.parse_channel_mapping(value)[1] % 2 == 0


@pytest.mark.parametrize("value", [None, [1], [1, "2"], [0, 2]])
def test_parse_channel_mapping_rejects_invalid_values(value) -> None:
    with pytest.raises(ValueError, match="two positive"):
        config.parse_channel_mapping(value)
