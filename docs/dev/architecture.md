# Architecture

MatchPatch is a Python 3.12+ application for normalizing loudness across audio
processor presets. The checked-in code is centered on Line 6 Helix support, but
the newer package layout separates front ends, normalization workflow, audio
measurement, and device-specific adapters so more processors can be added later.

## Repository Layout

- `src/matchpatch/` contains the installable package and console entry points.
- `src/matchpatch/gui/` contains the PySide6 GUI.
- `src/matchpatch/devices/` contains processor profile interfaces and the Helix
  implementation.
- `Python/` contains legacy Helix file-manipulation utilities. The modern Helix
  profile still delegates `.hls`/`.hlx` parsing and rewriting to
  `Python/preset_handling.py`.
- `scripts/` contains WSL/Windows environment, worker, installer build, and
  installer smoke-test wrappers.
- `installer/` contains the Inno Setup script, PyInstaller specs, and
  PowerShell smoke tests for the Windows installer.
- `tests/` contains unit, workflow, CLI, measurement, and GUI tests.
- `.github/workflows/` defines quality, installer smoke, PyPI release, and
  GitHub Release artifact automation.

## Entry Points

`pyproject.toml` exposes two console scripts:

- `matchpatch = matchpatch.cli:main`
- `matchpatch-gui = matchpatch.gui.app:main`

`matchpatch.cli` handles top-level utility flags such as `--devices`,
`--environment`, and `--export-default-config`. The `normalize` subcommand is
forwarded to `matchpatch.normalize`.

`matchpatch.gui.app` configures WSLg/Wayland behavior, installs a desktop entry
and Qt message handler, creates `QApplication`, and shows `MainWindow`.

The native measurement worker can also be invoked directly:

```bash
python -m matchpatch.measure measure ...
python -m matchpatch.measure devices
python -m matchpatch.measure check-hardware ...
```

## Normalization Flow

The reusable orchestration lives in `matchpatch.workflow.normalize_presets`.
Both CLI and GUI build a `NormalizationRequest`, then call the workflow with a
measurement runner and optional callbacks.

The workflow:

1. Loads a `DeviceProfile` from the registry.
2. Validates snapshot count, input file, reference DI, and optional custom
   adjustment file.
3. In automation mode, writes a device-specific measurement file beside the
   input and asks the user to import it.
4. Resolves selected preset IDs from the input file, optional `--preset-set`,
   optional `--diff-input`, and optional `--limit`.
5. Creates a temporary directory and asks the measurement runner to write
   `lufs_analysis.csv`.
6. Verifies the CSV row count matches selected presets.
7. Applies the CSV through the device file handler, unless GUI-style export is
   deferred.
8. Keeps or removes temporary files according to `keep_temp`, failure state, and
   deferred export.

`workflow.export_adjusted_file` reuses a retained CSV to write an adjusted file
later. This is the GUI save/export path after a deferred measurement run.

## CLI/WSL Bridge

`matchpatch.normalize` is the WSL-side command implementation. It merges command
line options, `~/.config/matchpatch/config.toml` or `--config`, and environment
overrides:

- `MATCHPATCH_BACKEND`
- `MATCHPATCH_WINDOWS_PYTHON`
- `MATCHPATCH_REFERENCE_DI`

For hardware measurement from WSL, `run_windows_analysis` builds a command for
the native Windows environment:

```text
<windows-python> -m matchpatch.measure measure ...
```

Paths are converted with `wslpath -w`. When the GUI supplies a progress callback,
the worker adds `--progress-jsonl` and parses structured progress lines from the
Windows process. Cancellation kills the worker process if needed.

`check_windows_hardware` performs an equivalent native call for
`matchpatch.measure check-hardware`.

## Measurement Worker

`matchpatch.measure` is designed to run natively where audio and MIDI devices are
visible. It supports three backends:

- `hardware`: uses `sounddevice` duplex playback/recording and a device
  controller for preset/snapshot steering.
- `loopback`: records the reference DI unchanged and needs no hardware.
- `simulated`: validates routing, tracks preset/snapshot state, applies
  deterministic gain and compression, and can inject preset failures.

The measurement worker loads a reference WAV with `soundfile`, ensures the
sample rate matches the configured device rate, forces mono files to stereo, and
truncates files with more than two channels to stereo.

`measure_presets` computes reference loudness once, then for each preset and
measured snapshot:

1. Activates the preset.
2. Reapplies the snapshot.
3. Records processed audio.
4. Computes average short-term LUFS and crest factor.
5. Appends one row to the measurement CSV.

Failures for a preset are represented by `ERROR` fields in that preset's row so
the rest of the run can continue.

## Audio Analysis

`matchpatch.analysis` contains the signal metrics:

- `calculate_average_short_term_lufs` slides a loudness window through the
  recording, using `pyloudnorm.Meter.integrated_loudness` and averaging valid
  windows.
- `calculate_crest_factor_db` computes peak/RMS in dB.
- `analyze_audio` returns both metrics in `AudioMeasurements`.

Defaults are `window_seconds=3.0`, `interval_seconds=0.1`, and
`minimum_valid_lufs=-100.0`. The LUFS window must be at least `0.4` seconds.

`matchpatch.audio` wraps `sounddevice`. It enables ASIO by default, resolves an
audio device by numeric ID or name substring, validates channel capacity, records
with configured USB mappings, and trims pre-roll/post-roll using
`round_trip_latency_seconds`.

## Device Layer

`matchpatch.devices.base` defines the extension seam:

- `DeviceProfile` names a processor, exposes default audio routing and steering,
  creates file handlers and controllers, and defines device limits.
- `PatchFileHandler` validates inputs/outputs, lists assignments, parses preset
  selectors, creates measurement files, applies analysis CSVs, and builds
  automation output paths.
