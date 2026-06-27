from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
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


def test_macos_hardware_validation_script_and_workflow_cover_expected_failure_and_self_hosted_paths() -> (
    None
):
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "scripts" / "test-macos-hardware.sh").read_text(encoding="utf-8")

    assert "macos-hardware:" in workflow
    assert "macos-hardware-self-hosted:" in workflow
    assert "runs-on: macos-latest" in workflow
    assert "runs-on: [self-hosted, macOS, line6-hardware]" in workflow
    assert "MATCHPATCH_MACOS_HARDWARE" in workflow
    assert "run: bash scripts/test-macos-hardware.sh" in workflow
    assert "matchpatch-macos-hardware-validation" in workflow
    assert "matchpatch-macos-hardware-self-hosted" in workflow

    assert "uv sync --locked --no-default-groups --extra hardware" in script
    assert "import mido; import mido.backends.rtmidi; import rtmidi; import sounddevice" in script
    assert "python -m matchpatch.measure devices" in script
    assert "validate_device helix" in script
    assert "validate_device podgo" in script
    assert "--diagnostics-json" in script
    assert "build/macos-hardware" in script
    assert "MATCHPATCH_MACOS_HARDWARE" in script
    assert "expected audio_device to fail without hardware" in script
    assert "expected midi_output to pass with hardware" in script


def test_quality_workflow_includes_macos_installer_smoke_job() -> None:
    quality_workflow = (PROJECT_ROOT / ".github" / "workflows" / "quality.yml").read_text(
        encoding="utf-8"
    )

    assert "macos-installer:" in quality_workflow
    assert "name: macOS installer smoke / arm64" in quality_workflow
    assert "runs-on: macos-15" in quality_workflow
    assert (
        "uv sync --locked --no-default-groups --group docs --group installer --extra gui --extra hardware"
        in quality_workflow
    )
    assert "run: bash scripts/build-macos-dmg.sh" in quality_workflow
    assert "run: bash installer/smoke/smoke_macos_dmg.sh --reuse-artifact" in quality_workflow
    assert "matchpatch-macos-installer-smoke" in quality_workflow
    assert "MatchPatch-macOS-*-*.dmg" in quality_workflow
    assert "matchpatch-installer-smoke" in quality_workflow


def test_quality_workflow_includes_macos_pypi_install_smoke_job() -> None:
    quality_workflow = (PROJECT_ROOT / ".github" / "workflows" / "quality.yml").read_text(
        encoding="utf-8"
    )

    assert "macos-pypi:" in quality_workflow
    assert "name: macOS PyPI install smoke / Python 3.12" in quality_workflow
    assert "runs-on: macos-latest" in quality_workflow
    assert "uv build --no-sources --wheel" in quality_workflow
    assert 'python -m pip install "${wheel[0]}[gui,hardware]"' in quality_workflow
    assert "matchpatch-gui --version" in quality_workflow
    assert "macOS PyPI install smoke OK" in quality_workflow


def test_macos_installer_scripts_do_not_require_executable_bits() -> None:
    quality_workflow = (PROJECT_ROOT / ".github" / "workflows" / "quality.yml").read_text(
        encoding="utf-8"
    )
    release_workflow = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    build_dmg_script = (PROJECT_ROOT / "scripts" / "build-macos-dmg.sh").read_text(encoding="utf-8")
    smoke_dmg_script = (PROJECT_ROOT / "installer" / "smoke" / "smoke_macos_dmg.sh").read_text(
        encoding="utf-8"
    )

    assert "run: bash scripts/test-macos-hardware.sh" in quality_workflow
    assert "run: bash scripts/build-macos-dmg.sh" in quality_workflow
    assert "run: bash installer/smoke/smoke_macos_dmg.sh --reuse-artifact" in quality_workflow
    assert "run: bash scripts/build-macos-dmg.sh" in release_workflow
    assert (
        'run: bash installer/smoke/smoke_macos_dmg.sh --dmg "${{ steps.version.outputs.installer }}"'
        in release_workflow
    )
    assert "bash scripts/build-macos-app.sh" in build_dmg_script
    assert "bash scripts/build-macos-dmg.sh" in smoke_dmg_script
    assert "bash installer/smoke/smoke_macos_payload.sh" in smoke_dmg_script


