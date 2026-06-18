"""File save path dialogs used by the main window."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import QFileDialog, QWidget

from matchpatch.gui import file_type_filters


def choose_save_as_path(
    parent: QWidget,
    *,
    input_path_text: str,
    device_name: str,
    show_error: Callable[[str], None],
    accept_label: str = "Save as",
) -> Path | None:
    suffix = Path(input_path_text).suffix.lower()
    file_filter = file_type_filters.helix_save_file_filter(device_name, suffix)
    if file_filter is None:
        show_error("Open a Helix .hls or .hlx file before saving")
        return None
    dialog = QFileDialog(parent, "Save Helix file as")
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
    dialog.setFileMode(QFileDialog.FileMode.AnyFile)
    dialog.setNameFilter(file_filter)
    dialog.setLabelText(QFileDialog.DialogLabel.Accept, accept_label)
    path = dialog.selectedFiles()[0] if dialog.exec() and dialog.selectedFiles() else ""
    if not path:
        return None
    save_path = Path(path)
    if save_path.suffix.lower() != suffix:
        show_error(f"Saved file must use the {suffix} extension")
        return None
    return save_path


def choose_measurement_save_path(
    parent: QWidget,
    *,
    input_path: Path,
    device_name: str,
    show_error: Callable[[str], None],
) -> Path | None:
    suffix = input_path.suffix.lower()
    file_filter = file_type_filters.helix_save_file_filter(device_name, suffix)
    if file_filter is None:
        show_error("Open a Helix .hls or .hlx file before saving a measurement file")
        return None
    suggested_path = input_path.with_name(input_path.stem + "_measurement" + suffix)
    dialog = QFileDialog(parent, "Save measurement file")
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setFileMode(QFileDialog.FileMode.AnyFile)
    dialog.setNameFilter(file_filter)
    dialog.selectFile(str(suggested_path))
    dialog.setLabelText(QFileDialog.DialogLabel.Accept, "Save")
    path = dialog.selectedFiles()[0] if dialog.exec() and dialog.selectedFiles() else ""
    if not path:
        return None
    save_path = Path(path)
    if save_path.suffix.lower() != suffix:
        show_error(f"Measurement file must use the {suffix} extension")
        return None
    return save_path
