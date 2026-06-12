from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

from packaging.version import Version

import matchpatch

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_project_version_is_valid_and_matches_package_metadata() -> None:
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    with pyproject_path.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    project_version = pyproject["project"]["version"]

    assert isinstance(project_version, str)
    Version(project_version)
    assert matchpatch.__version__ == project_version


def test_inno_setup_script_uses_build_defines_and_expected_payload_files() -> None:
    inno_script = (PROJECT_ROOT / "installer" / "matchpatch.iss").read_text(encoding="utf-8")
    project_version = _project_version()

    assert "#ifndef AppVersion" in inno_script
    assert "#ifndef SourceDir" in inno_script
    assert "#ifndef OutputDir" in inno_script
    assert "AppVersion={#AppVersion}" in inno_script
    assert "OutputDir={#OutputDir}" in inno_script
    assert "OutputBaseFilename=MatchPatch-Setup-{#AppVersion}" in inno_script
    assert '#define UninstallerExeName "Uninstall-MatchPatch.exe"' in inno_script
    assert 'Filename: "{app}\\{#UninstallerExeName}"' in inno_script
    assert "RenameUninstallerFile('unins000.exe', UninstallerExeName)" in inno_script
    assert "'UninstallString'" in inno_script
    assert "'QuietUninstallString'" in inno_script
    assert r"SetupIconFile={#SourceDir}\installer-assets\matchpatch.ico" in inno_script
    assert r"WizardImageFile={#SourceDir}\installer-assets\wizard-logo.bmp" in inno_script
    assert (
        r"WizardSmallImageFile={#SourceDir}\installer-assets\wizard-small-logo.bmp" in inno_script
    )
    assert 'Source: "{#SourceDir}\\*"' in inno_script
    assert r"MatchPatch.exe" in inno_script
    assert r'IconFilename: "{app}\installer-assets\matchpatch.ico"' in inno_script
    assert r"docs_html\index.html" in inno_script
    directives = {line.strip() for line in inno_script.splitlines()}
    assert f"AppVersion={project_version}" not in directives
    assert f"OutputBaseFilename=MatchPatch-Setup-{project_version}" not in directives


def test_windows_installer_scripts_use_windows_environment_and_no_stale_venv() -> None:
    script_paths = [
        PROJECT_ROOT / "scripts" / "build-windows-payload.cmd",
        PROJECT_ROOT / "scripts" / "build-windows-installer.cmd",
        PROJECT_ROOT / "scripts" / "test-windows-installer.cmd",
        PROJECT_ROOT / "installer" / "smoke" / "smoke_payload.ps1",
        PROJECT_ROOT / "installer" / "smoke" / "smoke_installed.ps1",
    ]
    scripts = {path.name: path.read_text(encoding="utf-8") for path in script_paths}
    combined = "\n".join(scripts.values())

    assert 'set "UV_PROJECT_ENVIRONMENT=.venv-windows"' in scripts["build-windows-payload.cmd"]
    assert 'set "UV_LINK_MODE=copy"' in scripts["build-windows-payload.cmd"]
    assert "build\\windows-payload\\MatchPatch" in combined
    assert "MatchPatch-Setup-%APP_VERSION%.exe" in combined
    assert "MatchPatch.exe --cli --version" in combined
    assert "Start-Process -FilePath $GuiExe" in combined
    assert 'Join-Path $InstallDir "Uninstall-MatchPatch.exe"' in combined
    assert "unins000.exe" not in combined
    assert "build-info.json version" in combined
    assert "installer-assets\\matchpatch.ico" in combined
    assert "installer-assets\\wizard-logo.bmp" in combined
    assert "installer-assets\\wizard-small-logo.bmp" in combined
    assert "audio\\reference-di\\DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav" in combined
    assert "installer\\smoke\\smoke_payload.ps1" in scripts["test-windows-installer.cmd"]
    assert "installer\\smoke\\smoke_installed.ps1" in scripts["test-windows-installer.cmd"]
    assert "matchpatch.exe" not in combined
    assert not re.search(r"(?<![\w.-])\.venv(?!-[\w.-])", combined)


def test_installer_dependency_group_supports_png_icon_conversion() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    installer_dependencies = pyproject["dependency-groups"]["installer"]

    assert any(dependency.startswith("pillow") for dependency in installer_dependencies)