def test_macos_hardware_docs_describe_device_listing_and_mapping_capture() -> None:
    commands_doc = (PROJECT_ROOT / "docs" / "dev" / "commands.md").read_text(encoding="utf-8")
    workflow_doc = (PROJECT_ROOT / "docs" / "workflows" / "hardware-measurement.md").read_text(
        encoding="utf-8"
    )

    assert "scripts/test-macos-hardware.sh" in commands_doc
    assert "MATCHPATCH_MACOS_HARDWARE=1" in commands_doc
    assert "Audio devices:" in commands_doc
    assert "MIDI outputs:" in commands_doc
    assert "audio_device.detail.input_mapping" in commands_doc
    assert "midi_output.detail.output" in commands_doc
    assert "scripts/test-macos-hardware.sh" in workflow_doc
    assert "Core Audio" in workflow_doc
    assert "CoreMIDI" in workflow_doc
    assert "audio_device.detail.output_mapping" in workflow_doc
    assert "midi_output.detail.channel" in workflow_doc


def test_release_docs_mention_both_windows_and_macos_installers() -> None:
    release_doc = (PROJECT_ROOT / "docs" / "dev" / "release.md").read_text(encoding="utf-8")

    assert "Windows installer and macOS DMG" in release_doc
    assert "MatchPatch-Setup-0.8.1.exe" in release_doc
    assert "MatchPatch-macOS-arm64-0.8.1.dmg" in release_doc
    assert "Windows machine and an arm64 macOS machine" in release_doc
    assert "dist/installer/MatchPatch-macOS-arm64-0.8.1.dmg" in release_doc


def test_installer_dependency_group_supports_png_icon_conversion() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    installer_dependencies = pyproject["dependency-groups"]["installer"]

    assert any(dependency.startswith("pillow") for dependency in installer_dependencies)


def test_pypi_metadata_declares_runtime_dependencies() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    project_dependencies = pyproject["project"]["dependencies"]
    optional_dependencies = pyproject["project"]["optional-dependencies"]

    assert any(dependency.startswith("numpy") for dependency in project_dependencies)
    assert any(dependency.startswith("pyloudnorm") for dependency in project_dependencies)
    assert any(dependency.startswith("soundfile") for dependency in project_dependencies)
    assert any(dependency.startswith("PySide6") for dependency in optional_dependencies["gui"])
    assert any(dependency.startswith("mido") for dependency in optional_dependencies["hardware"])
    assert any(
        dependency.startswith("sounddevice") for dependency in optional_dependencies["hardware"]
    )


def test_pypi_build_metadata_packages_runtime_resources_for_installed_macos_use() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    wheel_target = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    force_include = wheel_target["force-include"]
    sdist_include = pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    reference_di = "audio/reference-di/DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav"

    assert wheel_target["packages"] == ["src/matchpatch"]
    assert force_include[reference_di] == (
        "matchpatch/_resources/audio/reference-di/DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav"
    )
    assert force_include["docs/assets/matchmatch-icon.png"] == (
        "matchpatch/_resources/docs/assets/matchmatch-icon.png"
    )
    assert f"/{reference_di}" in sdist_include
    assert "/docs/assets/matchmatch-icon.png" in sdist_include


def test_hardware_metadata_includes_darwin_dependency_markers() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    with (PROJECT_ROOT / "uv.lock").open("rb") as lock_file:
        lock = tomllib.load(lock_file)

    hardware_dependencies = pyproject["project"]["optional-dependencies"]["hardware"]
    windows_dependencies = pyproject["dependency-groups"]["windows"]
    lock_package = _lock_package(lock, "matchpatch")

    assert _requirement_markers(hardware_dependencies, "python-rtmidi") == {
        "sys_platform == 'darwin' or sys_platform == 'win32'"
    }
    assert _requirement_markers(hardware_dependencies, "sounddevice") == {
        "sys_platform == 'darwin' or sys_platform == 'win32'"
    }
    assert _requirement_markers(windows_dependencies, "python-rtmidi") == {
        "sys_platform == 'darwin' or sys_platform == 'win32'"
    }
    assert _requirement_markers(windows_dependencies, "sounddevice") == {
        "sys_platform == 'darwin' or sys_platform == 'win32'"
    }
    assert _lock_dependency_markers(
        lock_package["optional-dependencies"]["hardware"], "python-rtmidi"
    ) == {"sys_platform == 'darwin' or sys_platform == 'win32'"}
    assert _lock_dependency_markers(
        lock_package["optional-dependencies"]["hardware"], "sounddevice"
    ) == {"sys_platform == 'darwin' or sys_platform == 'win32'"}
    assert _lock_requires_dist_supports_hardware(lock_package, "python-rtmidi")
    assert _lock_requires_dist_supports_hardware(lock_package, "sounddevice")


