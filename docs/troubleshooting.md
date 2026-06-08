# Troubleshooting

Most MatchPatch problems come from one of four places:

- the wrong backend;
- missing or wrong hardware routing;
- a missing reference DI;
- a snapshot recording silence or unstable audio.

Start with the checklist below, then find the problem that matches what you see.

## Start Here

1. Confirm the correct backend:
   - loopback for testing without Helix;
   - hardware for real Helix measurement.
2. If using hardware, confirm the Helix is connected and powered on.
3. Confirm the Reference DI path points to an existing WAV.
4. Confirm playback and recording channels match your Helix routing.
5. Confirm MIDI output and MIDI channel are correct.
6. Confirm selected presets have snapshots that are not all ignored.
7. If using a single `.hlx`, confirm the temporary slot is filled in.

## Red Highlighted Rows

### What You See

One or more preset rows or snapshot cells are red after measurement.

### Likely Cause

MatchPatch could not safely calculate a normal adjustment. It may have recorded
silence, received unusable loudness data, or calculated an output level outside
the Helix range.

### What To Try

1. Open the Log tab and look for the warning.
2. Check whether the snapshot recorded silence.
3. Check audio routing.
4. Use the recorded-output playback button if available.
5. Rerun the preset after fixing routing or timing.
6. If the tone really needs a special level, use manual editing or custom
   adjustments.

See [Reading Results](concepts/reading-results.md).

[Screenshot placeholder: Bad LUFS highlighted row]
[Screenshot placeholder: Measurement failed adjustment cell]

> Warning:
> Do not keep raising output levels blindly after a failed measurement. First
> find out why the measurement failed.

## No Suitable Device Connected

### What You See

The GUI shows a hardware error, or measurement does not start in hardware mode.

### Likely Cause

MatchPatch cannot see the Helix audio device, MIDI output, or native hardware
setup.

### What To Try

1. Check that the Helix is powered on.
2. Check the USB cable.
3. Check that the Helix appears as an audio device.
4. Check that the Helix appears as a MIDI output.
5. In Advanced > Device, make the Audio device and MIDI output names more
   specific.
6. If you only want to learn the app, switch Backend to `loopback`.

[Screenshot placeholder: Hardware error popup]

See [Hardware Measurement](workflows/hardware-measurement.md).

## Native Windows Environment Missing

### What You See

Hardware mode fails when running from WSL or a Linux-side setup.

### Likely Cause

The Windows audio/MIDI environment needed for hardware measurement is not ready.

### What To Try

If you are not comfortable with command-line setup, ask the person who installed
MatchPatch to prepare the Windows runtime.

If you only want to continue learning the GUI, switch to loopback mode.

See [Test Without Hardware](workflows/test-without-hardware.md).

## Reference DI File Missing

### What You See

MatchPatch says the Reference DI WAV does not exist.

### Likely Cause

The file path in Advanced > Files points to a missing or moved WAV.

### What To Try

1. Open Advanced > Files.
2. Click Browse beside Reference DI.
3. Choose an existing WAV file.
4. Start again.

See [Reference DI](concepts/reference-di.md).

## Reference DI Sample Rate Mismatch

### What You See

Measurement starts but fails with a sample-rate message.

### Likely Cause

The reference DI WAV sample rate does not match the configured audio sample
rate.

### What To Try

1. Use a reference DI recorded at the same sample rate as the Helix audio setup.
2. Or change the Sample rate in Advanced > Device to match the WAV and hardware.
3. Try again.

## Audio Device Not Found Or Ambiguous

### What You See

MatchPatch cannot find the audio device, or says the audio device match is
ambiguous.

### Likely Cause

The Audio device field is empty, too broad, or does not match the device name.

### What To Try

1. Open Advanced > Device.
2. Make the Audio device field more specific.
3. If multiple similar devices are visible, use the exact name shown by your
   system.
4. Reconnect the Helix and restart the app if the device list changed.

## Wrong Channel Mapping

### What You See

Measurements are silent, wrong, or fail with bad LUFS.

### Likely Cause

The reference DI is going to the wrong playback channels, or MatchPatch is
recording the wrong return channels.

### What To Try

1. Open Advanced > Device.
2. Check Recording channels.
3. Check Playback channels.
4. Try the normal Helix idea:
   - Recording channels: `1,2`;
   - Playback channels: `3,4`.
5. Use recorded-output playback to confirm signal.

See [Routing And Levels](concepts/routing-and-levels.md).

> Warning:
> Wrong channels can record silence and create misleading loudness numbers.

## No Measurable Presets

### What You See

MatchPatch says there are no measurable presets or snapshots.

### Likely Cause

All selected presets are empty, all selected snapshots are ignored, or the preset
selection does not match the loaded file.

### What To Try

1. Check that presets are selected.
2. Check that the ignored snapshot rule is not skipping everything.
3. Check the snapshot count.
4. Select a known non-empty preset.
5. Try again.

See [Snapshots, Solos, And Ignored Snapshots](concepts/snapshots-solos-and-ignored.md).

## `.hlx` Temporary Slot Missing

### What You See

