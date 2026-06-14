"""Save/export workflow helpers for the GUI."""

from __future__ import annotations

import csv
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from matchpatch.devices import get_device_profile
from matchpatch.devices.base import DeviceProfile, PatchFileAdjustments
from matchpatch.progress import ProgressEvent
from matchpatch.workflow import (
    PROJECT_DIR,
    NormalizationRequest,
    NormalizationResult,
    export_adjusted_file,
)


class SaveCancelled(Exception):
    """Raised when the user cancels an overwrite prompt."""


ConfirmOverwrite = Callable[[Path], bool]
ProgressCallback = Callable[[ProgressEvent], None]
ProfileProvider = Callable[[str], DeviceProfile]
ExportAdjustedFile = Callable[..., None]


class SaveCallbacks(Protocol):
    def confirm_overwrite(self, output_path: Path) -> bool: ...
    def create_table_save_csv(self, directory: Path) -> Path: ...
    def table_adjustments(self) -> PatchFileAdjustments: ...
    def update_progress(self, event: ProgressEvent) -> None: ...


@dataclass(frozen=True)
class SaveContext:
    input_path: Path
    output_path: Path
    completed_request: NormalizationRequest | None
    completed_result: NormalizationResult | None
    table_has_unsaved_changes: bool
    make_active: bool = True


@dataclass(frozen=True)
class SaveResult:
    output_path: Path
    saved_table_changes: bool
    copied_active_file: bool = False


class SaveWorkflow:
    def __init__(
        self,
        *,
        get_profile: ProfileProvider = get_device_profile,
        export_file: ExportAdjustedFile = export_adjusted_file,
        project_dir: Path = PROJECT_DIR,
    ) -> None:
        self._get_profile = get_profile
        self._export_file = export_file
        self._project_dir = project_dir

    def save_adjusted_file(
        self,
        context: SaveContext,
        callbacks: SaveCallbacks,
    ) -> SaveResult:
        if not context.table_has_unsaved_changes:
            if context.make_active and context.output_path != context.input_path:
                self.copy_active_file_to(
                    context.input_path,
                    context.output_path,
                    callbacks.confirm_overwrite,
                )
                return SaveResult(
                    context.output_path,
                    saved_table_changes=False,
                    copied_active_file=True,
                )
            return SaveResult(context.output_path, saved_table_changes=False)

        request = context.completed_request
        if request is None:
            raise ValueError("A normalization request is required to save table changes")

        csv_path = (
            context.completed_result.retained_csv_path
            if context.completed_result is not None
            else None
        )
        temporary_csv: Path | None = None
        if csv_path is None:
            temporary_csv = callbacks.create_table_save_csv(context.output_path.parent)
            csv_path = temporary_csv

        try:
            profile = self._get_profile(request.device)
            handler = profile.create_patch_file_handler(self._project_dir)
            handler.validate_output(request.input_path, context.output_path)

            if not callbacks.confirm_overwrite(context.output_path):
                raise SaveCancelled

            export_path, temporary_output = self._export_path_for_save(
                request.input_path,
                context.output_path,
            )
            try:
                self._export_file(
                    request,
                    csv_path,
                    export_path,
                    adjustments=callbacks.table_adjustments(),
                    on_progress=callbacks.update_progress,
                )
                if temporary_output is not None:
                    temporary_output.replace(context.output_path)
            except Exception:
                if temporary_output is not None:
                    temporary_output.unlink(missing_ok=True)
                raise
        finally:
            if temporary_csv is not None:
                temporary_csv.unlink(missing_ok=True)

        return SaveResult(context.output_path, saved_table_changes=True)

    def save_measurement_file(
        self,
        request: NormalizationRequest,
        output_path: Path,
        *,
        confirm_overwrite: ConfirmOverwrite,
    ) -> None:
        profile = self._get_profile(request.device)
        handler = profile.create_patch_file_handler(self._project_dir)
        handler.validate_output(request.input_path, output_path)
        if not confirm_overwrite(output_path):
            raise SaveCancelled
        handler.create_measurement_file(request.input_path, output_path)

    @staticmethod
    def copy_active_file_to(
        input_path: Path,
        output_path: Path,
        confirm_overwrite: ConfirmOverwrite,
    ) -> None:
        if not confirm_overwrite(output_path):
            raise SaveCancelled
        shutil.copy2(input_path, output_path)

    @staticmethod
    def _export_path_for_save(input_path: Path, output_path: Path) -> tuple[Path, Path | None]:
        if output_path.resolve() != input_path.resolve():
            return output_path, None
        temporary = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=output_path.suffix,
            dir=output_path.parent,
            delete=False,
        )
        temporary.close()
        temporary_output = Path(temporary.name)
        return temporary_output, temporary_output


def create_table_save_csv(
    directory: Path,
    *,
    snapshot_count: int,
    patches: list[str],
    target_lufs: str,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        suffix=".matchpatch-save.csv",
        dir=directory,
        delete=False,
    )
    with temporary:
        fieldnames = ["DevicePatch"]
        for snapshot in range(1, snapshot_count + 1):
            fieldnames.extend([f"LUFS{snapshot}", f"CrestFactor{snapshot}"])
        writer = csv.DictWriter(temporary, fieldnames=fieldnames)
        writer.writeheader()
        for patch in patches:
            csv_row = {"DevicePatch": patch}
            for snapshot in range(1, snapshot_count + 1):
                csv_row[f"LUFS{snapshot}"] = target_lufs or "-16.0"
                csv_row[f"CrestFactor{snapshot}"] = "12.0"
            writer.writerow(csv_row)
    return Path(temporary.name)