def test_pyinstaller_specs_include_payload_metadata_docs_and_assets() -> None:
    gui_spec = (PROJECT_ROOT / "installer" / "pyinstaller" / "matchpatch-gui.spec").read_text(
        encoding="utf-8"
    )
    macos_spec = (PROJECT_ROOT / "installer" / "pyinstaller" / "matchpatch-macos.spec").read_text(
        encoding="utf-8"
    )
    build_support = (PROJECT_ROOT / "installer" / "pyinstaller" / "build_support.py").read_text(
        encoding="utf-8"
    )

    assert 'name="MatchPatch"' in gui_spec
    assert "console=False" in gui_spec
    assert "datas=asset_datas()" in gui_spec
    assert '"matchpatch.devices.helix.preset_handling"' in gui_spec
    assert '"matchpatch.devices.line6.podgo.preset_handling"' in gui_spec
    assert '"mido.backends.rtmidi"' in gui_spec
    assert '"rtmidi"' in gui_spec
    assert '"src" / "matchpatch" / "app.py"' in gui_spec
    assert "prepare_installer_assets()" in gui_spec
    assert 'prepare_pyinstaller_paths(Path(CONF["workpath"]), Path(CONF["distpath"]))' in gui_spec
    assert "stage_installer_assets()" in gui_spec
    assert "stage_runtime_files()" in gui_spec
    assert "stage_docs()" in gui_spec
    assert "write_build_info()" in gui_spec
    assert "PAYLOAD_RUNTIME_FILES" in build_support
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
    assert 'name="MatchPatch.app"' in macos_spec
    assert "prepare_macos_icon()" in macos_spec
    assert "macos_info_plist()" in macos_spec
    assert "bundle_identifier=MACOS_BUNDLE_IDENTIFIER" in macos_spec
    assert "payload_runtime_root(MACOS_PAYLOAD_ROOT).mkdir" in macos_spec
    assert "stage_runtime_files(MACOS_PAYLOAD_ROOT)" in macos_spec
    assert "stage_docs(MACOS_PAYLOAD_ROOT)" in macos_spec
    assert "write_build_info(MACOS_PAYLOAD_ROOT)" in macos_spec
    assert "MACOS_CONTENTS_ROOT" in build_support
    assert "MACOS_EXECUTABLE_ROOT" in build_support
    assert "matchpatch.icns" in build_support
    assert "matchpatch.iconset" in build_support
    assert '["iconutil", "-c", "icns"' in build_support
    assert "def payload_runtime_root" in build_support
    assert "def macos_info_plist" in build_support
    assert "CFBundleIdentifier" in build_support
    assert "CFBundleShortVersionString" in build_support


def test_build_support_exposes_windows_and_macos_payload_paths_and_artifacts() -> None:
    build_support = _load_build_support()
    project_version = _project_version()

    assert build_support.PAYLOAD_ROOT == build_support.WINDOWS_PAYLOAD_ROOT
    assert build_support.PAYLOAD_ROOT == build_support.payload_root_for("windows")
    assert build_support.MACOS_PAYLOAD_ROOT == (
        PROJECT_ROOT / "build" / "macos-payload" / "MatchPatch.app"
    )
    assert build_support.MACOS_CONTENTS_ROOT == build_support.MACOS_PAYLOAD_ROOT / "Contents"
    assert build_support.MACOS_EXECUTABLE_ROOT == build_support.MACOS_CONTENTS_ROOT / "MacOS"
    assert build_support.payload_root_for("macos") == build_support.MACOS_PAYLOAD_ROOT
    assert (
        build_support.payload_runtime_root(build_support.PAYLOAD_ROOT) == build_support.PAYLOAD_ROOT
    )
    assert build_support.payload_runtime_root(build_support.MACOS_PAYLOAD_ROOT) == (
        build_support.MACOS_EXECUTABLE_ROOT
    )
    assert build_support.macos_info_plist()["CFBundleIdentifier"] == (
        "io.github.noseglasses.matchpatch"
    )
    assert build_support.macos_info_plist()["CFBundleShortVersionString"] == project_version
    assert build_support.macos_info_plist()["CFBundleVersion"] == project_version

    assert build_support.installer_artifact_name("windows", project_version) == (
        f"MatchPatch-Setup-{project_version}.exe"
    )
    assert build_support.installer_artifact_path("windows", project_version) == (
        PROJECT_ROOT / "dist" / "installer" / f"MatchPatch-Setup-{project_version}.exe"
    )
    assert (
        build_support.installer_artifact_name(
            "macos",
            project_version,
            arch="arm64",
        )
        == f"MatchPatch-macOS-arm64-{project_version}.dmg"
    )
    assert (
        build_support.installer_artifact_path(
            "macos",
            project_version,
            arch="arm64",
        )
        == PROJECT_ROOT / "dist" / "installer" / f"MatchPatch-macOS-arm64-{project_version}.dmg"
    )

    with pytest.raises(ValueError, match="macos installer artifacts require an architecture name"):
        build_support.installer_artifact_name("macos", project_version)


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

    assert (
        payload_root / "audio" / "reference-di" / "DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav"
    ).is_file()


