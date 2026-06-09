# Windows Installer

MatchPatch uses PyInstaller to create a self-contained Windows application
payload, then packages that payload with Inno Setup 6.

## Layout

- `matchpatch.iss`: Inno Setup script for the final installer.
- `pyinstaller/matchpatch-gui.spec`: frozen `MatchPatch.exe` GUI build.
- `pyinstaller/matchpatch-cli.spec`: frozen `matchpatch.exe` CLI build.
- `pyinstaller/build_support.py`: shared PyInstaller build metadata and data
  staging helpers.
- `smoke/smoke_payload.ps1`: checks the frozen payload before installation.
- `smoke/smoke_installed.ps1`: checks silent install, CLI startup, optional GUI
  startup, and silent uninstall.

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
scripts\test-windows-installer.cmd --installer C:\path\to\MatchPatch-Setup-0.1.0.exe
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
