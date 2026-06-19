# File Formats

This document describes the file formats MatchPatch currently reads or writes
for supported Line 6 normalization and measurement workflows.

## Helix `.hls` Setlists

`.hls` files are Line 6 Helix setlists. MatchPatch treats them as JSON wrapper
files containing compressed setlist JSON.

The wrapper includes:

- `encoded_data`: base64-encoded zlib-compressed JSON text.
- compression metadata such as `decompressed_size` and `crc32`.

`matchpatch.devices.helix.preset_handling` decodes `encoded_data`, edits the
decompressed JSON, then rebuilds the wrapper by replacing `encoded_data`,
`decompressed_size`, and `crc32`. Other wrapper fields are preserved.

The decompressed setlist JSON is expected to contain a `presets` list. Each
non-empty preset is assigned an internal numeric ID starting at `1`, and a Helix
slot label derived from zero-based position:

```text
1 -> 01A
2 -> 01B
3 -> 01C
4 -> 01D
5 -> 02A
```

Default/empty presets are skipped when listing setlist assignments. A preset is
considered non-empty if its `tone` contains at least one `block*` entry under
`dsp0` or `dsp1`.

## Helix `.hlx` Presets

`.hlx` files are single Helix presets stored as JSON. MatchPatch accepts either:

- a top-level preset object containing `tone`, or
- a wrapper object containing a preset object in `data`.

Internally, the Helix utility wraps a single preset as:

```text
{"presets": [preset]}
```

This lets setlist and single-preset code share most processing. When saving, the
single preset is unwrapped again. If the input used a `data` wrapper, the saved
file preserves that wrapper and replaces only `data`.

Unlike `.hls`, a `.hlx` file does not encode its target hardware slot. CLI
measurement therefore requires exactly one `--preset-set`/`-S` value, such as
`12A`, so the worker knows which temporary Helix slot to steer during
measurement.

The GUI can open several `.hlx` files in one File > Open selection. That mode is
implemented by joining the selected presets into a temporary `.hls` setlist so
the existing preset-table and measurement workflow can operate on the group.
Saving with Save splits the temporary setlist back into the original `.hlx`
files. Saving with Save As writes the temporary setlist as a normal `.hls` file.

## Unpacked `.json`

The Helix utility can also read and write unpacked JSON for selected
utility modes. The modern `HelixPatchFileHandler` only accepts `.hls` and
`.hlx` as normal workflow inputs and requires output files to use the same
extension as the input.

## Pod Go `.pgs` Setlists

`.pgs` files are Line 6 Pod Go setlists. They use the same `L6Setlist` wrapper
shape as Helix setlists: `encoded_data` contains base64 zlib-compressed JSON,
and the compression metadata includes `decompressed_size` and `crc32`.

The decoded setlist JSON contains 128 banked presets. MatchPatch labels those
slots `01A` through `32D`, with internal preset ID `1` mapping to `01A` and
internal preset ID `128` mapping to `32D`.

## Pod Go `.pgp` Presets

`.pgp` files are single Line 6 Pod Go presets. MatchPatch expects a wrapper with
schema `L6Preset` and a preset object in `data`. Internally, single presets are
wrapped as `{"presets": [preset]}` so setlist and preset processing can share
the same path.

Like `.hlx`, a `.pgp` file does not encode its target hardware slot. CLI
measurement therefore requires exactly one `--preset-set`/`-S` value, such as
`12A`, so the worker knows which temporary Pod Go slot to steer during
measurement.

## Measurement Files

Measurement conversion rewrites processor routing so the device can be measured
over USB. For Helix:

- Inputs that use Multi are changed to USB `3/4`.
- Final outputs are changed to USB `1/2`.
- Snapshot-assigned parameters are normalized so the current snapshot values are
  represented consistently.

These generated measurement `.hls`/`.hlx` files are temporary workflow files.
They are meant to be imported for measurement, not used as stage presets.

For Pod Go, MatchPatch changes the Pod Go input to USB `3/4` and output to USB
`1/2`, then restores the stage routing when requested. Generated measurement
`.pgs`/`.pgp` files are also temporary workflow files.

## Adjusted Files

Adjusted files preserve the input file type. Helix gain application:

- Finds one active final output block per preset.
- Ensures output gain is snapshot-controlled.
- Converts adjusted final output routing to XLR.
- Applies per-snapshot output gain deltas.
- Leaves snapshots with `ERROR` or implausible measurements unchanged when bad
  LUFS tolerance is enabled.

Helix name edits are validated against the hardware-safe character set:

