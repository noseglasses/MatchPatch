from __future__ import annotations

import json
import platform
import shutil
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAYLOAD_ROOT = PROJECT_ROOT / "build" / "windows-payload" / "MatchPatch"
PYINSTALLER_WORK_ROOT = PROJECT_ROOT / "build" / "pyinstaller"


def project_version() -> str:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    return str(pyproject["project"]["version"])


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def asset_datas() -> list[tuple[str, str]]:
    return [
        (str(PROJECT_ROOT / "docs" / "assets" / "matchmatch-icon.png"), "docs/assets"),
        (str(PROJECT_ROOT / "docs" / "assets" / "matchmatch-icon-512.png"), "docs/assets"),
        (str(PROJECT_ROOT / "docs" / "assets" / "matchmatch-logo.png"), "docs/assets"),
    ]


def write_build_info(payload_root: Path = PAYLOAD_ROOT) -> None:
    payload_root.mkdir(parents=True, exist_ok=True)
    build_info = {
        "name": "matchpatch",
        "version": project_version(),
        "git_sha": git_sha(),
        "built_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "python": platform.python_version(),
        "builder": "pyinstaller",
    }
    (payload_root / "build-info.json").write_text(
        json.dumps(build_info, indent=2) + "\n",
        encoding="utf-8",
    )


def stage_docs(payload_root: Path = PAYLOAD_ROOT) -> None:
    docs_source = PROJECT_ROOT / "docs_html"
    docs_index = docs_source / "index.html"
    if not docs_index.exists():
        raise SystemExit(
            "Offline docs are missing. Build docs_html before running the GUI PyInstaller spec."
        )

    docs_target = payload_root / "docs_html"
    if docs_target.exists():
        shutil.rmtree(docs_target)
    shutil.copytree(docs_source, docs_target)
