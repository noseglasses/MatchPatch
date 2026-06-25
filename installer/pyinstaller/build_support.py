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
WINDOWS_PAYLOAD_ROOT = PROJECT_ROOT / "build" / "windows-payload" / "MatchPatch"
MACOS_PAYLOAD_ROOT = PROJECT_ROOT / "build" / "macos-payload" / "MatchPatch.app"
MACOS_CONTENTS_ROOT = MACOS_PAYLOAD_ROOT / "Contents"
MACOS_EXECUTABLE_ROOT = MACOS_CONTENTS_ROOT / "MacOS"
PAYLOAD_ROOT = WINDOWS_PAYLOAD_ROOT
DIST_INSTALLER_ROOT = PROJECT_ROOT / "dist" / "installer"
PYINSTALLER_WORK_ROOT = PROJECT_ROOT / "build" / "pyinstaller"
PYINSTALLER_ASSETS_ROOT = PYINSTALLER_WORK_ROOT / "installer-assets"
INSTALLER_ASSETS_ROOT = PAYLOAD_ROOT / "installer-assets"
ICON_SOURCE = PROJECT_ROOT / "docs" / "assets" / "matchmatch-icon-512.png"
LOGO_SOURCE = PROJECT_ROOT / "docs" / "assets" / "matchmatch-logo.png"
REFERENCE_DI_SOURCE = (
    PROJECT_ROOT / "audio" / "reference-di" / "DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav"
)
PAYLOAD_RUNTIME_FILES = [
    (
        REFERENCE_DI_SOURCE,
        Path("audio") / "reference-di" / "DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav",
    ),
]
WINDOWS_INSTALLER_ARTIFACT_NAME = "MatchPatch-Setup-{version}.exe"
MACOS_INSTALLER_ARTIFACT_NAME = "MatchPatch-macOS-{arch}-{version}.dmg"
MACOS_BUNDLE_IDENTIFIER = "io.github.noseglasses.matchpatch"


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


def payload_root_for(platform_name: str) -> Path:
    if platform_name == "windows":
        return WINDOWS_PAYLOAD_ROOT
    if platform_name == "macos":
        return MACOS_PAYLOAD_ROOT
    raise ValueError(f"Unsupported platform name: {platform_name!r}")


def installer_artifact_name(
    platform_name: str,
    version: str,
    arch: str | None = None,
) -> str:
    if platform_name == "windows":
        return WINDOWS_INSTALLER_ARTIFACT_NAME.format(version=version)
    if platform_name == "macos":
        if not arch:
            raise ValueError("macos installer artifacts require an architecture name")
        return MACOS_INSTALLER_ARTIFACT_NAME.format(arch=arch, version=version)
    raise ValueError(f"Unsupported platform name: {platform_name!r}")


def installer_artifact_path(
    platform_name: str,
    version: str,
    arch: str | None = None,
    output_root: Path = DIST_INSTALLER_ROOT,
) -> Path:
    return output_root / installer_artifact_name(platform_name, version, arch=arch)


def macos_info_plist() -> dict[str, str | bool]:
    return {
        "CFBundleDisplayName": "MatchPatch",
        "CFBundleExecutable": "MatchPatch",
        "CFBundleIdentifier": MACOS_BUNDLE_IDENTIFIER,
        "CFBundleName": "MatchPatch",
        "CFBundleShortVersionString": project_version(),
        "CFBundleVersion": project_version(),
        "NSHighResolutionCapable": True,
    }


def asset_datas() -> list[tuple[str, str]]:
    return [
        (str(REFERENCE_DI_SOURCE), "audio/reference-di"),
        (str(PROJECT_ROOT / "docs" / "assets" / "matchmatch-icon.png"), "docs/assets"),
        (str(PROJECT_ROOT / "docs" / "assets" / "matchmatch-icon-512.png"), "docs/assets"),
        (str(PROJECT_ROOT / "docs" / "assets" / "matchmatch-logo.png"), "docs/assets"),
    ]


def payload_runtime_root(payload_root: Path = PAYLOAD_ROOT) -> Path:
    if payload_root.suffix == ".app":
        return payload_root / "Contents" / "MacOS"
    return payload_root


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


def prepare_macos_icon(target_root: Path = PYINSTALLER_ASSETS_ROOT) -> Path:
    from PIL import Image

    target_root.mkdir(parents=True, exist_ok=True)
    if shutil.which("iconutil") is None:
        raise SystemExit("macOS app builds require the 'iconutil' tool to create matchpatch.icns")
    iconset_root = target_root / "matchpatch.iconset"
    if iconset_root.exists():
        shutil.rmtree(iconset_root)
    iconset_root.mkdir()

    icon_sizes = (16, 32, 128, 256, 512)
    for size in icon_sizes:
        _contained_rgba(Image, ICON_SOURCE, (size, size), (0, 0, 0, 0)).save(
            iconset_root / f"icon_{size}x{size}.png"
        )
        _contained_rgba(Image, ICON_SOURCE, (size * 2, size * 2), (0, 0, 0, 0)).save(
            iconset_root / f"icon_{size}x{size}@2x.png"
        )

    icon_path = target_root / "matchpatch.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_root), "-o", str(icon_path)],
        check=True,
        cwd=PROJECT_ROOT,
    )
    return icon_path


def stage_installer_assets(
    source_root: Path = PYINSTALLER_ASSETS_ROOT,
    payload_root: Path = PAYLOAD_ROOT,
) -> None:
    target_root = payload_root / "installer-assets"
    if target_root.exists():
        shutil.rmtree(target_root)
    shutil.copytree(source_root, target_root)


def stage_runtime_files(payload_root: Path = PAYLOAD_ROOT) -> None:
    payload_root = payload_runtime_root(payload_root)
    for source, relative_target in PAYLOAD_RUNTIME_FILES:
        target = payload_root / relative_target
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def write_build_info(payload_root: Path = PAYLOAD_ROOT) -> None:
    payload_root = payload_runtime_root(payload_root)
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
    payload_root = payload_runtime_root(payload_root)
    docs_source = PROJECT_ROOT / "docs_html"
    docs_index = docs_source / "index.html"
    if not docs_index.exists():
        raise SystemExit(
            "Offline docs are missing. Build docs_html before running the GUI PyInstaller spec."
        )

    docs_target = payload_root / "docs_html"
    if docs_target.exists():
        shutil.rmtree(docs_target)
    shutil.copytree(docs_source, docs_target, ignore=shutil.ignore_patterns(".doctrees"))
