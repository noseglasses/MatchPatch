# Measurement And Adjusted Files

MatchPatch works with three kinds of Helix files during a normal workflow:

- your original file;
- a measurement file;
- an adjusted file.

Knowing the difference helps you avoid importing the wrong file before a gig.

## Original File

This is the `.hls` setlist or `.hlx` preset you already have.

Keep a backup of it before running MatchPatch.

## Measurement File

A measurement file is a temporary Helix file made for measuring. MatchPatch
changes routing so the computer can send the reference DI into the Helix and
record the processed output.

Measurement files often use `_measurement` in the filename.

Example:

```text
Songs.hls
Songs_measurement.hls
```

> Warning:
> A measurement file is for measurement only. Do not use it as your final live
> setlist or preset.

## Adjusted File

An adjusted file contains the level changes MatchPatch calculated.

This is the file you import back into the Helix after checking the results.
Adjusted files often use `_adjusted` in the filename.

Example:

```text
Songs.hls
Songs_adjusted.hls
```

## Save, Save As, And Save Measurement File

In the GUI:

- Save writes the current MatchPatch changes to the active Helix file.
- Save As writes the changes to a new Helix file.
- Save Measurement File creates a measurement file for the workflow.

Use Save As when you want to keep the original file untouched.

## File Extensions

The output file should keep the same extension as the input:

- `.hls` setlists save as `.hls`;
- `.hlx` presets save as `.hlx`.

MatchPatch will warn you if the extension does not match.

[Screenshot placeholder: Save Measurement File toolbar button]
[Screenshot placeholder: Completion popup telling user to save]

## Next Step

- Finish safely: [Save And Import Files](../workflows/save-and-import.md)
- Main setlist workflow: [Normalize A Setlist](../workflows/normalize-setlist.md)
