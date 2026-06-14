from __future__ import annotations

import os
from dataclasses import dataclass, field

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtGui import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
)

from matchpatch.gui import preset_table_csv
from matchpatch.gui.main_window import MainWindow
from matchpatch.gui.preset_table import snapshot_adjustment_column, snapshot_name_column
from matchpatch.gui.table_roles import ADJUSTMENT_VALUE_ROLE, IGNORED_SNAPSHOT_ROLE


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    QCoreApplication.setOrganizationName("MatchPatchTests")
    QCoreApplication.setApplicationName("MatchPatchTests")
    yield instance


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path):
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings().clear()
    yield
    QSettings().clear()


@dataclass
class CsvCallbacks:
    table: QTableWidget | None = None
    adjusted: list[str] = field(default_factory=list)

    def validate_preset_name(self, name: str) -> None:
        self._validate_name(name)

    def validate_snapshot_name(self, name: str) -> None:
        self._validate_name(name)

    def is_solo_snapshot_name(self, name: str) -> bool:
        return name.startswith("Solo")

    def is_ignored_snapshot_name(self, name: str) -> bool:
        return name.startswith("Skip")

    def set_snapshot_name(
        self,
        item: QTableWidgetItem,
        name: str,
        is_solo: bool,
        is_ignored: bool = False,
    ) -> None:
        item.setText(name)
        item.setData(IGNORED_SNAPSHOT_ROLE, True if is_ignored else None)

    def set_ignored_snapshot_highlight(
        self,
        row: int,
        snapshot_index: int,
        ignored: bool,
    ) -> None:
        table = self.table
        assert table is not None
        item = table.item(row, snapshot_adjustment_column(snapshot_index))
        assert item is not None
        item.setText("Ignore")
        item.setData(IGNORED_SNAPSHOT_ROLE, True if ignored else None)

    def set_adjustment_value(
        self,
        item: QTableWidgetItem,
        text: str,
        value: float,
    ) -> None:
        item.setText("0" if value == 0 else text)
        item.setData(ADJUSTMENT_VALUE_ROLE, value)

    def mark_preset_adjusted(self, preset_id: str) -> None:
        self.adjusted.append(preset_id)

    @staticmethod
    def _validate_name(name: str) -> None:
        if "%" in name:
            raise ValueError("Invalid Helix name")


def test_preset_table_csv_headers_and_row_export_custom_stored_value(app) -> None:
    table = QTableWidget()
    table.setColumnCount(9)
    table.insertRow(0)
    table.setItem(0, 1, QTableWidgetItem("02B"))
    table.setItem(0, 2, QTableWidgetItem("Song, Part 1"))
    table.setItem(0, snapshot_name_column(0), QTableWidgetItem("Clean, bright"))
    table.setItem(0, snapshot_name_column(1), QTableWidgetItem("Solo"))
    first_adjustment = QTableWidgetItem("+1.5 (+2)")
    first_adjustment.setData(ADJUSTMENT_VALUE_ROLE, 3.5)
    table.setItem(0, snapshot_adjustment_column(0), first_adjustment)
    second_adjustment = QTableWidgetItem("-2.0")
    second_adjustment.setData(ADJUSTMENT_VALUE_ROLE, -2.0)
    table.setItem(0, snapshot_adjustment_column(1), second_adjustment)

    assert preset_table_csv.preset_table_csv_headers(2) == [
        "preset_id",
        "preset_name",
        "snapshot_1_name",
        "snapshot_1_adjustment",
        "snapshot_2_name",
        "snapshot_2_adjustment",
    ]
    assert preset_table_csv.preset_table_csv_row(table, 0, 2) == [
        "02B",
        "Song, Part 1",
        "Clean, bright",
        "+3.5",
        "Solo",
        "-2.0",
    ]
    table.close()