def test_runtime_files_docs_and_build_info_stage_into_macos_bundle_executable_root(
    tmp_path: Path,
) -> None:
    build_support = _load_build_support()
    macos_payload = tmp_path / "build" / "macos-payload" / "MatchPatch.app"
    build_support.PROJECT_ROOT = tmp_path
    docs_source = tmp_path / "docs_html"
    docs_source.mkdir(parents=True, exist_ok=True)
    (docs_source / ".doctrees").mkdir()
    (docs_source / ".doctrees" / "environment.pickle").write_bytes(b"cached doctree")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "matchpatch"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )
    (docs_source / "index.html").write_text("<html>offline docs</html>\n", encoding="utf-8")

    build_support.stage_runtime_files(macos_payload)
    build_support.stage_docs(macos_payload)
    build_support.write_build_info(macos_payload)

    runtime_root = macos_payload / "Contents" / "MacOS"
    assert (
        runtime_root / "audio" / "reference-di" / "DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav"
    ).is_file()
    assert (runtime_root / "docs_html" / "index.html").is_file()
    assert not (runtime_root / "docs_html" / ".doctrees").exists()
    build_info = json.loads((runtime_root / "build-info.json").read_text(encoding="utf-8"))
    assert build_info["version"] == "9.9.9"
    assert build_info["builder"] == "pyinstaller"


def test_macos_app_scripts_validate_bundle_layout_and_startup_smoke() -> None:
    build_script = (PROJECT_ROOT / "scripts" / "build-macos-app.sh").read_text(encoding="utf-8")
    dmg_script = (PROJECT_ROOT / "scripts" / "build-macos-dmg.sh").read_text(encoding="utf-8")
    smoke_script = (PROJECT_ROOT / "installer" / "smoke" / "smoke_macos_payload.sh").read_text(
        encoding="utf-8"
    )
    dmg_smoke_script = (PROJECT_ROOT / "installer" / "smoke" / "smoke_macos_dmg.sh").read_text(
        encoding="utf-8"
    )

    combined = "\n".join((build_script, dmg_script, smoke_script, dmg_smoke_script))

    assert "MatchPatch macOS app builds must run on macOS." in build_script
    assert "uv run --frozen --no-default-groups --group docs sphinx-build" in build_script
    assert (
        "uv run --frozen --no-default-groups --group installer --extra gui --extra hardware "
        "pyinstaller installer/pyinstaller/matchpatch-macos.spec"
    ) in build_script
    assert "build/macos-payload/MatchPatch.app" in combined
    assert 'codesign --force --deep --sign - "$payload_dir"' in build_script
    assert 'codesign --verify --deep --strict --verbose=4 "$payload_dir"' in build_script
    assert 'codesign --verify --deep --strict --verbose=4 "$app_bundle"' in smoke_script
    assert "MatchPatch macOS DMG builds must run on macOS." in dmg_script
    assert "hdiutil create" in dmg_script
    assert "-format UDZO" in dmg_script
    assert '-srcfolder "$dmg_stage_root"' in dmg_script
    assert "MatchPatch-macOS-${arch}-${project_version}.dmg" in dmg_script
    assert "Signing and notarization are intentionally deferred" in dmg_script
    assert "Contents/Info.plist" in combined
    assert "Contents/MacOS/MatchPatch" in combined
    assert "Contents/MacOS/docs_html/index.html" in combined
    assert "Contents/MacOS/build-info.json" in combined
    assert "audio/reference-di/DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav" in combined
    assert "--cli --version" in smoke_script
    assert "MATCHPATCH_GUI_SMOKE=1" in smoke_script
    assert "Bundled GUI smoke failed" in smoke_script
    assert "Bundled GUI smoke timed out after 60 seconds." in smoke_script
    assert "GUI smoke log:" in smoke_script
    assert "CFBundleIdentifier" in smoke_script
    assert "CFBundleShortVersionString" in smoke_script
    assert "CFBundleVersion" in smoke_script
    assert "io.github.noseglasses.matchpatch" in smoke_script
    assert "Payload smoke passed" in smoke_script
    assert "MatchPatch macOS DMG smoke tests must run on macOS." in dmg_smoke_script
    assert "--reuse-artifact" in dmg_smoke_script
    assert "--dmg <path>" in dmg_smoke_script
    assert "hdiutil attach -nobrowse -readonly -mountpoint" in dmg_smoke_script
    assert 'hdiutil detach -force -quiet "$mount_point"' in dmg_smoke_script
    assert 'smoke_macos_payload.sh "$app_bundle" "$project_version"' in dmg_smoke_script
    assert "DMG smoke passed" in dmg_smoke_script


