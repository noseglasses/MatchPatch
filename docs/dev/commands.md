# Commands

Canonical commands for MatchPatch development. Run from the repository root.

## Environment

Create or update the shared WSL development environment:

```bash
scripts/sync-wsl.sh
```

Activate it when running commands interactively:

```bash
source "$HOME/.local/share/matchpatch/.venv-wsl/bin/activate"
```

Create or update the native Windows environment used for hardware audio/MIDI
work from WSL:

```bash
scripts/sync-windows-from-wsl.sh
```

The Windows environment is stored in `.venv-windows`. The WSL environment is
stored under `${XDG_DATA_HOME:-$HOME/.local/share}/matchpatch/.venv-wsl`.

## Test

Use the shared WSL pytest binary:

```bash
$HOME/.local/share/matchpatch/.venv-wsl/bin/pytest
```

Run a focused test:

```bash
$HOME/.local/share/matchpatch/.venv-wsl/bin/pytest tests/test_measure.py::test_loopback_backend_writes_compatible_csv
```

Run GUI tests:

```bash
scripts/test-gui.sh
```

Run a focused GUI test:

```bash
scripts/test-gui.sh tests/test_gui.py::test_loaded_file_updates_window_title_and_save_as_state
```

Do not rely on bare `pytest`; it may not be on `PATH`. Avoid `uv run pytest`
for local work when the project-local `.venv` is stale or incomplete.

## Quality

After syncing and activating the WSL env:

```bash
ruff check .
ruff format --check .
ty check
$HOME/.local/share/matchpatch/.venv-wsl/bin/pytest
```

Install the local Git hooks, including the Conventional Commit `commit-msg`
hook and the pre-push quality suite:

```bash
pre-commit install --install-hooks
pre-commit run --all-files --hook-stage pre-push
```

If hooks were already installed before `commit-msg` was added, reinstall all
configured hook types:

```bash
pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push --install-hooks
```

Commit messages must use Conventional Commits:

```text
feat(gui): add snapshot diff selector
fix: preserve adjusted setlist output path
chore(release): v0.2.0
```

CI runs equivalent `uv run --frozen --no-default-groups --group wsl` commands on
Linux, Windows, and WSL for Python 3.12, 3.13, and 3.14.

## Run The CLI

Show environment:

```bash
matchpatch --environment
```

List supported processor profiles:

```bash
matchpatch --devices
```

Export default config:

```bash
matchpatch --export-default-config ~/.config/matchpatch/config.toml
```

Installed Windows builds automatically look first in the roaming profile:

```powershell
MatchPatch.exe --cli --export-default-config "$env:APPDATA\MatchPatch\config.toml"
```

When `--config` is omitted, MatchPatch searches for config files in this order:
`%APPDATA%\MatchPatch\config.toml`, then
`%USERPROFILE%\.config\matchpatch\config.toml` on Windows; on Linux/WSL/macOS,
`$XDG_CONFIG_HOME/matchpatch/config.toml` when `XDG_CONFIG_HOME` is set,
otherwise `~/.config/matchpatch/config.toml`.

Normalize without hardware:

```bash
matchpatch normalize --device helix --backend loopback -i setlist.hls -o setlist_adjusted.hls -S 01A --keep-temp
matchpatch normalize --device podgo --backend loopback -i setlist.pgs -o setlist_adjusted.pgs -S 01A --keep-temp
```

Normalize with simulated hardware:

```bash
matchpatch normalize --device helix --backend simulated -i setlist.hls -o setlist_adjusted.hls -S 01A,01B --keep-temp
```

Guided hardware workflow:

```bash
matchpatch normalize --device helix -a -i setlist.hls
matchpatch normalize --device podgo -a -i setlist.pgs
```

Single preset measurement requires one temporary device slot:

```bash
matchpatch normalize --device helix -a -i Song.hlx -S 12A
matchpatch normalize --device podgo -a -i Song.pgp -S 12A
```

Select only presets changed relative to an earlier setlist:

```bash
matchpatch normalize --device helix -a -i current.hls --diff-input previous.hls
```

## Native Measurement Worker

From WSL, list native Windows audio/MIDI devices:

```bash
scripts/measure-windows-from-wsl.sh devices
```

Run a direct loopback measurement:

```bash
python -m matchpatch.measure measure --device helix --backend loopback --preset-ids 1,6 --csv /tmp/lufs_analysis.csv --reference-di audio/reference-di/DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav
```

Run the Windows worker from WSL:

```bash
scripts/measure-windows-from-wsl.sh measure --device helix --backend hardware --preset-ids 1,6 --csv "$(wslpath -w /tmp/lufs_analysis.csv)" --reference-di "$(wslpath -w audio/reference-di/DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav)"
```

Check hardware availability:

```bash
scripts/measure-windows-from-wsl.sh check-hardware --device helix
```

## GUI

Install GUI dependencies into the WSL env:

```bash
scripts/sync-wsl.sh --extra gui
```

Launch:

```bash
matchpatch-gui
```

