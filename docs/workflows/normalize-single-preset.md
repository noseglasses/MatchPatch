(help-normalize-single-preset)=
# Normalize A Single Preset

Use this workflow when you have one Helix `.hlx` or Pod Go `.pgp` preset instead
of a full setlist.

If you have several single-preset files for the same device family and want to
work on them together, select all of those files in File > Open. MatchPatch will
show them as a temporary setlist in the preset table. In that mode, Save writes
the edited presets back to their original files, while Save As writes one
matching setlist.

A single preset file does not know where it will live on the processor.
MatchPatch therefore needs a temporary device slot for measurement.

## Before You Start

- Back up the original `.hlx` or `.pgp` file.
- Choose a temporary device slot you can safely use.
- Choose a reference DI.
- Decide whether this is a hardware run or a no-hardware test.
- If using hardware mode, connect and power on the processor.

Valid slot examples:

```text
01A
12A
32D
```

## Steps

1. Open MatchPatch.
2. Open the `.hlx` or `.pgp` preset.
3. Find the Preset column in the table.
4. Enter the temporary device slot, such as `12A`.
5. Open Advanced.
6. Choose the backend in the Device tab.
7. Check the Reference DI in the Files tab.
8. Set target LUFS, solo boost, and snapshot rules if needed.
9. Check snapshot count in the Misc tab.
10. If using hardware, place or import the preset into the temporary device slot
    when the workflow requires it.
11. Click Start normalization.
12. Follow any import prompts.
13. Review the snapshot results.
14. Save or Save As.
15. Import the saved adjusted preset back into the matching processor.


(help-single-preset-table-legend)=
## Preset Table Legend

Use the Show legend button under the preset table to display the current table
legend.

## Temporary Slot Safety

The temporary slot tells MatchPatch where to steer the processor during
measurement.

Choose a slot you can safely overwrite or temporarily use. Do not use a live
preset slot unless you have a backup.

> Warning:
> If you choose an important live slot on the processor, you may overwrite or replace
> something you meant to keep.

## If The Slot Is Missing

MatchPatch will warn you before running. Enter exactly one device slot in the
Preset column.

The valid range is `01A` through `32D`.

## What Success Looks Like

- The temporary slot is accepted.
- The preset measures without unexpected red cells.
- The snapshot gain changes look sensible.
- Save or Save As writes an adjusted preset file.
- The adjusted preset sounds balanced after import.

## If Something Goes Wrong

- If the slot is rejected, check the format: two digits plus A, B, C, or D.
- If hardware is not found, read [Hardware Measurement](hardware-measurement.md).
- If results are red, read [Troubleshooting](../troubleshooting.md).

See also: [Measurement And Adjusted Files](../concepts/measurement-and-adjusted-files.md).
