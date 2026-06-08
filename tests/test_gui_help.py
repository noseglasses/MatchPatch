from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from matchpatch.gui import help as gui_help
from matchpatch.gui import main_window
from matchpatch.gui.help import GITHUB_DOCS_URL, HELP_TOPICS, HelpId
from matchpatch.gui.main_window import (
    MEASUREMENT_TIMING_PRESETS,
    MainWindow,
    MeasurementOptimizationDialog,
    MeasurementOptimizationSettings,
    MeasurementOptimizationSetupDialog,
)

DOCS_ROOT = Path(__file__).resolve().parents[1] / "docs"


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_help_topic_resolves_to_local_file_url(tmp_path) -> None:
    docs_root = tmp_path / "docs_html"
    target = docs_root / "concepts" / "reference-di.html"
    target.parent.mkdir(parents=True)
    target.write_text("<html></html>", encoding="utf-8")

    url = gui_help.resolve_help_url(HelpId.REFERENCE_DI, docs_root=docs_root)

    assert url.isLocalFile()
    assert url.toLocalFile() == str(target)
    assert url.fragment() == "help-reference-di"


def test_help_topic_falls_back_to_github_docs_when_local_page_is_missing(tmp_path) -> None:
    url = gui_help.resolve_help_url(HelpId.REFERENCE_DI, docs_root=tmp_path)

    assert not url.isLocalFile()
    assert url.toString().startswith(f"{GITHUB_DOCS_URL}/concepts/reference-di.md")
    assert url.fragment() == "help-reference-di"


def test_unknown_help_topic_falls_back_to_docs_index(tmp_path) -> None:
    docs_root = tmp_path / "docs_html"
    index = docs_root / "index.html"
    docs_root.mkdir()
    index.write_text("<html></html>", encoding="utf-8")

    url = gui_help.resolve_help_url("missing_topic", docs_root=docs_root)

    assert url.isLocalFile()
    assert url.toLocalFile() == str(index)
    assert url.fragment() == ""


def test_local_docs_root_prefers_packaged_docs_when_frozen(tmp_path, monkeypatch) -> None:
    packaged_docs = tmp_path / "installed" / "docs_html"
    checkout_docs = tmp_path / "checkout" / "docs_html"
    packaged_docs.mkdir(parents=True)
    checkout_docs.mkdir(parents=True)
    (packaged_docs / "index.html").write_text("<html></html>", encoding="utf-8")
    (checkout_docs / "index.html").write_text("<html></html>", encoding="utf-8")
    executable = tmp_path / "installed" / "matchpatch-gui.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setattr(gui_help.sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui_help.sys, "executable", str(executable))
    monkeypatch.setattr(gui_help, "repo_root", lambda: tmp_path / "checkout")

    assert gui_help.local_docs_root() == packaged_docs