def test_preset_table_csv_row_exports_ignored_snapshot_tokens(app) -> None:
    table = QTableWidget()
    table.setColumnCount(9)
    table.insertRow(0)
    table.setItem(0, 1, QTableWidgetItem("02B"))
    table.setItem(0, 2, QTableWidgetItem("Song"))
    table.setItem(0, snapshot_name_column(0), QTableWidgetItem("Skip Intro"))
    table.setItem(0, snapshot_name_column(1), QTableWidgetItem("Skip Lead"))
    first_adjustment = QTableWidgetItem("-")
    first_adjustment.setData(IGNORED_SNAPSHOT_ROLE, True)
    table.setItem(0, snapshot_adjustment_column(0), first_adjustment)
    second_adjustment = QTableWidgetItem("Ignore")
    second_adjustment.setData(IGNORED_SNAPSHOT_ROLE, True)
    table.setItem(0, snapshot_adjustment_column(1), second_adjustment)

    assert preset_table_csv.preset_table_csv_row(table, 0, 2) == [
        "02B",
        "Song",
        "Skip Intro",
        "-",
        "Skip Lead",
        "Ignore",
    ]
    table.close()


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (["02B", "Song", "Clean"], "expected 4 columns, got 3"),
        (["99A", "Song", "Clean", "0"], "preset ID '99A'"),
        (["02B", "Invalid%", "Clean", "0"], "preset name is invalid"),
        (["02B", "Song", "Invalid%", "0"], "snapshot 1 name is invalid"),
        (["02B", "Song", "Clean", "loud"], "is not a floating point number"),
        (["02B", "Song", "Clean", "nan"], "is not finite"),
    ],
)
def test_parse_preset_table_csv_row_reports_invalid_rows(row, message, app) -> None:
    errors: list[str] = []

    parsed = preset_table_csv.parse_preset_table_csv_row(
        row,
        7,
        preset_table_csv.preset_table_csv_headers(1),
        {"02B": 0},
        1,
        CsvCallbacks(),
        errors,
    )

    assert parsed is None
    assert len(errors) == 1
    assert "Line 7" in errors[0]
    assert message in errors[0]


def test_apply_preset_table_csv_row_preserves_ignored_adjustment_tokens(app) -> None:
    table = QTableWidget()
    table.setColumnCount(9)
    table.insertRow(0)
    table.setItem(0, 1, QTableWidgetItem("02B"))
    table.setItem(0, 2, QTableWidgetItem("Song"))
    for snapshot_index in range(2):
        table.setItem(0, snapshot_name_column(snapshot_index), QTableWidgetItem())
        table.setItem(0, snapshot_adjustment_column(snapshot_index), QTableWidgetItem())
    callbacks = CsvCallbacks(table=table)

    preset_table_csv.apply_preset_table_csv_row(
        table,
        0,
        "Song",
        ["Skip Intro", "Skip Lead"],
        [("-", 0.0), ("Ignore", 0.0)],
        callbacks,
    )

    assert table.item(0, snapshot_adjustment_column(0)).text() == "-"
    assert table.item(0, snapshot_adjustment_column(1)).text() == "Ignore"
    assert table.item(0, snapshot_adjustment_column(0)).data(IGNORED_SNAPSHOT_ROLE)
    assert table.item(0, snapshot_adjustment_column(1)).data(IGNORED_SNAPSHOT_ROLE)
    table.close()


def test_load_preset_table_csv_applies_valid_rows_and_reports_errors(tmp_path, app) -> None:
    table = QTableWidget()
    table.setColumnCount(9)
    for row, (preset_id, preset_name) in enumerate((("02B", "Song"), ("01A", "Other"))):
        table.insertRow(row)
        table.setItem(row, 1, QTableWidgetItem(preset_id))
        table.setItem(row, 2, QTableWidgetItem(preset_name))
        for snapshot_index in range(2):
            table.setItem(row, snapshot_name_column(snapshot_index), QTableWidgetItem())
            table.setItem(row, snapshot_adjustment_column(snapshot_index), QTableWidgetItem())

    csv_path = tmp_path / "preset-table.csv"
    csv_path.write_text(
        "\n".join(
            [
                "preset_id|preset_name|snapshot_1_name|snapshot_1_adjustment|"
                "snapshot_2_name|snapshot_2_adjustment",
                "02B|Song 2|Clean!|+1.5|Solo|-2.0",
                "99A|Missing|Clean|0|Solo|0",
                "01A|Invalid%|Clean|0|Solo|0",
                "01A|Other|Clean|nan|Solo|0",
                "01A|Other 2|Clean|0|Skip Lead|Ignore",
            ]
        ),
        encoding="utf-8",
    )
    callbacks = CsvCallbacks()
    callbacks.table = table

    result = preset_table_csv.load_preset_table_csv(csv_path, table, 2, callbacks)

    assert result.accepted == 2
    assert len(result.errors) == 3
    assert "Line 3" in result.errors[0]
    assert "preset ID '99A'" in result.errors[0]
    assert "Line 4" in result.errors[1]
    assert "Line 5" in result.errors[2]
    assert table.item(0, 2).text() == "Song 2"
    assert table.item(0, snapshot_name_column(0)).text() == "Clean!"
    assert table.item(0, snapshot_adjustment_column(0)).text() == "+1.5"
    assert table.item(1, 2).text() == "Other 2"
    assert table.item(1, snapshot_name_column(1)).text() == "Skip Lead"
    assert table.item(1, snapshot_adjustment_column(1)).data(IGNORED_SNAPSHOT_ROLE)
    assert callbacks.adjusted == ["02B", "01A"]
    table.close()


