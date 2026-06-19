# Test Without Hardware

Use this workflow when you want to learn MatchPatch without connecting a Helix or
Pod Go.

This is the safest first run. It lets you practice opening files, selecting
presets, starting measurement, reading the table, and saving.

## Before You Start

- Have a Helix `.hls`/`.hlx` or Pod Go `.pgs`/`.pgp` file available.
- Make a backup of that file.
- Have a reference DI selected, or use the default one.
- Choose which no-hardware mode you want:
  - Loopback for the simplest test.
  - Simulated for a fake processor-style test.

See also: [Backends](../concepts/backends.md).

## Loopback Mode

Loopback mode measures the reference DI directly. It does not measure your
processor, and it does not tell you how balanced your real presets are.

Use loopback when you want to practice the app quickly.

## Simulated Mode

Simulated mode pretends to be a processor. It can show more varied result-table
changes than loopback, but it is still not your real processor.

Use simulated mode when you want to test the workflow without hardware but still
see fake preset and snapshot differences.

## Steps

1. Open MatchPatch.
2. Open a supported setlist or preset.
3. Open Advanced.
4. Go to the Device tab.
5. Set Backend to `loopback` or `simulated`.
6. If using a setlist, choose the presets you want to test.
7. If using a single preset file, enter a temporary slot such as `12A` in the
   Preset column.
8. Check the Reference DI field in Advanced > Files.
9. Click Start normalization.
10. Watch the progress area and result table.
11. Save only if you intentionally want to test the save workflow.

> Warning:
> Even in a no-hardware test, keep a backup before testing Save or Save As.

## What Success Looks Like

- The app starts measurement without asking for real hardware.
- The progress area moves through the selected presets and snapshots.
- The table shows output/gain results.
- There are no unexpected red warning rows.

## If Something Goes Wrong

- If MatchPatch asks for hardware, check that Backend is `loopback` or
  `simulated`.
- If the file does not open, confirm it is a supported Helix or Pod Go file.
- If a single preset will not run, enter a temporary slot such as `12A`.
- If rows are red, read [Troubleshooting](../troubleshooting.md).

## What The Results Mean

Loopback and simulated results prove that the workflow runs. They do not prove
that your real processor presets are balanced.

For final gig or rehearsal levels, run [Hardware Measurement](hardware-measurement.md).

> Warning:
> Do not judge your live processor preset balance from loopback or simulated mode.