The GUI warns that a preset ID is required, or highlights the Preset cell.

### Likely Cause

A single `.hlx` preset needs one temporary Helix slot for measurement.

### What To Try

1. Click the Preset cell.
2. Enter one slot, such as `12A`.
3. Use a slot from `01A` through `32D`.
4. Start again.

[Screenshot placeholder: Missing preset ID highlight for .hlx]

See [Normalize A Single Preset](workflows/normalize-single-preset.md).

## Output File Extension Mismatch

### What You See

MatchPatch refuses to save the file.

### Likely Cause

The saved file extension does not match the input.

### What To Try

- Save `.hls` setlists as `.hls`.
- Save `.hlx` presets as `.hlx`.
- Use Save As and choose a matching filename.

See [Save And Import Files](workflows/save-and-import.md).

## Diff Input Must Use Same File Type

### What You See

Select changed or diff selection fails.

### Likely Cause

The previous file does not have the same extension as the current file.

### What To Try

1. Open the current `.hls` setlist.
2. Click Select changed.
3. Choose an older `.hls` version of that same setlist.

See [Select Changed Presets](workflows/select-changed-presets.md).

## Invalid Helix Name

### What You See

A table edit or CSV import complains about a Helix name.

### Likely Cause

The preset or snapshot name contains a character the Helix file workflow does
not allow, or the name is too long.

### What To Try

1. Use shorter names.
2. Avoid unusual symbols.
3. Use letters, numbers, spaces, and common punctuation.
4. For snapshot names, keep names very short.

See [Manual Editing And CSV](workflows/manual-editing-and-csv.md).

## Bad LUFS Or Measurement Unavailable

### What You See

The table shows a failed measurement, bad LUFS warning, or measurement
unavailable warning.

### Likely Cause

MatchPatch did not get usable loudness data.

Common reasons:

- silence was recorded;
- wrong USB channels;
- the Helix did not switch as expected;
- the reference DI did not reach the Helix;
- the measured audio was too short for the analysis window;
- timing was too fast for effect trails.

### What To Try

1. Check routing.
2. Check the Reference DI.
3. Use recorded-output playback.
4. Use Default timing instead of Fast.
5. Increase snapshot wait for presets with long trails.
6. Rerun the affected preset.

See [Measurement Timing](concepts/timing.md).

## Implausible Output Gain

### What You See

MatchPatch warns that the resulting output level would be outside the Helix
range.

### Likely Cause

The measurement was probably invalid, often because silence was recorded.

### What To Try

1. Check routing first.
2. Check that the preset produces sound.
3. Check that the output block is active.
4. Rerun the preset.
5. If the preset is intentionally strange, use manual editing carefully.

## Fast Timing Feels Unstable

### What You See

Measurements vary between runs, or snapshots with delay/reverb produce strange
results.

### Likely Cause

Timing is too fast. One snapshot's trails may still be ringing during the next
snapshot's measurement.

### What To Try

1. Use the Default timing preset.
2. Increase snapshot wait or measurement wait.
3. Run Determine optimal parameters.

See [Optimize Timing](workflows/optimize-timing.md).

## GUI Does Not Start On WSL

### What You See

The GUI fails to open from a WSL setup.

### Likely Cause

The graphical desktop support is not available or the required GUI packages are
missing.

### What To Try

1. If you are not technical, ask the person who installed MatchPatch to check
   WSLg or GUI package setup.
2. If you only need hardware measurement, consider running MatchPatch from the
   prepared Windows environment.

## Preset Table CSV Import Errors

### What You See

Loading a table CSV shows an error popup.

### Likely Cause

The CSV does not match the current table.

### What To Try

1. Open the same setlist the CSV came from.
2. Make sure the snapshot count is the same.
3. Make sure preset IDs still exist in the table.
4. Check that gain values are numbers.
5. Check that names are short and Helix-safe.

[Screenshot placeholder: CSV error popup]

See [Manual Editing And CSV](workflows/manual-editing-and-csv.md).

## Custom Adjustment CSV Errors

### What You See

The custom adjustment file is rejected.

### Likely Cause

The file has the wrong number of columns, a duplicate preset ID, an empty preset
ID, or a non-number adjustment.

### What To Try

1. Make one row per preset.
2. Put the preset slot first, such as `01A`.
3. Add one value column per measured snapshot.
4. Leave cells empty when no custom adjustment is needed.
5. Use small number values, such as `1.5` or `-2`.

See [Custom Adjustments](workflows/custom-adjustments.md).

## What To Listen For After Saving

After importing the adjusted file, play through the real setlist.

Listen for:

- rhythm presets that still jump out;
- leads that still disappear;
- clean sounds that feel too quiet;
- special effects that should be skipped;
- snapshot changes that feel unnatural.

If only one snapshot needs a small change, use manual editing or a custom
adjustment.

## When To Rerun Measurement

Rerun measurement when:

- routing was wrong;
- the Helix was not connected correctly;
- a red row was caused by silence;
- timing was too fast;
- you changed the preset tone;
- you changed the reference DI.

[Screenshot placeholder: Log tab with warning filter]