def test_local_docs_root_uses_checkout_docs_for_normal_python(tmp_path, monkeypatch) -> None:
    checkout_docs = tmp_path / "checkout" / "docs_html"
    checkout_docs.mkdir(parents=True)
    (checkout_docs / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(gui_help.sys, "frozen", False, raising=False)
    monkeypatch.setattr(gui_help, "repo_root", lambda: tmp_path / "checkout")

    assert gui_help.local_docs_root() == checkout_docs


def test_local_docs_root_returns_none_without_html_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(gui_help.sys, "frozen", False, raising=False)
    monkeypatch.setattr(gui_help, "repo_root", lambda: tmp_path)

    assert gui_help.local_docs_root() is None


def test_open_help_delegates_to_qdesktopservices(monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(gui_help, "_running_under_wsl", lambda: False)
    monkeypatch.setattr(gui_help, "local_docs_root", lambda: None)
    monkeypatch.setattr(
        gui_help.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url) or True,
    )

    assert gui_help.open_help(HelpId.QUICK_START)
    assert opened
    assert opened[0].toString().endswith("/quick-start.md")


def test_open_help_uses_wsl_launcher_before_qdesktopservices(monkeypatch) -> None:
    opened = []
    desktop_opened = []
    monkeypatch.setattr(gui_help, "_running_under_wsl", lambda: True)
    monkeypatch.setattr(gui_help, "resolve_help_url", lambda help_id: QUrl("https://example.test"))
    monkeypatch.setattr(
        gui_help,
        "_open_url_with_wsl_launcher",
        lambda url: opened.append(url.toString()) or True,
    )
    monkeypatch.setattr(
        gui_help.QDesktopServices,
        "openUrl",
        lambda url: desktop_opened.append(url.toString()) or True,
    )

    assert gui_help.open_help(HelpId.QUICK_START)
    assert opened == ["https://example.test"]
    assert desktop_opened == []


def test_open_help_falls_back_to_qdesktopservices_when_wsl_launcher_fails(monkeypatch) -> None:
    desktop_opened = []
    monkeypatch.setattr(gui_help, "_running_under_wsl", lambda: True)
    monkeypatch.setattr(gui_help, "resolve_help_url", lambda help_id: QUrl("https://example.test"))
    monkeypatch.setattr(gui_help, "_open_url_with_wsl_launcher", lambda url: False)
    monkeypatch.setattr(
        gui_help.QDesktopServices,
        "openUrl",
        lambda url: desktop_opened.append(url.toString()) or True,
    )

    assert gui_help.open_help(HelpId.QUICK_START)
    assert desktop_opened == ["https://example.test"]


def test_wsl_launcher_url_converts_local_file_path_and_preserves_anchor(monkeypatch) -> None:
    url = QUrl.fromLocalFile("/home/flo/MatchPatch/docs_html/index.html")
    url.setFragment("help-anchor")
    monkeypatch.setattr(
        gui_help,
        "_wslpath_to_windows",
        lambda path: r"\\wsl.localhost\Ubuntu-24.04\home\flo\MatchPatch\docs_html\index.html",
    )

    assert (
        gui_help._url_for_wsl_launcher(url)
        == r"\\wsl.localhost\Ubuntu-24.04\home\flo\MatchPatch\docs_html\index.html#help-anchor"
    )


def test_wsl_launcher_uses_cmd_when_wslview_is_unavailable(monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(
        gui_help.shutil,
        "which",
        lambda name: "cmd.exe" if name == "cmd.exe" else None,
    )

    class Result:
        returncode = 0

    def run_command(command, **kwargs):
        commands.append(command)
        return Result()

    monkeypatch.setattr(gui_help.subprocess, "run", run_command)

    assert gui_help._open_url_with_wsl_launcher(QUrl("https://example.test/docs"))
    assert commands == [["cmd.exe", "/d", "/c", "start", "", "https://example.test/docs"]]


def test_all_help_topics_use_html_pages() -> None:
    assert HELP_TOPICS
    for topic in HELP_TOPICS.values():
        assert topic.page.endswith(".html")


def test_all_help_id_constants_are_registered() -> None:
    help_ids = {
        value for name, value in vars(HelpId).items() if name.isupper() and isinstance(value, str)
    }

    assert help_ids == set(HELP_TOPICS)


def test_all_help_topics_target_existing_docs_pages_and_anchors() -> None:
    for topic in HELP_TOPICS.values():
        source_path = DOCS_ROOT / f"{topic.page.removesuffix('.html')}.md"

        assert source_path.is_file(), topic.page
        if topic.anchor is not None:
            assert f"({topic.anchor})=" in source_path.read_text(encoding="utf-8")


def test_main_window_assigns_stable_help_ids(app) -> None:
    window = MainWindow()

    assert window.help_action.property("help_id") == HelpId.DOCS_INDEX
    assert window.open_action.property("help_id") == HelpId.OPEN_FILES
    assert window.save_measurement_action.property("help_id") == HelpId.MEASUREMENT_FILE
    assert window.start_button.property("help_id") == HelpId.NORMALIZE_SETLIST
    assert window.cancel_button.property("help_id") == HelpId.PROGRESS_CANCEL
    assert window.reference_di.property("help_id") == HelpId.REFERENCE_DI
    assert window.determine_parameters_button.property("help_id") == HelpId.OPTIMIZE_TIMING
    assert window.manual_adjustments.property("help_id") == HelpId.MANUAL_EDITING
    assert window.save_csv_button.property("help_id") == HelpId.MANUAL_CSV
    assert window.load_csv_button.property("help_id") == HelpId.MANUAL_CSV
    assert window.preset_help_button.text() == ""
    assert window.advanced_help_button.text() == ""
    assert not window.preset_help_button.icon().isNull()
    assert not window.advanced_help_button.icon().isNull()
    assert window.preset_help_button.toolTip() == "Open help for presets"
    assert window.advanced_help_button.toolTip() == "Open help for current advanced tab"

    tab_help_ids = {
        window.advanced_tabs.tabText(index): window.advanced_tabs.tabBar().tabData(index)
        for index in range(window.advanced_tabs.count())
    }
    assert tab_help_ids == {
        "Device": HelpId.BACKENDS,
        "Files": HelpId.FILES_TAB,
        "Timing": HelpId.TIMING,
        "LUFS": HelpId.LUFS_LOUDNESS,
        "Misc": HelpId.SNAPSHOT_COUNT,
        "Meta Data": HelpId.METADATA,
        "Log": HelpId.TROUBLESHOOTING,
    }
    window.close()


def test_toolbar_help_opens_docs_index(monkeypatch, app) -> None:
    opened = []
    monkeypatch.setattr(gui_help, "open_help", lambda help_id: opened.append(help_id) or True)
    window = MainWindow()

    assert window.show_help()
    assert opened == [HelpId.DOCS_INDEX]
    window.close()


def test_f1_opens_focused_help_topic(monkeypatch, app) -> None:
    opened = []
    monkeypatch.setattr(gui_help, "open_help", lambda help_id: opened.append(help_id) or True)
    window = MainWindow()
    monkeypatch.setattr(main_window.QApplication, "focusWidget", lambda: window.reference_di)

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F1, Qt.KeyboardModifier.NoModifier)
    window.keyPressEvent(event)

    assert event.isAccepted()
    assert opened == [HelpId.REFERENCE_DI]
    window.close()


def test_f1_without_focused_help_topic_opens_quick_start(monkeypatch, app) -> None:
    opened = []
    monkeypatch.setattr(gui_help, "open_help", lambda help_id: opened.append(help_id) or True)
    window = MainWindow()
    window.setFocus()

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F1, Qt.KeyboardModifier.NoModifier)
    window.keyPressEvent(event)

    assert opened == [HelpId.QUICK_START]
    window.close()