def test_release_workflow_publishes_windows_installer() -> None:
    release_workflow = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "windows-installer:" in release_workflow
    assert "runs-on: windows-latest" in release_workflow
    assert "contents: write" in release_workflow
    assert "scripts\\test-windows-installer.cmd" in release_workflow
    assert "MatchPatch-Setup-$version.exe" in release_workflow
    assert "actions/upload-artifact@v7" in release_workflow
    assert "gh release create $tag" in release_workflow
    assert "gh release upload $tag $installer --clobber" in release_workflow
    assert release_workflow.count("GITHUB_REF_NAME") >= 2
    assert release_workflow.count("pyproject.toml") >= 2


def test_release_workflow_publishes_macos_installer() -> None:
    release_workflow = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "macos-installer:" in release_workflow
    assert "name: macOS installer" in release_workflow
    assert "runs-on: macos-15" in release_workflow
    assert "contents: write" in release_workflow
    assert 'test "${GITHUB_REF_NAME}" = "v${version}"' in release_workflow
    assert "MatchPatch-macOS-${arch}-${version}.dmg" in release_workflow
    assert "scripts/build-macos-dmg.sh" in release_workflow
    assert "installer/smoke/smoke_macos_dmg.sh --dmg" in release_workflow
    assert "matchpatch-macos-installer-${{ github.ref_name }}" in release_workflow
    assert 'gh release create "$tag"' in release_workflow
    assert 'gh release upload "$tag" "$installer" --clobber' in release_workflow


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


def _lock_package(lock: dict[str, object], name: str) -> dict[str, object]:
    package_entries = lock["package"]
    assert isinstance(package_entries, list)
    for package in package_entries:
        assert isinstance(package, dict)
        if package.get("name") == name:
            return package
    raise AssertionError(f"Missing package {name!r} in uv.lock")


def _requirement_markers(dependencies: list[object], name: str) -> set[str]:
    markers: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, str):
            continue
        requirement = Requirement(dependency)
        if requirement.name == name and requirement.marker is not None:
            markers.add(_normalize_marker(str(requirement.marker)))
    return markers


def _lock_dependency_markers(dependencies: list[object], name: str) -> set[str]:
    markers: set[str] = set()
    for dependency in dependencies:
        assert isinstance(dependency, dict)
        if dependency.get("name") == name:
            marker = dependency.get("marker")
            assert isinstance(marker, str)
            markers.add(_normalize_marker(marker))
    return markers


def _lock_requires_dist_supports_hardware(lock_package: dict[str, object], name: str) -> bool:
    required_dist = lock_package["metadata"]["requires-dist"]
    assert isinstance(required_dist, list)
    for dependency in required_dist:
        assert isinstance(dependency, dict)
        if dependency.get("name") != name:
            continue
        marker = dependency.get("marker")
        assert isinstance(marker, str)
        marker = _normalize_marker(marker)
        if "extra == 'hardware'" not in marker:
            continue
        if "sys_platform == 'darwin'" not in marker:
            continue
        if "sys_platform == 'win32'" not in marker:
            continue
        return True
    return False


def _normalize_marker(marker: str) -> str:
    return marker.replace('"', "'")
