"""State helpers for the MatchPatch main window."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

from PySide6.QtCore import QSettings

RECENT_FILES_SETTINGS_KEY = "recentFiles"
MAX_RECENT_FILES = 8


@dataclass(frozen=True)
class RecentFileItem:
    label: str
    path: str


@dataclass(frozen=True)
class FileActionState:
    save_enabled: bool
    save_as_enabled: bool
    save_measurement_enabled: bool
    start_enabled: bool
    determine_enabled: bool
    determine_hint: str
    record_output_enabled: bool
    play_recorded_output_enabled: bool
    workflow_active: bool


def recent_file_paths(settings: QSettings) -> list[str]:
    value = settings.value(RECENT_FILES_SETTINGS_KEY, [])
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = [str(path) for path in value]
    else:
        values = []

    paths: list[str] = []
    seen: set[str] = set()
    for path in values:
        path = path.strip()
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths[:MAX_RECENT_FILES]


def store_recent_file(settings: QSettings, path: PurePath) -> list[str]:
    path_text = _settings_path_text(path)
    recent = [path_text]
    recent.extend(existing for existing in recent_file_paths(settings) if existing != path_text)
    recent = recent[:MAX_RECENT_FILES]
    settings.setValue(RECENT_FILES_SETTINGS_KEY, recent)
    return recent


def recent_file_items(settings: QSettings) -> list[RecentFileItem]:
    return [recent_file_item(path_text) for path_text in recent_file_paths(settings)]


def recent_file_item(path_text: str) -> RecentFileItem:
    path = _display_path(path_text)
    label = f"{path.name} - {path.parent}" if path.name else path_text
    return RecentFileItem(label=label, path=path_text)


def _settings_path_text(path: PurePath) -> str:
    text = str(path)
    if path.drive or text.startswith("\\\\"):
        return text
    return path.as_posix()


def _display_path(path_text: str) -> PurePosixPath | PureWindowsPath:
    if "/" in path_text and "\\" not in path_text:
        return PurePosixPath(path_text)
    return PureWindowsPath(path_text)


def active_file_title(path: Path) -> str:
    filename = path.name if str(path) else ""
    return filename or "MatchPatch"


def determine_parameters_disabled_hint(
    *,
    has_loaded_file: bool,
    has_preset_selection: bool,
) -> str:
    if not has_loaded_file:
        return "Open a Helix file, then select a preset to enable this."
    if not has_preset_selection:
        return "Select at least one preset with a measurable snapshot to enable this."
    return "Wait for the current operation to finish before determining optimal parameters."


def file_action_state(
    *,
    has_file: bool,
    has_loaded_file: bool,
    preset_table_modified: bool,
    has_preset_selection: bool,
    normalization_active: bool,
    hardware_check_active: bool,
    optimization_active: bool,
    preflight_active: bool,
) -> FileActionState:
    determine_enabled = (
        has_loaded_file
        and has_preset_selection
        and not normalization_active
        and not hardware_check_active
        and not optimization_active
    )
    workflow_active = (
        normalization_active or hardware_check_active or optimization_active or preflight_active
    )
    return FileActionState(
        save_enabled=has_file and preset_table_modified,
        save_as_enabled=has_file,
        save_measurement_enabled=has_loaded_file,
        start_enabled=has_loaded_file and not normalization_active,
        determine_enabled=determine_enabled,
        determine_hint=determine_parameters_disabled_hint(
            has_loaded_file=has_loaded_file,
            has_preset_selection=has_preset_selection,
        ),
        record_output_enabled=has_loaded_file,
        play_recorded_output_enabled=True,
        workflow_active=workflow_active,
    )


__all__ = [
    "MAX_RECENT_FILES",
    "RECENT_FILES_SETTINGS_KEY",
    "FileActionState",
    "RecentFileItem",
    "active_file_title",
    "determine_parameters_disabled_hint",
    "file_action_state",
    "recent_file_item",
    "recent_file_items",
    "recent_file_paths",
    "store_recent_file",
]