def test_pyinstaller_specs_include_payload_metadata_docs_and_assets() -> None:
    gui_spec = (PROJECT_ROOT / "installer" / "pyinstaller" / "matchpatch-gui.spec").read_text(
        encoding="utf-8"
    )
    build_support = (PROJECT_ROOT / "installer" / "pyinstaller" / "build_support.py").read_text(
        encoding="utf-8"
    )

    assert 'name="MatchPatch"' in gui_spec
    assert "console=False" in gui_spec
    assert "datas=asset_datas()" in gui_spec
    assert '"src" / "matchpatch" / "app.py"' in gui_spec
    assert "prepare_installer_assets()" in gui_spec
    assert 'prepare_pyinstaller_paths(Path(CONF["workpath"]), Path(CONF["distpath"]))' in gui_spec
    assert "stage_installer_assets()" in gui_spec
    assert "stage_runtime_files()" in gui_spec
    assert "stage_docs()" in gui_spec
    assert "write_build_info()" in gui_spec

    assert "PAYLOAD_RUNTIME_FILES" in build_support
    assert '"Python" / "preset_handling.py"' in build_support
    assert '"audio" / "reference-di"' in build_support
    assert "DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav" in build_support
    assert '"docs_html"' in build_support
    assert '"build-info.json"' in build_support
    assert '"builder": "pyinstaller"' in build_support
    assert "def prepare_pyinstaller_paths" in build_support
    assert "def prepare_installer_assets" in build_support
    assert "def stage_installer_assets" in build_support
    assert "def stage_runtime_files" in build_support
    assert "matchpatch.ico" in build_support
    assert "wizard-logo.bmp" in build_support
    assert "wizard-small-logo.bmp" in build_support
    assert "matchmatch-icon.png" in build_support
    assert "matchmatch-icon-512.png" in build_support
    assert "matchmatch-logo.png" in build_support


def test_prepare_pyinstaller_paths_creates_missing_build_dirs(tmp_path: Path) -> None:
    build_support = _load_build_support()
    workpath = tmp_path / "build" / "pyinstaller" / "gui"
    distpath = tmp_path / "build" / "windows-payload"

    build_support.prepare_pyinstaller_paths(workpath, distpath)

    assert workpath.is_dir()
    assert distpath.is_dir()
    assert not (distpath / "MatchPatch").exists()


def test_installer_assets_are_prepared_outside_payload_then_staged(tmp_path: Path) -> None:
    build_support = _load_build_support()
    scratch_assets = tmp_path / "build" / "pyinstaller" / "installer-assets"
    payload_root = tmp_path / "build" / "windows-payload" / "MatchPatch"
    scratch_assets.mkdir(parents=True)

    for asset_name in ("matchpatch.ico", "wizard-logo.bmp", "wizard-small-logo.bmp"):
        (scratch_assets / asset_name).write_bytes(b"asset")

    assert build_support.prepare_installer_assets.__defaults__ == (
        build_support.PYINSTALLER_ASSETS_ROOT,
    )
    assert build_support.PYINSTALLER_ASSETS_ROOT != build_support.INSTALLER_ASSETS_ROOT
    assert not build_support.PYINSTALLER_ASSETS_ROOT.is_relative_to(build_support.PAYLOAD_ROOT)
    assert not payload_root.exists()

    build_support.stage_installer_assets(scratch_assets, payload_root)

    assert (payload_root / "installer-assets" / "matchpatch.ico").is_file()


def test_runtime_files_are_staged_at_payload_root(tmp_path: Path) -> None:
    build_support = _load_build_support()
    payload_root = tmp_path / "build" / "windows-payload" / "MatchPatch"

    build_support.stage_runtime_files(payload_root)

    assert (payload_root / "Python" / "preset_handling.py").is_file()
    assert (
        payload_root / "audio" / "reference-di" / "DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav"
    ).is_file()


def test_release_workflow_publishes_windows_installer() -> None:
    release_workflow = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "windows-installer:" in release_workflow
    assert "runs-on: windows-latest" in release_workflow
    assert "contents: write" in release_workflow
    assert "scripts\\test-windows-installer.cmd" in release_workflow
    assert "MatchPatch-Setup-$version.exe" in release_workflow
    assert "actions/upload-artifact@v4" in release_workflow
    assert "gh release create $tag" in release_workflow
    assert "gh release upload $tag $installer --clobber" in release_workflow
    assert release_workflow.count("GITHUB_REF_NAME") >= 2
    assert release_workflow.count("pyproject.toml") >= 2


def _project_version() -> str:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    return str(pyproject["project"]["version"])


def _load_build_support():
    support_path = PROJECT_ROOT / "installer" / "pyinstaller" / "build_support.py"
    spec = importlib.util.spec_from_file_location(
        "matchpatch_installer_build_support", support_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
