# MatchPatch

Command line tools for measuring and normalizing audio processor presets.

## Python Project Setup

MatchPatch uses `uv` for Python installation, dependency locking, virtual
environment creation, and package synchronization. Do not create virtual
environments manually or install project packages with `pip`.

The repository uses two `uv` dependency groups and two platform-specific
virtual environments:

| Platform | Dependency group | Managed environment |
|---|---|---|
| WSL/Linux development | `wsl` | `~/.local/share/matchpatch/.venv-wsl` |
| Native Windows processor worker | `windows` | `.venv-windows` |

The Windows group includes the WSL analysis dependencies plus the native MIDI
and audio packages that will replace REAPER. Both environments use the same
`pyproject.toml` and shared `uv.lock`.

Install `uv` once on each operating system using the official installers:

```bash
# WSL
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Native Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then synchronize the WSL environment from WSL:

```bash
scripts/sync-wsl.sh
```

Synchronize the native Windows environment from the same WSL shell:

```bash
scripts/sync-windows-from-wsl.sh
```

The second command invokes the Windows `uv.exe` through WSL interoperability.
It therefore requires `uv` to be installed and available on the Windows
`PATH`.

Add or remove platform dependencies through `uv`, then refresh the shared
lockfile:

```bash
uv add --group wsl PACKAGE
uv add --group windows PACKAGE
uv lock
```

Run the package CLI in WSL:

```bash
UV_PROJECT_ENVIRONMENT="$HOME/.local/share/matchpatch/.venv-wsl" \
  uv run --no-default-groups --group wsl \
  matchpatch --environment
```

Run the pytest suite with terminal and HTML coverage reporting:

```bash
scripts/sync-wsl.sh
UV_PROJECT_ENVIRONMENT="$HOME/.local/share/matchpatch/.venv-wsl" \
  uv run --no-default-groups --group wsl \
  pytest
```

The terminal report includes missing line numbers. The browsable HTML report is
written to `htmlcov/index.html`.

Run Ruff code-quality checks:

```bash
UV_PROJECT_ENVIRONMENT="$HOME/.local/share/matchpatch/.venv-wsl" \
  uv run --no-default-groups --group wsl \
  ruff check .
```

Check Ruff formatting without changing files:

```bash
UV_PROJECT_ENVIRONMENT="$HOME/.local/share/matchpatch/.venv-wsl" \
  uv run --no-default-groups --group wsl \
  ruff format --check .
```

Run `ty` package type checks:

```bash
UV_PROJECT_ENVIRONMENT="$HOME/.local/share/matchpatch/.venv-wsl" \
  uv run --no-default-groups --group wsl \
  ty check
```

Install the Git hooks after synchronizing the WSL environment:

```bash
UV_PROJECT_ENVIRONMENT="$HOME/.local/share/matchpatch/.venv-wsl" \
  uv run --no-default-groups --group wsl \
  pre-commit install --install-hooks
```

This installs commit and push hooks. Commits run repository hygiene checks,
Ruff linting, Ruff formatting validation, and `ty`. Pushes additionally run the
pytest suite. Run every hook manually with:

```bash
UV_PROJECT_ENVIRONMENT="$HOME/.local/share/matchpatch/.venv-wsl" \
  uv run --no-default-groups --group wsl \
  pre-commit run --all-files --hook-stage pre-push