def test_start_and_preset_help_route_by_loaded_file_type(app) -> None:
    window = MainWindow()

    assert window._help_id_for_widget(window.start_button) == HelpId.QUICK_START
    assert window._help_id_for_widget(window.preset_table) == HelpId.OPEN_FILES

    window.input_path.setText("/tmp/setlist.hls")
    window._loaded_input_path = window.input_path.text()
    assert window._help_id_for_widget(window.start_button) == HelpId.NORMALIZE_SETLIST
    assert window._help_id_for_widget(window.preset_table) == HelpId.NORMALIZE_SETLIST

    window.input_path.setText("/tmp/preset.hlx")
    window._loaded_input_path = window.input_path.text()
    assert window._help_id_for_widget(window.start_button) == HelpId.NORMALIZE_SINGLE_PRESET
    assert window._help_id_for_widget(window.preset_table) == HelpId.NORMALIZE_SINGLE_PRESET
    window.close()


def test_section_help_buttons_open_context_topics(monkeypatch, app) -> None:
    opened = []
    monkeypatch.setattr(gui_help, "open_help", lambda help_id: opened.append(help_id) or True)
    window = MainWindow()

    window.preset_help_button.click()
    window.advanced_tabs.setCurrentIndex(2)
    window.advanced_help_button.click()

    assert opened == [HelpId.OPEN_FILES, HelpId.TIMING]
    window.close()


def test_complex_dialogs_expose_help_ids(app) -> None:
    preset = MEASUREMENT_TIMING_PRESETS["Default"]
    settings = MeasurementOptimizationSettings(
        pre_roll=float(preset["pre_roll"]),
        post_roll=float(preset["post_roll"]),
        round_trip_latency=float(preset["round_trip_latency"]),
        preset_wait=float(preset["preset_wait"]),
        snapshot_wait=float(preset["snapshot_wait"]),
        measurement_wait=float(preset["measurement_wait"]),
        stability_runs=3,
        termination_tolerance=10.0,
        stability_tolerance=2.0,
    )

    setup_dialog = MeasurementOptimizationSetupDialog(settings, "01A Clean", 1)
    result_dialog = MeasurementOptimizationDialog(settings)

    assert setup_dialog.property("help_id") == HelpId.OPTIMIZE_TIMING
    assert result_dialog.property("help_id") == HelpId.OPTIMIZE_TIMING_RESULTS