The GUI starts with the configured backend and can run loopback/simulated flows
without processor hardware. Hardware mode requires the native Windows
environment and visible audio/MIDI endpoints.

## Helix Utility Module

Run from the repository root:

```bash
python3 -m matchpatch.devices.helix.preset_handling --help
```

Useful integrated operations:

```bash
python3 -m matchpatch.devices.helix.preset_handling -i setlist.hls -o setlist_measurement.hls --measurement
python3 -m matchpatch.devices.helix.preset_handling -i setlist.hls --list-presets
python3 -m matchpatch.devices.helix.preset_handling -i current.hls --diff-presets previous.hls
```

## Pod Go Utility Module

Run from the repository root:

```bash
python3 -m matchpatch.devices.line6.podgo.preset_handling --help
```

Useful integrated operations:

```bash
python3 -m matchpatch.devices.line6.podgo.preset_handling -i setlist.pgs -o setlist_measurement.pgs --measurement
python3 -m matchpatch.devices.line6.podgo.preset_handling -i setlist.pgs --list-presets
python3 -m matchpatch.devices.line6.podgo.preset_handling -i current.pgs --diff-presets previous.pgs
matchpatch files split --device podgo --input setlist.pgs --output-dir presets
matchpatch files join --device podgo --output joined.pgs --preset-set 01A,01B presets/Lead.pgp presets/Clean.pgp
```

## Build

Build wheel and source distribution:

```bash
uv build --no-sources
```

Smoke-test built artifacts:

```bash
uv run --isolated --no-project --with dist/*.whl python -c "import matchpatch"
uv run --isolated --no-project --with dist/*.tar.gz python -c "import matchpatch"
```

(test-pypi-package)=

## Test The Published PyPI Package

Use fresh virtual environments when checking a published PyPI release. Do not
reuse the repository WSL environment, `.venv-windows`, or a project-local
`.venv`; those environments can hide missing package metadata.

MatchPatch supports Python `>=3.12,<3.15`. Replace `0.8.2` with the version you
just published.

From WSL:

```bash
python3.12 -m venv /tmp/matchpatch-pypi-test
source /tmp/matchpatch-pypi-test/bin/activate

python -m pip install --upgrade pip
python -m pip install --no-cache-dir "matchpatch[gui]==0.8.2"

python -m pip show matchpatch
matchpatch --version
matchpatch --environment
matchpatch --devices
matchpatch-gui --help
matchpatch-gui --version
python -c "import matchpatch; import matchpatch.analysis; import matchpatch.normalize; print('import OK')"

deactivate
```

From native Windows PowerShell:

```powershell
py -3.12 -m venv $env:TEMP\matchpatch-pypi-test
& $env:TEMP\matchpatch-pypi-test\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install --no-cache-dir "matchpatch[gui]==0.8.2"

python -m pip show matchpatch
matchpatch --version
matchpatch --environment
matchpatch --devices
matchpatch-gui --help
matchpatch-gui --version
python -c "import matchpatch; import matchpatch.analysis; import matchpatch.normalize; print('import OK')"

deactivate
```

For hardware dependency metadata checks on native Windows, install the hardware
extra in the same fresh environment:

```powershell
python -m pip install --no-cache-dir "matchpatch[gui,hardware]==0.8.2"
python -c "import mido; import sounddevice; print('hardware imports OK')"
```

These checks verify that the published wheel declares the dependencies needed
by the installed command-line entry points. They do not replace installer smoke
tests or real hardware checks.

For the lightweight macOS CI-style import smoke, install the hardware extra in
the same fresh environment and verify the backend imports directly:

```bash
uv sync --locked --no-default-groups --extra hardware
uv run --frozen --no-default-groups --extra hardware python -c "import mido; import mido.backends.rtmidi; import rtmidi; import sounddevice; print('macOS hardware imports OK')"
```

This checks the macOS hardware dependency metadata without requiring any
physical processor hardware.

For the macOS hardware validation harness, run the device listing and hardware
diagnostics together. The harness writes its logs to `build/macos-hardware/`:

```bash
scripts/test-macos-hardware.sh
```

On GitHub-hosted macOS runners, this expects no Helix or Pod Go to be attached
and therefore checks that the diagnostics fail cleanly. On a self-hosted macOS
runner with hardware attached, set `MATCHPATCH_MACOS_HARDWARE=1` and rerun the
same script so the diagnostics must pass instead.

To record the exact Core Audio and CoreMIDI names, keep the device listing and
diagnostics outputs:

```bash
uv run --frozen --no-default-groups --extra hardware python -m matchpatch.measure devices \
  | tee build/macos-hardware/device-list.txt
uv run --frozen --no-default-groups --extra hardware python -m matchpatch.measure check-hardware \
  --device helix --diagnostics-json > build/macos-hardware/helix-diagnostics.json \
  2> build/macos-hardware/helix-diagnostics.stderr.txt
uv run --frozen --no-default-groups --extra hardware python -m matchpatch.measure check-hardware \
  --device podgo --diagnostics-json > build/macos-hardware/podgo-diagnostics.json \
  2> build/macos-hardware/podgo-diagnostics.stderr.txt
```

