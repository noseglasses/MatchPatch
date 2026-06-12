from __future__ import annotations

import json
import platform
import shutil
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as ImageModule

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAYLOAD_ROOT = PROJECT_ROOT / "build" / "windows-payload" / "MatchPatch"
PYINSTALLER_WORK_ROOT = PROJECT_ROOT / "build" / "pyinstaller"
PYINSTALLER_ASSETS_ROOT = PYINSTALLER_WORK_ROOT / "installer-assets"
INSTALLER_ASSETS_ROOT = PAYLOAD_ROOT / "installer-assets"
ICON_SOURCE = PROJECT_ROOT / "docs" / "assets" / "matchmatch-icon-512.png"
LOGO_SOURCE = PROJECT_ROOT / "docs" / "assets" / "matchmatch-logo.png"
REFERENCE_DI_SOURCE = (
    PROJECT_ROOT / "audio" / "reference-di" / "DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav"
)
PAYLOAD_RUNTIME_FILES = [
    (PROJECT_ROOT / "Python" / "preset_handling.py", Path("Python") / "preset_handling.py"),
    (
        REFERENCE_DI_SOURCE,
        Path("audio") / "reference-di" / "DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav",
    ),
]


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
        (str(PROJECT_ROOT / "Python" / "preset_handling.py"), "Python"),
        (str(REFERENCE_DI_SOURCE), "audio/reference-di"),
        (str(PROJECT_ROOT / "docs" / "assets" / "matchmatch-icon.png"), "docs/assets"),
        (str(PROJECT_ROOT / "docs" / "assets" / "matchmatch-icon-512.png"), "docs/assets"),
        (str(PROJECT_ROOT / "docs" / "assets" / "matchmatch-logo.png"), "docs/assets"),
    ]


def prepare_pyinstaller_paths(workpath: Path, distpath: Path) -> None:
    workpath.mkdir(parents=True, exist_ok=True)
    distpath.mkdir(parents=True, exist_ok=True)


def _contained_rgba(
    image_module: ImageModule,
    source: Path,
    size: tuple[int, int],
    background: tuple[int, int, int, int],
) -> ImageModule.Image:
    image = image_module.open(source).convert("RGBA")
    image.thumbnail(size, image_module.Resampling.LANCZOS)
    canvas = image_module.new("RGBA", size, background)
    canvas.alpha_composite(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def prepare_installer_assets(target_root: Path = PYINSTALLER_ASSETS_ROOT) -> Path:
    from PIL import Image

    target_root.mkdir(parents=True, exist_ok=True)

    icon = _contained_rgba(Image, ICON_SOURCE, (256, 256), (0, 0, 0, 0))
    icon.save(
        target_root / "matchpatch.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    large = _contained_rgba(Image, LOGO_SOURCE, (164, 314), (255, 255, 255, 255)).convert("RGB")
    large.save(target_root / "wizard-logo.bmp")

    small = _contained_rgba(Image, ICON_SOURCE, (55, 55), (255, 255, 255, 255)).convert("RGB")
    small.save(target_root / "wizard-small-logo.bmp")

    return target_root


def stage_installer_assets(
    source_root: Path = PYINSTALLER_ASSETS_ROOT,
    payload_root: Path = PAYLOAD_ROOT,
) -> None:
    target_root = payload_root / "installer-assets"
    if target_root.exists():
        shutil.rmtree(target_root)
    shutil.copytree(source_root, target_root)


def stage_runtime_files(payload_root: Path = PAYLOAD_ROOT) -> None:
    for source, relative_target in PAYLOAD_RUNTIME_FILES:
        target = payload_root / relative_target
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


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