- `DeviceController` activates presets and reapplies snapshots.

The registry in `matchpatch.devices.registry` currently registers only
`helix`.

## Helix Profile

`HelixDeviceProfile` declares:

- name: `helix`
- display name: `Line 6 Helix`
- max measured snapshots: `8`
- preset name length: `16`
- snapshot name length: `10`
- default audio: device query `Helix`, sample rate `48000`, input USB `1/2`,
  output USB `3/4`
- default steering: MIDI output query `Helix`, channel `0`, preset wait `0.5`,
  snapshot wait `0.2`, measurement wait `0.1`

`HelixMidiController` uses `mido`. Presets are selected with MIDI program
changes, where internal preset ID `1` maps to program `0`. Snapshots use CC 69
with values `0..7`.

`HelixPatchFileHandler` shells out to `Python/preset_handling.py` with the
current Python interpreter. It delegates:

- assignment listing via `--list-presets`
- metadata extraction via `--metadata`
- loudness-affecting diff selection via `--diff-presets`
- measurement file creation via `--measurement`
- gain application via `--adjust-gain`

Modern measurement CSVs use a generic `DevicePatch` column. Before passing them
to the legacy utility, the Helix handler writes a temporary legacy CSV that adds
or replaces `HelixPreset`.

## Helix File Processing

`Python/preset_handling.py` understands `.hls`, `.hlx`, and unpacked `.json`.
Setlists are stored as JSON wrappers whose `encoded_data` contains base64 zlib
data; the script preserves wrapper fields while replacing encoded data, size,
and CRC. Presets are JSON files and may contain either a top-level preset or a
wrapper with a `data` preset object.

Measurement conversion changes Helix routing so processor input comes from USB
`3/4` and final output goes to USB `1/2`. Stage conversion restores USB `1/2`
outputs to XLR and USB `3/4` inputs to Multi.

Gain application finds an active final output block, normalizes output routing,
ensures snapshot controller values exist, computes per-snapshot gain deltas from
LUFS and crest factor, adds solo boosts and custom/user overrides, applies a
deadband, rejects implausible gain values unless bad LUFS is ignored, and writes
snapshot output gain values.

## GUI Architecture

`MainWindow` owns user-facing state: active file, selected device/backend,
advanced configuration, preset table, metadata view, retained CSV display,
logging, and file save/save-as actions. It reads preset assignments and metadata
through the selected device profile.

`matchpatch.gui.worker` keeps blocking work off the UI thread:

- `HardwareCheckWorker` runs the native hardware check.
- `NormalizationWorker` runs `normalize_presets`, forwards progress, asks the UI
  to confirm import steps, and supports cancellation.
- `MeasurementOptimizationWorker` runs native timing optimization and forwards
  progress.

Progress is carried as `ProgressEvent` dataclasses. JSONL progress is used
across the WSL-to-Windows process boundary; Qt signals carry event objects
inside the GUI.

## Configuration

`matchpatch.config` reads TOML using the standard library. When no `--config`
is supplied, it checks `default_config_paths()` in order and loads the first
existing file:

- Windows: `%APPDATA%\MatchPatch\config.toml`, then
  `%USERPROFILE%\.config\matchpatch\config.toml`;
- Linux/WSL/macOS: `$XDG_CONFIG_HOME/matchpatch/config.toml` when
  `XDG_CONFIG_HOME` is set, otherwise `~/.config/matchpatch/config.toml`.

`--config` points at one explicit file and raises an error if that file is
missing.

Configuration is layered with command-line values preferred over config file
values. For normalize commands, selected environment variables override matching
file values. `export_default_config` writes a complete TOML file containing
normalization, analysis, measurement policy, and per-device routing/steering
defaults.

## Legacy Utility Scripts

The `Python/` directory predates the package architecture. The main integrated
script is `preset_handling.py`; other checked-in scripts perform Helix-specific
batch transformations such as decrypting/encrypting HLS, listing cab presets,
replacing amp blocks, removing inactive blocks, resetting output levels, and
converting blocks to stereo. They are useful utilities but not the core
normalization API.

## CI And Packaging

The quality workflow runs Linux, Windows, and WSL jobs across Python 3.12,
3.13, and 3.14. It syncs dependencies with `uv`, then runs Ruff lint, Ruff
format check, `ty check`, and pytest with coverage.

The quality workflow also runs a Windows installer smoke job on Python 3.12. It
installs Inno Setup, builds the PyInstaller payload, packages it with
`installer/matchpatch.iss`, runs payload and silent install/uninstall smoke
tests, and uploads the generated installer artifact for inspection.

The release workflow is tag-driven. A `v*` tag must match
`project.version` in `pyproject.toml`; CI builds distributions with `uv build`,
smoke-tests the wheel and source distribution, uploads the generated
`docs_html/` offline help bundle for installer packaging, and publishes to PyPI
using OIDC trusted publishing. A separate Windows release job repeats the
tag/version check, builds and smoke-tests the installer, uploads it as an
Actions artifact, and attaches `MatchPatch-Setup-<version>.exe` to the GitHub
Release.

Windows installer packaging is a three-stage flow:

1. Build strict Sphinx HTML docs into `docs_html/`.
2. Freeze the GUI and CLI into `build/windows-payload/MatchPatch/` with
   PyInstaller, including brand assets, offline docs, and `build-info.json`.
3. Package the payload with Inno Setup into
   `dist/installer/MatchPatch-Setup-<version>.exe`.

Installer builds run from a native Windows path. WSL users normally invoke
`scripts/build-windows-installer-from-wsl.sh` or
`scripts/test-windows-installer-from-wsl.sh`, which synchronize the Windows
mirror before calling the native `.cmd` scripts.