def test_preset_table_csv_save_uses_pipe_delimiter(tmp_path, monkeypatch, app) -> None:
    window = MainWindow()
    window.snapshot_count_input.setValue(2)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song, Part 1"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Clean, bright", "Solo"))
    window.preset_table_controller.set_adjustment_value(window.preset_table.item(0, 5), "+1.5", 1.5)
    window.preset_table_controller.set_adjustment_value(
        window.preset_table.item(0, 8), "-2.0", -2.0
    )
    csv_path = tmp_path / "preset-table"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(csv_path), ""),
    )

    window.save_preset_table_csv()

    assert (tmp_path / "preset-table.csv").read_text(encoding="utf-8").splitlines() == [
        "preset_id|preset_name|snapshot_1_name|snapshot_1_adjustment|"
        "snapshot_2_name|snapshot_2_adjustment",
        "02B|Song, Part 1|Clean, bright|+1.5|Solo|-2.0",
    ]
    assert "Preset table CSV saved" in window.log.toHtml()

    window.close()


def test_preset_table_csv_load_applies_valid_rows_and_reports_line_errors(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    window.snapshot_count_input.setValue(2)
    for row, (patch, name) in enumerate((("02B", "Song"), ("01A", "Other"))):
        window.preset_table.insertRow(row)
        selected = QTableWidgetItem()
        selected.setCheckState(Qt.CheckState.Checked)
        window.preset_table.setItem(row, 0, selected)
        window.preset_table.setItem(row, 1, QTableWidgetItem(patch))
        window.preset_table.setItem(row, 2, QTableWidgetItem(name))
        window.preset_table_controller.clear_preset_adjustments(row)

    csv_path = tmp_path / "preset-table.csv"
    csv_path.write_text(
        "\n".join(
            [
                "preset_id|preset_name|snapshot_1_name|snapshot_1_adjustment|"
                "snapshot_2_name|snapshot_2_adjustment",
                "02B|Song 2|Clean!|+1.5|Solo|-2.0",
                "99A|Missing|Clean|0|Solo|0",
                "01A|Invalid%|Clean|0|Solo|0",
                "01A|Other|Clean|nan|Solo|0",
                "01A|Other 2|Clean|0|Solo|+3.0",
            ]
        ),
        encoding="utf-8",
    )
    popups = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(csv_path), ""),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: popups.append(args))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)

    window.load_preset_table_csv()

    assert window.preset_table.item(0, 2).text() == "Song 2"
    assert window.preset_table.item(0, 3).text() == "Clean!"
    assert window.preset_table.item(0, 5).text() == "+1.5"
    assert window.preset_table.item(0, 6).text() == "Solo"
    assert window.preset_table.item(0, 8).text() == "-2.0"
    assert window.preset_table.item(1, 2).text() == "Other 2"
    assert window.preset_table.item(1, 8).text() == "+3.0"
    assert len(popups) == 1
    assert popups[0][1] == "Preset table CSV errors"
    assert "Line 3" in popups[0][2]
    assert "Line 4" in popups[0][2]
    assert "Line 5" in popups[0][2]
    assert "preset ID '99A'" in window.log.toPlainText()
    assert "Preset table CSV loaded" in window.log.toHtml()
    assert window._preset_table_modified

    window.close()


def test_preset_table_csv_load_does_not_mark_identical_content_modified(
    tmp_path, monkeypatch, app
) -> None:
    window = MainWindow()
    window.snapshot_count_input.setValue(1)
    window.preset_table.insertRow(0)
    selected = QTableWidgetItem()
    selected.setCheckState(Qt.CheckState.Checked)
    window.preset_table.setItem(0, 0, selected)
    window.preset_table.setItem(0, 1, QTableWidgetItem("02B"))
    window.preset_table.setItem(0, 2, QTableWidgetItem("Song"))
    window.preset_table_controller.clear_preset_adjustments(0)
    window.preset_table_controller.set_snapshot_names(0, ("Clean",))
    window._reset_preset_table_modified()
    csv_path = tmp_path / "preset-table.csv"
    csv_path.write_text(
        "\n".join(
            [
                "preset_id|preset_name|snapshot_1_name|snapshot_1_adjustment",
                "02B|Song|Clean|0",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(csv_path), ""),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: pytest.fail("identical CSV should not create a close prompt"),
    )

    window.load_preset_table_csv()

    assert not window._preset_table_modified

    window.close()
