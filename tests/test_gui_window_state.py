from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings

from matchpatch.gui.window_state import (
    MAX_RECENT_FILES,
    RECENT_FILES_SETTINGS_KEY,
    active_file_title,
    file_action_state,
    recent_file_items,
    recent_file_paths,
    store_recent_file,
)


def test_recent_file_paths_normalizes_deduplicates_and_truncates() -> None:
    settings = QSettings()
    values = [" /tmp/one.hls ", "", "/tmp/two.hlx", "/tmp/one.hls"]
    values.extend(f"/tmp/{index}.hls" for index in range(20))
    settings.setValue(RECENT_FILES_SETTINGS_KEY, values)

    assert recent_file_paths(settings) == [
        "/tmp/one.hls",
        "/tmp/two.hlx",
        "/tmp/0.hls",
        "/tmp/1.hls",
        "/tmp/2.hls",
        "/tmp/3.hls",
        "/tmp/4.hls",
        "/tmp/5.hls",
    ]


def test_store_recent_file_moves_existing_path_to_front_and_truncates() -> None:
    settings = QSettings()
    settings.setValue(
        RECENT_FILES_SETTINGS_KEY,
        [f"/tmp/{index}.hls" for index in range(MAX_RECENT_FILES)],
    )

    assert store_recent_file(settings, Path("/tmp/3.hls")) == [
        "/tmp/3.hls",
        "/tmp/0.hls",
        "/tmp/1.hls",
        "/tmp/2.hls",
        "/tmp/4.hls",
        "/tmp/5.hls",
        "/tmp/6.hls",
        "/tmp/7.hls",
    ]
    assert settings.value(RECENT_FILES_SETTINGS_KEY) == [
        "/tmp/3.hls",
        "/tmp/0.hls",
        "/tmp/1.hls",
        "/tmp/2.hls",
        "/tmp/4.hls",
        "/tmp/5.hls",
        "/tmp/6.hls",
        "/tmp/7.hls",
    ]


def test_recent_file_items_format_filename_and_parent() -> None:
    settings = QSettings()
    settings.setValue(RECENT_FILES_SETTINGS_KEY, ["/tmp/session/recent.hlx"])

    assert recent_file_items(settings)[0].label == "recent.hlx - /tmp/session"


def test_active_file_title_uses_filename_or_application_name() -> None:
    assert active_file_title(Path("/tmp/input.hlx")) == "input.hlx"
    assert active_file_title(Path("")) == "MatchPatch"


def test_file_action_state_captures_save_start_and_determine_matrix() -> None:
    state = file_action_state(
        has_file=True,
        has_loaded_file=True,
        preset_table_modified=True,
        has_preset_selection=True,
        normalization_active=False,
        hardware_check_active=False,
        optimization_active=False,
        preflight_active=False,
    )

    assert state.save_enabled
    assert state.save_as_enabled
    assert state.save_measurement_enabled
    assert state.start_enabled
    assert state.determine_enabled
    assert state.record_output_enabled
    assert state.play_recorded_output_enabled
    assert not state.workflow_active


def test_file_action_state_explains_disabled_determine_button() -> None:
    no_file = file_action_state(
        has_file=False,
        has_loaded_file=False,
        preset_table_modified=False,
        has_preset_selection=False,
        normalization_active=False,
        hardware_check_active=False,
        optimization_active=False,
        preflight_active=False,
    )
    busy = file_action_state(
        has_file=True,
        has_loaded_file=True,
        preset_table_modified=False,
        has_preset_selection=True,
        normalization_active=True,
        hardware_check_active=False,
        optimization_active=False,
        preflight_active=True,
    )

    assert "Open a Helix file" in no_file.determine_hint
    assert not no_file.determine_enabled
    assert "current operation" in busy.determine_hint
    assert not busy.determine_enabled
    assert busy.workflow_active