```

GitHub Actions runs Ruff linting, Ruff formatting checks, `ty`, and pytest on
Python 3.12, 3.13, and 3.14 across Linux, native Windows, and Ubuntu on WSL.

Release tags matching the package version, such as `v0.1.0`, trigger a
tokenless PyPI trusted-publishing workflow. Configure the GitHub `pypi`
environment and register `.github/workflows/release.yml` as a trusted
publisher for the `matchpatch` project on PyPI before publishing the first tag.

The separate environment directories are intentional. Linux and Windows
virtual environments cannot be shared, even though they are managed from the
same project metadata and lockfile. The WSL environment lives on the native
Linux filesystem because Linux virtual environments cannot be created reliably
inside the Windows-mounted repository.

The primary package command selects an audio processor profile explicitly:

```bash
matchpatch normalize --device helix -i setlist_original.hls -o setlist_adjusted.hls
```

List the installed profiles:

```bash
matchpatch --devices
```

The first supported profile is `helix`. Its legacy utility scripts work on:

- `.hls`: Helix setlist files
- `.hlx`: Helix preset files

Some utility scripts also work with unpacked `.json` files. When an `.hlx` file
is used as input, the output must also be `.hlx`; the tools intentionally do not
write `.hls` or `.json` from `.hlx` input.

Run commands from the project root:

```bash
python3 Python/<script>.py --help
```

## File Rules

- `.hls` files contain multiple presets.
- `.hlx` files contain one preset.
- Operations that modify every preset in a `.hls` file modify only the single
  preset in an `.hlx` file.
- For `adjust_gain.py`, `.hlx` input requires exactly one `-S/--preset-set`
  value, for example `-S 12A`. This tells MatchPatch which Helix slot contains
  the imported preset during measurement.

## Typical Workflow

Create a reamp version of a setlist:

```bash
python3 Python/preset_handling.py -i setlist_original.hls -o setlist_reamp.hls -r
```

Import the reamp file into the Helix, measure it with the native Windows
MatchPatch worker, then apply the generated LUFS CSV:

```bash
python3 Python/preset_handling.py \
  -i setlist_original.hls \
  -o setlist_adjusted.hls \
  --adjust-gain \
  -g helix_gain/lufs_analysis.csv
