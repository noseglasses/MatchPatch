"""GUI helpers for device file split/join operations."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol, cast

from PySide6.QtWidgets import QFileDialog, QWidget

from matchpatch import file_operations
from matchpatch.devices import get_device_profile
from matchpatch.devices.base import (
    DeviceFileKind,
    DeviceFileType,
    DeviceProfile,
    FileOperationCapabilities,
)
from matchpatch.gui.window_state import FileActionState


class PresetTableControllerLike(Protocol):
    def original_filename_map(
        self,
        parse_patch_set: Callable[[str], list[int]] | None = None,
    ) -> dict[int, str]: ...

    def preset_ids_for_rows(
        self,
        rows: list[int],
        parse_patch_set: Callable[[str], list[int]],
    ) -> list[int]: ...

    def selected_rows_or_all_measurable_rows(self) -> list[int]: ...


class FileOperationWindow(Protocol):
    device: Any
    input_path: Any
    preset_table_controller: PresetTableControllerLike
    _loaded_input_path: str

    def show_error(self, message: str) -> None: ...

    def _log(self, message: str, level: str) -> None: ...

    def _open_input_path(self, path: str) -> None: ...

    def _set_optional_widget_enabled(self, name: str, enabled: bool) -> None: ...


ProfileProvider = Callable[[str], DeviceProfile]


def _file_type_patterns(
    file_types: Iterable[DeviceFileType],
    kind: DeviceFileKind,
) -> tuple[str, ...]:
    return tuple(
        pattern
        for file_type in file_types
        if file_type.kind == kind
        for pattern in file_type.patterns()
    )


def _kind_file_filter(
    file_types: Iterable[DeviceFileType],
    kind: DeviceFileKind,
    fallback: str,
) -> str:
    patterns = _file_type_patterns(file_types, kind)
    if not patterns:
        return fallback
    label = "Preset files" if kind == "preset" else "Setlist files"
    return f"{label} ({' '.join(patterns)})"


def _kind_extension(
    file_types: Iterable[DeviceFileType],
    kind: DeviceFileKind,
    fallback: str,
) -> str:
    for file_type in file_types:
        if file_type.kind == kind and file_type.normalized_extensions():
            return file_type.normalized_extensions()[0]
    return fallback


def current_file_types(
    window: FileOperationWindow,
    *,
    get_profile: ProfileProvider,
    project_dir: Path,
) -> tuple[DeviceFileType, ...]:
    device = window.device.currentData() if hasattr(window, "device") else None
    if not device:
        return ()
    try:
        profile = get_profile(device)
        handler = profile.create_patch_file_handler(project_dir)
        return handler.file_types()
    except Exception:  # noqa: BLE001
        return ()


def choose_join_preset_paths(
    parent: QWidget,
    file_types: Iterable[DeviceFileType] = (),
) -> list[Path] | None:
    paths, _ = QFileDialog.getOpenFileNames(
        parent,
        "Choose preset files",
        filter=_kind_file_filter(file_types, "preset", "Preset files (*.hlx)"),
    )
    return [Path(path) for path in paths] if paths else None


def choose_join_output_path(
    parent: QWidget,
    file_types: Iterable[DeviceFileType] = (),
) -> Path | None:
    path, _ = QFileDialog.getSaveFileName(
        parent,
        "Save joined setlist",
        filter=_kind_file_filter(file_types, "setlist", "Setlist files (*.hls)"),
    )
    if not path:
        return None
    output_path = Path(path)
    suffix = _kind_extension(file_types, "setlist", ".hls")
    return output_path if output_path.suffix.lower() == suffix else output_path.with_suffix(suffix)


def choose_split_output_dir(parent: QWidget) -> Path | None:
    path = QFileDialog.getExistingDirectory(parent, "Choose split output directory")
    return Path(path) if path else None


def selected_split_preset_ids(
    controller: PresetTableControllerLike,
    parse_patch_set: Callable[[str], list[int]],
) -> list[int] | None:
    rows = controller.selected_rows_or_all_measurable_rows()
    preset_ids = controller.preset_ids_for_rows(rows, parse_patch_set)
    return preset_ids or None


def original_filename_map(
    controller: PresetTableControllerLike,
    parse_patch_set: Callable[[str], list[int]],
) -> dict[int, str]:
    return controller.original_filename_map(parse_patch_set)


def created_files_log(created_paths: Iterable[Path]) -> list[str]:
    return [f"Created preset file: {path.resolve()}" for path in created_paths]


def join_preset_files(window: FileOperationWindow) -> bool:
    parent = cast(QWidget, window)
    file_types = current_file_types(
        window,
        get_profile=get_device_profile,
        project_dir=Path(__file__).resolve().parents[3],
    )
    preset_paths = choose_join_preset_paths(parent, file_types)
    if not preset_paths:
        return False
    output_path = choose_join_output_path(parent, file_types)
    if output_path is None:
        return False

    try:
        result = file_operations.join_preset_files(
            window.device.currentData(),
            preset_paths,
            output_path,
        )
    except Exception as exc:  # noqa: BLE001
        window.show_error(str(exc))
        return False

    window._log(f"Joined preset files: {result.output_path.resolve()}", "success")
    window._open_input_path(str(result.output_path))
    return True


def split_setlist(
    window: FileOperationWindow,
    *,
    get_profile: ProfileProvider,
    project_dir: Path,
) -> bool:
    input_path = Path(window.input_path.text().strip())
    if not window._loaded_input_path or not input_path:
        window.show_error("Open a setlist file before splitting presets")
        return False
    output_dir = choose_split_output_dir(cast(QWidget, window))
    if output_dir is None:
        return False

    try:
        profile = get_profile(window.device.currentData())
        handler = profile.create_patch_file_handler(project_dir)
        selected_ids = selected_split_preset_ids(
            window.preset_table_controller,
            handler.parse_patch_set,
        )
        filenames = original_filename_map(
            window.preset_table_controller,
            handler.parse_patch_set,
        )
        result = file_operations.split_setlist_file(
            window.device.currentData(),
            input_path,
            output_dir,
            selected_ids=selected_ids,
            original_filenames=filenames,
        )
    except Exception as exc:  # noqa: BLE001
        window.show_error(str(exc))
        return False

    for message in created_files_log(result.created_paths):
        window._log(message, "success")
    window._log(
        f"Split setlist into {len(result.created_paths)} preset file(s)",
        "success",
    )
    return True


def apply_file_operation_action_state(
    window: FileOperationWindow,
    action_state: FileActionState,
    *,
    get_profile: ProfileProvider,
    project_dir: Path,
) -> None:
    capabilities = current_file_operation_capabilities(
        window,
        get_profile=get_profile,
        project_dir=project_dir,
    )
    window._set_optional_widget_enabled(
        "join_preset_files_action",
        capabilities.joins_presets_to_setlist and not action_state.workflow_active,
    )
    window._set_optional_widget_enabled(
        "split_setlist_action",
        capabilities.splits_setlist_to_presets
        and active_file_kind(window, get_profile=get_profile, project_dir=project_dir) == "setlist"
        and not action_state.workflow_active,
    )


def current_file_operation_capabilities(
    window: FileOperationWindow,
    *,
    get_profile: ProfileProvider,
    project_dir: Path,
) -> FileOperationCapabilities:
    device = window.device.currentData() if hasattr(window, "device") else None
    if not device:
        return FileOperationCapabilities()
    try:
        profile = get_profile(device)
        handler = profile.create_patch_file_handler(project_dir)
        return handler.file_capabilities()
    except Exception:  # noqa: BLE001
        return FileOperationCapabilities()


def active_file_kind(
    window: FileOperationWindow,
    *,
    get_profile: ProfileProvider,
    project_dir: Path,
) -> str:
    path_text = window.input_path.text().strip() if hasattr(window, "input_path") else ""
    if not path_text or not window._loaded_input_path:
        return "unknown"
    try:
        profile = get_profile(window.device.currentData())
        handler = profile.create_patch_file_handler(project_dir)
        return handler.file_kind(Path(path_text))
    except Exception:  # noqa: BLE001
        return "unknown"