In `device-list.txt`, copy the exact `Audio devices:` and `MIDI outputs:`
entries for the attached processor. In the JSON diagnostics, record:

```text
audio_device.detail.device
audio_device.detail.input_mapping
audio_device.detail.output_mapping
midi_output.detail.output
midi_output.detail.channel
```

Those fields show the Core Audio device name, the channel mapping used by
`sounddevice.playrec`, and the CoreMIDI output name chosen for steering.

## Packaging

The checked-in Windows packaging pipeline builds a frozen application payload
with PyInstaller, then packages that payload with Inno Setup 6.

Prerequisites:

- A native Windows checkout, or WSL with the Windows mirror workflow.
- `uv`.
- Inno Setup 6, with `ISCC.exe` on `PATH`, installed in the default location,
  or referenced by `INNO_SETUP_ISCC`.

Build and test the installer from WSL:

```bash
scripts/test-windows-installer-from-wsl.sh
```

Build only the installer from WSL:

```bash
scripts/build-windows-installer-from-wsl.sh
```

Build and test from a native Windows checkout:

```bat
scripts\test-windows-installer.cmd
```

Build only from a native Windows checkout:

```bat
scripts\build-windows-installer.cmd
```

Build only the frozen payload:

```bat
scripts\build-windows-payload.cmd
```

The default WSL mirror lives at `/mnt/c/src/MatchPatch-windows`. Override it
with `MATCHPATCH_WINDOWS_WORKDIR` if your Windows checkout lives elsewhere.

Generated outputs:

- Payload: `build/windows-payload/MatchPatch/`
- Payload manifest: `build/windows-payload/MatchPatch/build-info.json`
- Installer: `dist/installer/MatchPatch-Setup-<version>.exe`
- Offline help staged beside the executable: `docs_html/`

Run smoke tests against an existing installer artifact:

```bat
scripts\test-windows-installer.cmd --reuse-artifact
scripts\test-windows-installer.cmd --installer C:\path\to\MatchPatch-Setup-0.1.0.exe
```

Add `--gui-smoke` to initialize the GUI in non-interactive smoke mode as part
of the payload and installed-app checks.

The smoke tests verify that `MatchPatch.exe`, bundled `docs_html/index.html`,
installer artwork, and `build-info.json` exist; that
`build-info.json` reports the expected version; that
`MatchPatch.exe --cli --version` starts cleanly; and that the
installer can install and uninstall silently.

Troubleshooting:

- If a script reports a UNC path problem, run from a native Windows path or use
  the WSL wrapper so the project is mirrored to a Windows filesystem.
- If `ISCC.exe` is missing, install Inno Setup 6, add it to `PATH`, or set
  `INNO_SETUP_ISCC` to the full compiler path.
- If the GUI fails with Qt or PySide6 plugin startup errors, rebuild the payload
  with `scripts\build-windows-payload.cmd` so PyInstaller can restage Qt
  plugins and runtime files.
- Antivirus warnings can happen while testing the unsigned installer. Verify the
  artifact came from your local build or GitHub Actions before allowing it.

Brand assets for app packaging live in `docs/assets/`.

Stage the offline documentation payload manually with:

```bash
scripts/stage-installer-docs.sh <installer-payload-dir>
```

The script builds `docs_html/`, copies it to
`<installer-payload-dir>/docs_html`, and verifies that the installer payload has
the docs index, quick start, workflow pages, concept pages, and Sphinx static
assets. Installers should place that `docs_html/` directory beside the GUI
executable so `matchpatch.gui.help.local_docs_root()` can resolve local
`file://` help URLs.

Sync the opt-in Windows installer build environment from a native Windows
checkout with:

```bat
uv sync --locked --no-default-groups --group windows --group docs --group installer --extra gui
```

Inno Setup is intentionally not a Python dependency. Install Inno Setup on the
Windows host or provide it in CI before running installer packaging scripts.

## Docs

Build the local Sphinx HTML documentation with:

```bash
scripts/build-docs.sh
```

The wrapper cleans `docs_html/`, runs Sphinx in strict mode, and writes the
generated offline help bundle back to `docs_html/`.

Suggested checks for docs-only changes:

```bash
scripts/build-docs.sh
ruff format --check .
git diff --check
```

## Release

Release automation is tag-driven and publishes to PyPI from GitHub Actions.

1. Update `project.version` in `pyproject.toml`.
2. Commit the version change.
3. Tag with `v<version>` matching `pyproject.toml`.
4. Push the tag.

```bash
git tag v0.1.0
git push origin v0.1.0
```

The release workflow verifies the tag/version match, runs `uv build
--no-sources`, smoke-tests the wheel and source distribution, builds and uploads
the offline docs artifact, publishes to PyPI with trusted publishing, and runs a
separate Windows job that builds, smoke-tests, uploads, and attaches
`MatchPatch-Setup-<version>.exe` to the GitHub Release.
