# Auto_Pegelsetup

Command line tools for analyzing and modifying Line 6 Helix setlist and preset
files.

Most scripts work on:

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
  value, for example `-S 12A`. This tells REAPER which Helix slot contains the
  imported preset during measurement.

## Typical Workflow

Create a reamp version of a setlist:

```bash
python3 Python/preset_handling.py -i setlist_original.hls -o setlist_reamp.hls -r
```

Import the reamp file into the Helix, measure it with REAPER, then apply the
generated LUFS CSV:

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
- New REAPER measurements include `CrestFactor1` through `CrestFactor4`.
  Compressed snapshots receive a crest-factor correction:
  `LUFS alignment gain - clamp((12 - crest factor dB) * 0.4, 0, 3)`.
- Gain residuals up to `0.25 dB` are treated as stable to avoid repeated
  adjustments caused by normal measurement variance.
- Snapshot names containing `solo` case-insensitively receive the solo gain
  bump.

### `adjust_gain.py`

Runs the full gain measurement workflow with REAPER and the Helix.

Usage:

```bash
python3 Python/adjust_gain.py -i INPUT [-o OUTPUT] [options]
python3 Python/adjust_gain.py -a -i INPUT [options]
```

Important options:

- `-a`, `--automation`: create a reamp file, wait for import, run REAPER
  analysis, then create the adjusted output.
- `-o`, `--output`: output file when not using automation.
- `-S`, `--preset-set`: comma-separated Helix preset IDs, such as
  `01B,02A,16D`.
- `-n`, `--limit`: only analyze the first N detected presets.
- `--timeout`: maximum seconds to wait for REAPER analysis.
- `--keep-temp`: keep the temporary CSV and done marker.
- `--ignore-bad-lufs`: skip implausible LUFS-derived gain values.
- `--target-lufs`: target average short-term LUFS value for gain adjustment.
- `--reaper-exe`: path to `reaper.exe`.
- `--project`: REAPER project to open.

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
- The REAPER process started by this script is asked to close automatically
  after the analysis is done.

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

## REAPER Integration

`adjust_gain.py` launches:

- `Reaper/Auto_Pegelsetup.rpp`
- `Reaper/HelixAnalyzeSet.lua`

The script passes the preset set, CSV path, and done marker through environment
variables. When the REAPER analysis is complete, the Lua script writes the done
marker and asks the launched REAPER instance to quit.

The default REAPER executable path is:

```text
/mnt/c/Program Files/REAPER (x64)/reaper.exe
```

Override it if needed:

```bash
python3 Python/adjust_gain.py -a -i setlist_original.hls --reaper-exe "/mnt/c/Program Files/REAPER (x64)/reaper.exe"
```

## Safety Notes

- Keep backups of original `.hls` and `.hlx` files.
- Import generated reamp files into the Helix only when you are ready to run the
  measurement workflow.
- The scripts skip presets named `New Preset`.
- `.hlx` workflows operate on one preset only and require `.hlx` output.
