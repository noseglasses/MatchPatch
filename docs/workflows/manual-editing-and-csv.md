# Manual Editing And CSV

Use this workflow when you want to adjust names or gain results by hand.

Manual editing is useful after a failed measurement, when you want a small
musical exception, or when you want to clean up preset and snapshot names before
saving.

## Before You Start

- Open a Helix setlist or preset.
- Back up the original file.
- Run measurement first if you want to edit measured gain results.

> Warning:
> Manual gain edits affect the file you save.

## Turn On Manual Editing

For setlists:

1. Open the setlist.
2. Check Edit manually below the preset table.
3. Double-click a preset name, snapshot name, or gain adjustment cell.

For a single `.hlx` preset, the temporary Preset slot can be edited without
turning on Edit manually.

[Screenshot placeholder: Edit manually checkbox]
[Screenshot placeholder: Inline cell editor]

## Editing A Cell

When the inline editor appears:

- press Enter to keep the edit;
- press Escape to cancel;
- click away to keep the edit.

You can edit:

- preset names;
- snapshot names;
- gain adjustment values.

Preset and snapshot names are cleaned to fit Helix rules. Long names may be
shortened.

## Manual Gain Example

If one solo still feels too loud, you might lower it by 1 dB:

```text
Before: +3.0
After:  +2.0
```

Use small changes first.

## Save The Edited File

After editing, click Save or Save As.

If you try to open another file or start normalization with unsaved edits,
MatchPatch asks whether you want to save, discard, or cancel.

## Preset Table CSV

The CSV buttons below the table let you save and load the preset table.

Use this when you want to review or edit table results outside MatchPatch.

The table CSV uses `|` as a separator because Helix names can contain commas.

[Screenshot placeholder: CSV open/save buttons]

## Loading A Table CSV

When loading a table CSV:

- MatchPatch matches rows by preset slot, such as `01A`;
- only presets already visible in the current table are changed;
- invalid names or gain values are reported as errors.

[Screenshot placeholder: CSV error popup]

## What Success Looks Like

- Manual edits are visible in the table.
- No unexpected error popup appears.
- Save writes the edited Helix file.
- The edited file sounds correct after import.

## If Something Goes Wrong

- If a name changes unexpectedly, it may have been cleaned for Helix-safe
  characters or length.
- If a gain value is rejected, enter a normal number such as `-1`, `0`, or
  `1.5`.
- If CSV import fails, check that the current table and CSV use the same preset
  IDs and snapshot count.
- If you do not trust the edit, discard changes and reload the original file.

> Warning:
> CSV import applies only to presets currently loaded in the table.

See also: [Reading Results](../concepts/reading-results.md).
