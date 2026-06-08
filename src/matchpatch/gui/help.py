"""Offline help topic IDs and URL resolution for the MatchPatch GUI."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

GITHUB_DOCS_URL = "https://github.com/noseglasses/MatchPatch/tree/main/docs"


class HelpId:
    DOCS_INDEX = "docs_index"
    QUICK_START = "quick_start"
    OPEN_FILES = "open_files"
    SAVE_IMPORT = "save_import"
    MEASUREMENT_FILE = "measurement_file"
    NORMALIZE_SETLIST = "normalize_setlist"
    NORMALIZE_SINGLE_PRESET = "normalize_single_preset"
    PROGRESS_CANCEL = "progress_cancel"
    RECORDED_OUTPUT = "recorded_output"
    ADVANCED_SETTINGS = "advanced_settings"
    SELECT_PRESETS = "select_presets"
    SELECT_CHANGED = "select_changed"
    MANUAL_EDITING = "manual_editing"
    MANUAL_CSV = "manual_csv"
    SNAPSHOTS_SOLOS_IGNORED = "snapshots_solos_ignored"
    READING_RESULTS = "reading_results"
    BACKENDS = "backends"
    ROUTING_LEVELS = "routing_levels"
    HARDWARE_MEASUREMENT = "hardware_measurement"
    FILES_TAB = "files_tab"
    REFERENCE_DI = "reference_di"
    CUSTOM_ADJUSTMENTS = "custom_adjustments"
    TIMING = "timing"
    OPTIMIZE_TIMING = "optimize_timing"
    LUFS_LOUDNESS = "lufs_loudness"
    SNAPSHOT_COUNT = "snapshot_count"
    METADATA = "metadata"
    TROUBLESHOOTING = "troubleshooting"
    HARDWARE_TROUBLESHOOTING = "hardware_troubleshooting"
    OPTIMIZE_TIMING_RESULTS = "optimize_timing_results"


@dataclass(frozen=True)
class HelpTopic:
    page: str
    anchor: str | None = None


HELP_TOPICS: dict[str, HelpTopic] = {
    HelpId.DOCS_INDEX: HelpTopic("index.html"),
    HelpId.QUICK_START: HelpTopic("quick-start.html"),
    HelpId.OPEN_FILES: HelpTopic("musician-guide.html", "help-opening-files"),
    HelpId.SAVE_IMPORT: HelpTopic("workflows/save-and-import.html"),
    HelpId.MEASUREMENT_FILE: HelpTopic(
        "concepts/measurement-and-adjusted-files.html",
        "help-measurement-file",
    ),
    HelpId.NORMALIZE_SETLIST: HelpTopic("workflows/normalize-setlist.html"),
    HelpId.NORMALIZE_SINGLE_PRESET: HelpTopic("workflows/normalize-single-preset.html"),
    HelpId.PROGRESS_CANCEL: HelpTopic("concepts/reading-results.html", "help-progress-and-cancel"),
    HelpId.RECORDED_OUTPUT: HelpTopic(
        "workflows/hardware-measurement.html",
        "help-recorded-output-playback",
    ),
    HelpId.ADVANCED_SETTINGS: HelpTopic("musician-guide.html", "help-advanced-settings"),
    HelpId.SELECT_PRESETS: HelpTopic("workflows/normalize-setlist.html", "help-select-presets"),
    HelpId.SELECT_CHANGED: HelpTopic("workflows/select-changed-presets.html"),
    HelpId.MANUAL_EDITING: HelpTopic(
        "workflows/manual-editing-and-csv.html",
        "help-manual-editing",
    ),
    HelpId.MANUAL_CSV: HelpTopic("workflows/manual-editing-and-csv.html", "help-csv"),
    HelpId.SNAPSHOTS_SOLOS_IGNORED: HelpTopic("concepts/snapshots-solos-and-ignored.html"),
    HelpId.READING_RESULTS: HelpTopic("concepts/reading-results.html"),
    HelpId.BACKENDS: HelpTopic("concepts/backends.html"),
    HelpId.ROUTING_LEVELS: HelpTopic("concepts/routing-and-levels.html", "help-audio-routing"),
    HelpId.HARDWARE_MEASUREMENT: HelpTopic("workflows/hardware-measurement.html"),
    HelpId.FILES_TAB: HelpTopic("concepts/measurement-and-adjusted-files.html"),
    HelpId.REFERENCE_DI: HelpTopic("concepts/reference-di.html", "help-reference-di"),
    HelpId.CUSTOM_ADJUSTMENTS: HelpTopic("workflows/custom-adjustments.html"),
    HelpId.TIMING: HelpTopic("concepts/timing.html"),
    HelpId.OPTIMIZE_TIMING: HelpTopic("workflows/optimize-timing.html"),
    HelpId.LUFS_LOUDNESS: HelpTopic("concepts/lufs-and-loudness.html"),
    HelpId.SNAPSHOT_COUNT: HelpTopic(
        "concepts/snapshots-solos-and-ignored.html",
        "help-snapshot-count",
    ),
    HelpId.METADATA: HelpTopic("musician-guide.html", "help-metadata"),
    HelpId.TROUBLESHOOTING: HelpTopic("troubleshooting.html"),
    HelpId.HARDWARE_TROUBLESHOOTING: HelpTopic("troubleshooting.html", "help-hardware-not-found"),
    HelpId.OPTIMIZE_TIMING_RESULTS: HelpTopic(
        "workflows/optimize-timing.html",
        "help-apply-optimized-timing",
    ),
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _docs_root_if_available(path: Path) -> Path | None:
    if (path / "index.html").is_file():
        return path
    return None


def local_docs_root() -> Path | None:
    if getattr(sys, "frozen", False):
        executable = getattr(sys, "executable", "")
        if executable:
            if packaged_docs := _docs_root_if_available(
                Path(executable).resolve().parent / "docs_html"
            ):
                return packaged_docs

    if checkout_docs := _docs_root_if_available(repo_root() / "docs_html"):
        return checkout_docs

    return None


def resolve_help_url(help_id: str, *, docs_root: Path | None = None) -> QUrl:
    topic = HELP_TOPICS.get(help_id, HELP_TOPICS[HelpId.DOCS_INDEX])
    if docs_root is None:
        docs_root = local_docs_root()

    if docs_root is not None:
        target = docs_root / topic.page
        if target.is_file():
            url = QUrl.fromLocalFile(str(target))
            if topic.anchor:
                url.setFragment(topic.anchor)
            return url

    source_page = topic.page.removesuffix(".html") + ".md"
    url = QUrl(f"{GITHUB_DOCS_URL}/{source_page}")
    if topic.anchor:
        url.setFragment(topic.anchor)
    return url


def _running_under_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        version = Path("/proc/version").read_text(encoding="utf-8").casefold()
    except OSError:
        return False
    return "microsoft" in version or "wsl" in version


def _wslpath_to_windows(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["wslpath", "-w", str(path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _url_for_wsl_launcher(url: QUrl) -> str:
    if not url.isLocalFile():
        return url.toString()

    launcher_url = _wslpath_to_windows(Path(url.toLocalFile())) or url.toLocalFile()
    if fragment := url.fragment():
        launcher_url = f"{launcher_url}#{fragment}"
    return launcher_url


def _open_url_with_wsl_launcher(url: QUrl) -> bool:
    launcher_url = _url_for_wsl_launcher(url)
    commands = []
    if wslview := shutil.which("wslview"):
        commands.append([wslview, launcher_url])
    if shutil.which("cmd.exe"):
        commands.append(["cmd.exe", "/d", "/c", "start", "", launcher_url])

    for command in commands:
        try:
            result = subprocess.run(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            continue
        if result.returncode == 0:
            return True
    return False


def open_help(help_id: str = HelpId.DOCS_INDEX) -> bool:
    url = resolve_help_url(help_id)
    if _running_under_wsl() and _open_url_with_wsl_launcher(url):
        return True
    return QDesktopServices.openUrl(url)
