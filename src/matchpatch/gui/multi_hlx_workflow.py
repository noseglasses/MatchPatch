"""Open and save workflows for multiple Helix preset files."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from PySide6.QtWidgets import QCheckBox, QMessageBox, QTableWidgetItem, QWidget

from matchpatch import file_operations
from matchpatch.devices import get_device_profile
from matchpatch.gui import file_operations_workflow
from matchpatch.gui.advanced_settings import GuiSettingsBinder
from matchpatch.gui.main_window_callbacks import MainWindowSaveCallbacks
from matchpatch.gui.save_workflow import SaveContext, SaveWorkflow
from matchpatch.gui.window_state import RECENT_FILES_SETTINGS_KEY
from matchpatch.workflow import NormalizationRequest, NormalizationResult

if TYPE_CHECKING:
    from matchpatch.gui.main_window import MainWindow


class _CurrentDeviceWidget(Protocol):
    def currentData(self) -> str: ...


class _InputPathWidget(Protocol):
    def text(self) -> str: ...


class _PresetTableWidget(Protocol):
    def item(self, row: int, column: int) -> QTableWidgetItem | None: ...


class _SettingsStore(Protocol):
    def setValue(self, key: str, value: object) -> None: ...


class MultiHlxWindow(Protocol):
    device: _CurrentDeviceWidget
    input_path: _InputPathWidget
    preset_table: _PresetTableWidget
    settings: _SettingsStore
    completed_request: NormalizationRequest | None
    completed_result: NormalizationResult | None
    _staged_joined_setlist_path: Path | None
    _multi_hlx_output_paths_by_id: dict[int, Path]
    _multi_hlx_input_count: int

    def _open_input_path(self, path: str) -> None: ...
    def _preset_table_has_unsaved_changes(self) -> bool: ...
    def _prompt_save_or_discard_preset_table_changes(self, action: str) -> str | bool: ...
    def _discard_preset_table_changes(self) -> None: ...
    def _log(self, message: str, level: str) -> None: ...
    def _mark_multi_hlx_setlist_staged(self, path: Path, preset_paths: list[Path]) -> None: ...
    def _recent_file_paths(self) -> list[str]: ...
    def _refresh_recent_files_selector(self) -> None: ...
    def setWindowTitle(self, title: str) -> None: ...
    def _mark_preset_table_modified(self) -> None: ...
    def _refresh_file_actions(self) -> None: ...
    def _set_phase(self, phase: str) -> None: ...
    def _reset_preset_table_modified(self) -> None: ...
    def _save_workflow(self) -> SaveWorkflow: ...
    def show_error(self, message: str) -> None: ...


def open_input_paths(window: MultiHlxWindow, paths: list[str]) -> None:
    selected_paths = [Path(path) for path in paths if path]
    if not selected_paths:
        return
    if len(selected_paths) == 1:
        window._open_input_path(str(selected_paths[0]))
        return

    suffixes = {path.suffix.lower() for path in selected_paths}
    if suffixes != {".hlx"}:
        window.show_error(
            "Select either one .hls setlist, one .hlx preset, or multiple .hlx presets. "
            "Do not mix .hls and .hlx files."
        )
        return
    open_multiple_hlx_paths(window, selected_paths)


def open_multiple_hlx_paths(window: MultiHlxWindow, paths: list[Path]) -> None:
    if window._preset_table_has_unsaved_changes():
        prompt_result = window._prompt_save_or_discard_preset_table_changes(
            "opening another preset or setlist file"
        )
        if not prompt_result:
            return
        if prompt_result == "discard":
            window._discard_preset_table_changes()

    file_types = file_operations_workflow.current_file_types(
        cast(file_operations_workflow.FileOperationWindow, window),
        get_profile=get_device_profile,
        project_dir=_project_dir(),
    )
    output_path = file_operations_workflow.temporary_join_output_path(file_types)
    try:
        result = file_operations.join_preset_files(
            window.device.currentData(),
            paths,
            output_path,
            log_callback=lambda message: window._log(message, "info"),
        )
    except Exception as exc:  # noqa: BLE001
        output_path.unlink(missing_ok=True)
        window.show_error(str(exc))
        return

    window._open_input_path(str(result.output_path))
    mark_multi_hlx_setlist_staged(window, result.output_path, paths)


def mark_joined_setlist_staged(window: MultiHlxWindow, path: Path) -> None:
    window._staged_joined_setlist_path = path
    window._multi_hlx_output_paths_by_id = {}
    window._multi_hlx_input_count = 0
    _remove_recent_file(window, path)
    window.setWindowTitle("Joined setlist (unsaved)")
    window._mark_preset_table_modified()
    window._refresh_file_actions()


def mark_multi_hlx_setlist_staged(
    window: MultiHlxWindow,
    path: Path,
    preset_paths: list[Path],
) -> None:
    window._staged_joined_setlist_path = None
    window._multi_hlx_output_paths_by_id = multi_hlx_path_map(window, preset_paths)
    window._multi_hlx_input_count = len(preset_paths)
    _remove_recent_file(window, path)
    window.setWindowTitle(f"{len(preset_paths)} presets (multiple .hlx files)")
    window._refresh_file_actions()


def multi_hlx_path_map(window: MultiHlxWindow, preset_paths: list[Path]) -> dict[int, Path]:
    try:
        profile = get_device_profile(window.device.currentData())
        handler = profile.create_patch_file_handler(_project_dir())
    except Exception:  # noqa: BLE001
        return {}

    output_paths_by_id: dict[int, Path] = {}
    for row, preset_path in enumerate(preset_paths):
        patch_item = window.preset_table.item(row, 1)
        patch = patch_item.text().strip() if patch_item is not None else ""
        try:
            preset_ids = handler.parse_patch_set(patch)
        except ValueError:
            continue
        if len(preset_ids) == 1:
            output_paths_by_id[preset_ids[0]] = preset_path
    return output_paths_by_id


def save_multi_hlx_files(window: MultiHlxWindow) -> bool:
    if not window._preset_table_has_unsaved_changes():
        return True
    if not window._multi_hlx_output_paths_by_id:
        window.show_error("Open multiple .hlx preset files before saving them together")
        return False
    if len(window._multi_hlx_output_paths_by_id) != window._multi_hlx_input_count:
        window.show_error(
            "Could not map every open .hlx preset back to its original file. "
            "Use Save As to write a setlist instead."
        )
        return False
    output_paths = list(window._multi_hlx_output_paths_by_id.values())
    if not confirm_multi_hlx_overwrites(window, output_paths):
        return False

    active_path = Path(window.input_path.text())
    with tempfile.TemporaryDirectory(prefix="matchpatch_multi_hlx_") as temporary_directory:
        temporary_dir = Path(temporary_directory)
        materialized_setlist = temporary_dir / "materialized.hls"
        if not save_table_to_temporary_setlist(window, materialized_setlist):
            return False
        if not _split_and_copy_presets(window, materialized_setlist, temporary_dir, active_path):
            return False

    window._set_phase("completed")
    window._reset_preset_table_modified()
    window._refresh_file_actions()
    return True


def save_table_to_temporary_setlist(window: MultiHlxWindow, output_path: Path) -> bool:
    request = window.completed_request
    result = window.completed_result
    if request is None:
        try:
            request = GuiSettingsBinder.from_widgets(window).normalization_request()
        except Exception as exc:  # noqa: BLE001
            window.show_error(str(exc))
            return False

    try:
        window._save_workflow().save_adjusted_file(
            SaveContext(
                input_path=Path(window.input_path.text()),
                output_path=output_path,
                completed_request=request,
                completed_result=result,
                table_has_unsaved_changes=True,
                make_active=False,
            ),
            MainWindowSaveCallbacks(
                cast("MainWindow", window),
                confirm_overwrite=lambda output_path: True,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        window.show_error(str(exc))
        return False
    return True


def confirm_multi_hlx_overwrites(window: MultiHlxWindow, output_paths: list[Path]) -> bool:
    overwrite_all = False
    existing_paths = [path for path in output_paths if path.exists()]
    for index, output_path in enumerate(existing_paths):
        if overwrite_all:
            continue
        dialog = QMessageBox(cast(QWidget, window))
        dialog.setWindowTitle("Overwrite preset file")
        dialog.setText(f"The file already exists:\n{output_path}\n\nOverwrite it?")
        overwrite_button = dialog.addButton(
            QMessageBox.StandardButton.Yes,
        )
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(overwrite_button)
        checkbox: QCheckBox | None = None
        if len(existing_paths) > 1 and index == 0:
            checkbox = QCheckBox("I do not want to be asked again, overwrite them all")
            dialog.setCheckBox(checkbox)
        dialog.exec()
        if dialog.clickedButton() is not overwrite_button:
            return False
        overwrite_all = checkbox is not None and checkbox.isChecked()
    return True


def _split_and_copy_presets(
    window: MultiHlxWindow,
    materialized_setlist: Path,
    temporary_dir: Path,
    active_path: Path,
) -> bool:
    temporary_names = {
        preset_id: f"{preset_id:03d}_{output_path.name}"
        for preset_id, output_path in window._multi_hlx_output_paths_by_id.items()
    }
    try:
        result = file_operations.split_setlist_file(
            window.device.currentData(),
            materialized_setlist,
            temporary_dir / "presets",
            selected_ids=list(window._multi_hlx_output_paths_by_id),
            original_filenames=temporary_names,
            log_callback=lambda message: window._log(message, "info"),
        )
        created_by_name = {path.name: path for path in result.created_paths}
        for preset_id, output_path in window._multi_hlx_output_paths_by_id.items():
            created_path = created_by_name.get(temporary_names[preset_id])
            if created_path is None:
                raise ValueError(f"Could not create updated preset file for {output_path}")
            shutil.copy2(created_path, output_path)
            window._log(f"Saved preset file: {output_path.resolve()}", "success")
        shutil.copy2(materialized_setlist, active_path)
    except Exception as exc:  # noqa: BLE001
        window.show_error(str(exc))
        return False
    return True


def _remove_recent_file(window: MultiHlxWindow, path: Path) -> None:
    recent = [item for item in window._recent_file_paths() if item != str(path)]
    window.settings.setValue(RECENT_FILES_SETTINGS_KEY, recent)
    window._refresh_recent_files_selector()


def _project_dir() -> Path:
    return Path(__file__).resolve().parents[3]