```

Or run the automated workflow:

```bash
python3 Python/adjust_gain.py -a -i setlist_original.hls
```

For a single preset:

```bash
python3 Python/adjust_gain.py -a -i "Entre dos Tierra.hlx" -S 12A
```

## Python Scripts

### `preset_handling.py`

General Helix file utility. It can convert inputs/outputs for reamping/stage
use, list presets, and apply LUFS-derived gain corrections.

Usage:

```bash
python3 Python/preset_handling.py -i INPUT [-o OUTPUT] MODE [options]
```

Modes:

- `-r`, `--reamp`: convert Multi/XLR style live routing to USB reamp routing.
- `-s`, `--stage`: convert USB reamp routing back to stage routing.
- `-a`, `--adjust-gain`: apply gain corrections from a LUFS CSV.
- `--list-presets`: print non-default preset assignments as JSON.

Examples:

```bash
python3 Python/preset_handling.py -i setlist_original.hls --list-presets
python3 Python/preset_handling.py -i setlist_original.hls -o setlist_reamp.hls -r
python3 Python/preset_handling.py -i setlist_reamp.hls -o setlist_stage.hls -s
python3 Python/preset_handling.py -i song.hlx -o song_reamp.hlx -r
python3 Python/preset_handling.py -i song.hlx -o song_adjusted.hlx --adjust-gain -g lufs_analysis.csv
python3 Python/preset_handling.py -i song.hlx -o song_adjusted.hlx --adjust-gain -g lufs_analysis.csv --target-lufs -18
```

Notes:

- `.hlx` input can only produce `.hlx` output.
- In `.hlx` gain adjustment, the LUFS CSV must contain exactly one preset row.
- Measurements include `CrestFactor1` through `CrestFactor4`.
  Compressed snapshots receive a crest-factor correction:
  `LUFS alignment gain - clamp((12 - crest factor dB) * 0.4, 0, 3)`.
- Gain residuals up to `0.25 dB` are treated as stable to avoid repeated
  adjustments caused by normal measurement variance.
- Snapshot names containing `solo` case-insensitively receive the solo gain
  bump.

### `adjust_gain.py`

Runs the full gain measurement workflow with the native Windows Python worker
and the Helix.

Usage:

```bash
python3 Python/adjust_gain.py -i INPUT [-o OUTPUT] [options]
python3 Python/adjust_gain.py -a -i INPUT [options]
```

Important options:

- `-a`, `--automation`: create a reamp file, wait for import, run native
  Windows analysis, then create the adjusted output.
- `-o`, `--output`: output file when not using automation.
- `-S`, `--preset-set`: comma-separated Helix preset IDs, such as
  `01B,02A,16D`.
- `-n`, `--limit`: only analyze the first N detected presets.
- `--timeout`: maximum seconds to wait for native Windows analysis.
- `--keep-temp`: keep the temporary CSV and done marker.
- `--ignore-bad-lufs`: skip implausible LUFS-derived gain values.
- `--target-lufs`: target average short-term LUFS value for gain adjustment.
- `--windows-python`: WSL path to the uv-managed native Windows Python.
- `--reference-di`: reference guitar DI WAV file.
- `--audio-device`: unique substring or numeric ID for the Helix ASIO device.
- `--midi-output`: unique substring for the Helix MIDI output.
- `--input-mapping`: ASIO recording channels, default `1,2` for USB 1/2.
- `--output-mapping`: ASIO playback channels, default `3,4` for USB 3/4.

Examples:

```bash
python3 Python/adjust_gain.py -a -i setlist_original.hls
python3 Python/adjust_gain.py -a -i setlist_original.hls -S 01A,01B,02A
python3 Python/adjust_gain.py -a -i setlist_original.hls -n 8 --keep-temp
python3 Python/adjust_gain.py -a -i setlist_original.hls --target-lufs -18
python3 Python/adjust_gain.py -a -i "Entre dos Tierra.hlx" -S 12A
python3 Python/adjust_gain.py -i setlist_original.hls -o setlist_adjusted.hls -S 01A --timeout 300
```

Notes:

- Automation writes `*_reamp.hls`/`*_reamp.hlx` and
  `*_adjusted.hls`/`*_adjusted.hlx`.
- With `.hlx` input, `-S` is required and must contain exactly one preset ID.
- The WSL script invokes `.venv-windows/Scripts/python.exe` directly. The
  native worker owns ASIO, MIDI, playback, recording, and measurement.

### `list_cab_presets.py`

Lists presets that contain isolated cab blocks.

Usage:

```bash
python3 Python/list_cab_presets.py -i INPUT
```

Examples:

```bash
python3 Python/list_cab_presets.py -i setlist_original.hls
python3 Python/list_cab_presets.py -i song.hlx
```

### `replace_amp.py`

Replaces amp+cab blocks with equivalent amp-only blocks by removing the embedded
cab assignment.

Usage:

```bash
python3 Python/replace_amp.py -i INPUT -o OUTPUT
```

Examples:

```bash
python3 Python/replace_amp.py -i setlist_original.hls -o setlist_amp_only.hls
python3 Python/replace_amp.py -i song.hlx -o song_amp_only.hlx
```

### `remove_inactive_blocks.py`

Removes blocks that are inactive in the first four snapshots, except blocks with
expression-pedal controller assignments.

Usage:

```bash
python3 Python/remove_inactive_blocks.py -i INPUT -o OUTPUT
```

Examples:

```bash
python3 Python/remove_inactive_blocks.py -i setlist_original.hls -o setlist_cleaned.hls
python3 Python/remove_inactive_blocks.py -i song.hlx -o song_cleaned.hlx
```

### `reset_output_levels.py`

Sets active output block gains and snapshot-assigned output gains to `0.0 dB`.

Usage:

```bash
python3 Python/reset_output_levels.py -i INPUT -o OUTPUT
```

Examples:

```bash
python3 Python/reset_output_levels.py -i setlist_original.hls -o setlist_zero_outputs.hls
python3 Python/reset_output_levels.py -i song.hlx -o song_zero_outputs.hlx
```

### `stereofy.py`

Turns blocks after cab or IR blocks stereo where the conversion can be identified
safely.

Usage:

```bash
python3 Python/stereofy.py -i INPUT -o OUTPUT
```

Examples:

```bash
python3 Python/stereofy.py -i setlist_original.hls -o setlist_stereo.hls
python3 Python/stereofy.py -i song.hlx -o song_stereo.hlx
```

### `decrypt_hls.py`

Unpacks a Helix `.hls` file to JSON. For `.hlx` input, it validates and copies
the preset to another `.hlx` file.

Usage:

```bash
python3 Python/decrypt_hls.py -i INPUT -o OUTPUT
```

Examples:

```bash
python3 Python/decrypt_hls.py -i setlist_original.hls -o setlist_original.json
python3 Python/decrypt_hls.py -i song.hlx -o song_copy.hlx
```

### `encrypt_hls.py`

Packs an unpacked JSON file into a Helix `.hls` file. For `.hlx` input, it
validates and copies the preset to another `.hlx` file.

Usage:

```bash
python3 Python/encrypt_hls.py -i INPUT -o OUTPUT
```

Examples:

```bash
python3 Python/encrypt_hls.py -i setlist_original.json -o setlist_repacked.hls
python3 Python/encrypt_hls.py -i song.hlx -o song_copy.hlx
```

## Device Profiles

Processor-specific behavior lives under `src/matchpatch/devices/`. A supported
profile supplies:

- A patch-file handler for setlist and preset files.
- A steering controller for preset and snapshot selection.
- Default USB recording and playback channels.

The normalization orchestration and `loopback` backend do not contain
processor-specific logic. To add another audio processor, implement a
`DeviceProfile`, `PatchFileHandler`, and `DeviceController`, then register the
profile in `src/matchpatch/devices/registry.py`.

The `helix` profile adapts the proven `.hls` and `.hlx` implementation from
`Python/preset_handling.py`. Its controller sends MIDI Program Change messages
for presets and CC `69` for snapshots.

## Native Windows Measurement

REAPER is no longer required for gain measurement. MatchPatch keeps
orchestration and preset file processing in WSL while a native Windows Python
worker communicates with the selected processor's audio driver and steering
transport.

Synchronize both uv-managed environments:

```bash
scripts/sync-wsl.sh
scripts/sync-windows-from-wsl.sh
```

List the Windows audio host APIs, audio devices, and MIDI outputs:

```bash
scripts/measure-windows-from-wsl.sh devices
```

When hardware is not connected, test the native Windows measurement worker with
an in-process loopback backend. It simulates an empty patch by feeding the
reference DI directly into the analyzer:

```bash
scripts/measure-windows-from-wsl.sh measure \
  --device helix \
  --backend loopback \
  --preset-ids 1,2 \
  --csv "$(wslpath -w "$PWD/loopback_analysis.csv")" \
  --reference-di "$(wslpath -w "$PWD/Reaper/Referenz_Gitarre_DI_Strandberg_Boden_Fusion_Bridge_Humbucker_short.wav")"
```

The complete WSL orchestration can use the same backend:

```bash
matchpatch normalize \
  --device helix \
  -i setlist_original.hls \
  -o setlist_loopback_adjusted.hls \
  -S 01A \
  --backend loopback \
  --keep-temp
```

The measurement worker defaults to:

| Purpose | Helix USB channels |
|---|---|
| Processed audio recording | USB 1/2 |
| Reference DI playback | USB 3/4 |

If the Helix ASIO or MIDI names are ambiguous, pass a unique device substring
or numeric audio device ID:

```bash
matchpatch normalize --device helix -a -i setlist_original.hls \
  --audio-device "Helix ASIO" \
  --midi-output "Helix"
```

The historical files in `Reaper/` remain as references while the native
measurement results are calibrated against the previous workflow.

## Safety Notes

- Keep backups of original `.hls` and `.hlx` files.
- Import generated reamp files into the Helix only when you are ready to run the
  measurement workflow.
- The scripts skip presets named `New Preset`.
- `.hlx` workflows operate on one preset only and require `.hlx` output.