```text
[A-Za-z0-9\-_+=!@#$&()?:'",./ ]
```

Current Helix limits are 16 characters for preset names and 10 characters for
snapshot names.

Pod Go gain application adjusts the `dsp0.output.gain` snapshot value and
supports up to 4 snapshots per preset. Pod Go currently uses the same Line 6
name character set and configured name length limits as Helix in MatchPatch.

## Measurement CSV: Generic

The native measurement worker writes the canonical generic CSV. The default
temporary filename is `lufs_analysis.csv`.

For `N` measured snapshots, the columns are:

```text
Preset,DevicePatch,LUFS1..LUFSN,CrestFactor1..CrestFactorN
```

Example for two snapshots:

```text
Preset,DevicePatch,LUFS1,LUFS2,CrestFactor1,CrestFactor2
1,01A,-16.2,-13.7,11.8,10.4
6,02B,-18.0,-15.0,12.5,12.1
```

Field meaning:

- `Preset`: internal numeric preset ID, starting at `1`.
- `DevicePatch`: device-facing patch label, such as `01A`.
- `LUFS#`: measured average short-term LUFS for one-based snapshot `#`.
- `CrestFactor#`: measured crest factor in dB for one-based snapshot `#`.

If measurement of a preset fails, each LUFS and crest factor field for that row
is written as `ERROR`.

CSV files are written with UTF-8 and read with UTF-8-SIG so a BOM is tolerated.

## Measurement CSV: Helix Legacy Adapter

The shared Line 6 file handler writes a temporary adapter CSV before invoking
packaged utility modules that expect a legacy `HelixPreset` column instead of
`DevicePatch`.

Its columns are:

```text
Preset,HelixPreset,<all other measurement columns except DevicePatch>
```

This file is an implementation detail and is deleted after gain application.
When documenting or debugging user-visible measurement results, prefer the
generic `DevicePatch` form.

## GUI Save CSV

The GUI can save and load the preset table as a user-editable CSV. It uses a
pipe delimiter because `|` is not part of the allowed Helix name character set.

For `N` snapshots, headers are:

```text
preset_id|preset_name|snapshot_1_name|snapshot_1_adjustment|...|snapshot_N_name|snapshot_N_adjustment
```

Rows are keyed by the displayed preset ID. Loading applies only rows whose
preset ID exists in the currently loaded table. Preset and snapshot names are
validated with Helix character and length rules. Adjustment cells must parse as
finite floats. All row-level parse failures are reported in the GUI log and in
an error popup.

Adjustment cells may display custom adjustment annotations in parentheses in the
GUI, but the exported numeric delta is the actual manual/export delta.

## GUI Synthetic Save CSV

When the GUI saves an adjusted file without a retained measurement CSV, it can
create a temporary `*.matchpatch-save.csv` beside the destination. This CSV has
the same shape expected by the gain-application path, but it contains target
values derived from the current preset table:

```text
DevicePatch,LUFS1,CrestFactor1,...,LUFSN,CrestFactorN
```

Each LUFS field is populated with the current target LUFS, and each crest factor
field is populated with `12.0`. The file is temporary and removed after export.

## Custom Adjustments CSV

A custom adjustment CSV lets users bump or lower the target loudness of specific
presets/snapshots. For `N` measured snapshots, each non-empty row must contain
exactly `N + 1` columns:

```text
PresetID,Snapshot1Bump,Snapshot2Bump,...,SnapshotNBump
```

Both comma and pipe delimiters are accepted. The first column is a device patch
ID such as `01A`; it is normalized to uppercase. Remaining columns are optional
finite float values in dB. Empty cells mean no custom adjustment for that
snapshot. Duplicate preset IDs are rejected.

Example:

```text
01A,0.0,1.5,,-2.0
02B|0.5||||
```

The value is added on top of the normal target calculation for that
preset/snapshot.

## Manual Adjustments JSON

The GUI passes manual table edits to the device utility module as temporary
JSON, not CSV. The payload can contain:

```json
{
  "preset_names": {"01A": "Song Name"},
  "snapshot_names": {"01A": {"0": "Verse"}},
  "gain_deltas": {"01A": {"0": -1.5}}
}
```

Snapshot keys are zero-based strings. Manual gain deltas override computed
deltas for matching snapshots.

## Diff Selection

Setlist diff selection compares current and previous files of the same type.
The comparison removes non-signal content before comparing presets, including
names, metadata, and color fields. Presets are selected when loudness-affecting
signal content differs. This feature is implemented by the Line 6 utility
modules and surfaced through `--diff-input` and the GUI diff button.
