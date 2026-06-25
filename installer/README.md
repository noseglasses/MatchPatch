# Windows Installer

MatchPatch uses PyInstaller to create a self-contained Windows application
payload, then packages that payload with Inno Setup 6.

## Layout

- `matchpatch.iss`: Inno Setup script for the final installer.
- `pyinstaller/matchpatch-gui.spec`: frozen `MatchPatch.exe` GUI build. Use
  `MatchPatch.exe --cli ...` for command-line mode.
- `pyinstaller/build_support.py`: shared PyInstaller build metadata and data
  staging helpers.
- `smoke/smoke_payload.ps1`: checks the frozen payload before installation.
- `smoke/smoke_installed.ps1`: checks silent install, CLI startup, optional GUI
  startup, and silent uninstall.

## macOS Installer Notes

MatchPatch also builds a macOS `.app` bundle and DMG for release testing. The
current macOS app bundle is ad-hoc signed so its internal code-signing seal is
valid, but it is not Developer ID signed or notarized because the project does
not yet have Apple Developer Program funding.

Future signing and notarization work is deferred on purpose. See the Session 5
TODOs in [release docs](../docs/dev/release.md#deferred-macos-signing-and-notarization)
for the planned future checklist.

macOS artifacts without Developer ID signing or notarization may require manual
Gatekeeper approval the first time they are opened.

## macOS Build And Test

CI builds the Mac installer on `macos-15` and smoke-tests the DMG there.
Developers do not have local Mac hardware, so the macOS path is validated in CI
and by release artifacts, not by a local maintainer machine.

Build the `.app` bundle:

```bash
scripts/build-macos-app.sh
```

Build the DMG:

```bash
scripts/build-macos-dmg.sh
```

Smoke-test the bundle or DMG:

```bash
installer/smoke/smoke_macos_payload.sh build/macos-payload/MatchPatch.app 0.8.1
installer/smoke/smoke_macos_dmg.sh --reuse-artifact
```

Expected macOS outputs:

- App bundle: `build/macos-payload/MatchPatch.app`
- DMG: `dist/installer/MatchPatch-macOS-<arch>-<version>.dmg`

The smoke checks verify the bundle metadata, bundled CLI startup, bundled GUI
startup in non-interactive smoke mode, offline docs, `build-info.json`, and
reference DI audio. The DMG smoke mounts the image, checks the app bundle from
the mounted volume, and then detaches it again.

The macOS scripts and workflows do not claim hardware validation. They only
prove packaging, startup, and no-device behavior on GitHub-hosted runners.

## Prerequisites

- Windows, or WSL with a native Windows mirror checkout.
- `uv`.
- Inno Setup 6. The build script finds `ISCC.exe` in this order:
  `INNO_SETUP_ISCC`, `PATH`, `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`,
  then `C:\Program Files\Inno Setup 6\ISCC.exe`.

Inno Setup is not a Python dependency. Install it on the Windows host or in CI
before building the installer.

## Build And Test

From WSL, using the Windows mirror workflow:

```bash
scripts/test-windows-installer-from-wsl.sh
```

Build only from WSL:

```bash
scripts/build-windows-installer-from-wsl.sh
```

The WSL scripts use `/mnt/c/src/MatchPatch-windows` by default. Override that
with `MATCHPATCH_WINDOWS_WORKDIR`.

From a native Windows checkout:

```bat
scripts\test-windows-installer.cmd
```

Build only from native Windows:

```bat
scripts\build-windows-installer.cmd
```

Build only the PyInstaller payload:

```bat
scripts\build-windows-payload.cmd
```

Run smoke tests against an existing artifact:

```bat
scripts\test-windows-installer.cmd --reuse-artifact
scripts\test-windows-installer.cmd --installer C:\path\to\MatchPatch-Setup-0.8.1.exe
```

Add `--gui-smoke` to run the non-interactive GUI startup check in both smoke
tests.

## Outputs

- Frozen payload: `build/windows-payload/MatchPatch/`
- Payload metadata: `build/windows-payload/MatchPatch/build-info.json`
- Offline docs in payload: `build/windows-payload/MatchPatch/docs_html/`
- Installer: `dist/installer/MatchPatch-Setup-<version>.exe`

The installer version is read from `project.version` in `pyproject.toml`.

## Troubleshooting

- UNC path error: run the `.cmd` scripts from a native Windows path, or use the
  WSL wrapper so the checkout is mirrored to a Windows filesystem.
- Missing `ISCC.exe`: install Inno Setup 6, add it to `PATH`, or set
  `INNO_SETUP_ISCC` to the full compiler path.
- Qt or PySide6 plugin startup error: rebuild the payload so PyInstaller
  restages the Qt runtime files.
- Antivirus warning: first public builds are unsigned. Only allow installers
  produced locally or by the MatchPatch GitHub Actions release workflow.
- Gatekeeper warning: current macOS release artifacts are unsigned and may need
  manual approval on first launch.
