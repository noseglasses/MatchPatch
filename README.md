# MatchPatch

<p align="center">
  <img src="https://raw.githubusercontent.com/noseglasses/MatchPatch/main/doc/assets/matchmatch-logo.png" alt="MatchPatch: Normalize presets. Match volume." width="520">
</p>

[![Quality](https://github.com/noseglasses/MatchPatch/actions/workflows/quality.yml/badge.svg)](https://github.com/noseglasses/MatchPatch/actions/workflows/quality.yml)
[![Release](https://github.com/noseglasses/MatchPatch/actions/workflows/release.yml/badge.svg)](https://github.com/noseglasses/MatchPatch/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/matchpatch.svg)](https://pypi.org/project/matchpatch/)
[![Python](https://img.shields.io/pypi/pyversions/matchpatch.svg)](https://pypi.org/project/matchpatch/)

**Measure once. Match every patch.**

MatchPatch normalizes gain across audio-processor presets and snapshots. It
plays a reference DI through each patch, measures LUFS and crest factor, then
writes adjusted preset files with balanced output levels.

The first supported device is the **Line 6 Helix**. The architecture is
device-aware, so additional processors can provide their own file handling,
steering commands, and audio routing later. MatchPatch is designed to support
Windows, Linux, and WSL.

## Why MatchPatch?

- Replace manual gain matching with a repeatable Python workflow.
- Normalize Helix `.hls` setlists and `.hlx` presets.
- Test the complete measurement pipeline without hardware using loopback mode.
- Keep environments and dependencies reproducible with one `uv.lock`.

## How It Works

```text
MatchPatch CLI
  -> preset and snapshot selection
  -> reference playback and processed-audio recording
  -> LUFS and crest-factor analysis
  -> adjusted processor preset file
```

## Quick Setup

MatchPatch uses [uv](https://docs.astral.sh/uv/) for environments, dependency
locking, and package installation. Install uv for your platform:

```bash
# Linux or WSL
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Synchronize the environment:

```bash
# Linux or WSL
scripts/sync-wsl.sh
source "$HOME/.local/share/matchpatch/.venv-wsl/bin/activate"
```

When running the current Helix hardware workflow from WSL, also install uv on
Windows and synchronize its audio environment:

```bash
scripts/sync-windows-from-wsl.sh
```

## Try It Without Hardware

Loopback mode simulates an empty processor patch by feeding the reference DI
directly into the analyzer:

```bash
matchpatch normalize \
  --device helix \
  --backend loopback \
  -i setlist_original.hls \
  -o setlist_loopback_adjusted.hls \
  -S 01A \
  --keep-temp
```

## Normalize With A Helix

List available audio devices and MIDI outputs:

```bash
scripts/measure-windows-from-wsl.sh devices
```

Run the guided workflow:

```bash
matchpatch normalize --device helix -a -i setlist_original.hls
```

MatchPatch creates a reamp file, pauses while you import it into the Helix,
measures the presets, and creates the adjusted file.

For a single `.hlx` preset, specify the temporary Helix slot:

```bash
matchpatch normalize --device helix -a -i "Song.hlx" -S 12A
```

Useful options:

| Option | Purpose |
|---|---|
| `-S 01A,01B,02A` | Measure selected processor slots |
| `-n 8` | Limit measurement to the first eight selected presets |
| `--target-lufs -18` | Override the default `-16 LUFS` target |
| `--keep-temp` | Keep the generated measurement CSV |
| `--audio-device "Helix ASIO"` | Select an ambiguous audio device |
| `--midi-output "Helix"` | Select an ambiguous MIDI output |
| `--timeout 300` | Limit analysis time |

Helix defaults:

| Purpose | USB channels |
|---|---|
| Processed audio recording | USB `1/2` |
| Reference DI playback | USB `3/4` |

## Supported Files

| Extension | Meaning | Notes |
|---|---|---|
| `.hls` | Helix setlist | Contains multiple presets |
| `.hlx` | Helix preset | Contains one preset and requires one `-S` slot during measurement |
| `.json` | Unpacked Helix data | Supported by selected legacy utilities |

Keep backups of original processor files. Generated reamp files are meant for
measurement, not stage use.

## Device Profiles

Processor-specific code lives in `src/matchpatch/devices/`. A profile supplies:

- preset and setlist file handling;
- preset and snapshot steering;
- default processor USB channels.

The measurement workflow and loopback backend stay device-independent. To add
another processor, implement `DeviceProfile`, `PatchFileHandler`, and
`DeviceController`, then register the profile in
`src/matchpatch/devices/registry.py`.

## Helix Utilities

Additional Helix utilities are available under `Python/`:

| Script | Purpose |
|---|---|
| `preset_handling.py` | Convert routing, list presets, and apply LUFS adjustments |
| `list_cab_presets.py` | List presets containing isolated cab blocks |
| `replace_amp.py` | Replace amp+cab blocks with amp-only blocks |
| `remove_inactive_blocks.py` | Remove blocks inactive in the first four snapshots |
| `reset_output_levels.py` | Reset active and snapshot-assigned output gains |
| `stereofy.py` | Convert identifiable post-cab or post-IR blocks to stereo |
| `decrypt_hls.py` | Unpack `.hls` data to JSON |
| `encrypt_hls.py` | Pack JSON data into `.hls` |

Run a utility from the repository root:

```bash
python3 Python/preset_handling.py --help
```

## Development

Synchronize dependencies and run the same checks enforced by GitHub Actions:

```bash
scripts/sync-wsl.sh
source "$HOME/.local/share/matchpatch/.venv-wsl/bin/activate"

ruff check .
ruff format --check .
ty check
pytest
```

The pytest suite includes Hypothesis property tests and reports branch-aware
coverage in the terminal and under `htmlcov/`.

Install Git hooks:

```bash
pre-commit install --install-hooks
pre-commit run --all-files --hook-stage pre-push
```

CI runs on Python `3.12`, `3.13`, and `3.14` across Linux, Windows, and WSL.
Dependabot maintains uv, GitHub Actions, and pre-commit dependencies.

## Releases

Push a version tag matching `pyproject.toml`, such as `v0.1.0`, to trigger the
trusted-publishing workflow:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The release workflow builds and smoke-tests the wheel and source distribution,
then publishes to PyPI through GitHub OIDC without a stored API token.

## Brand Assets

The project logo and square icons live under `doc/assets/`. Use
`matchmatch-icon-512.png` for GitHub's social preview and future application
packaging.
