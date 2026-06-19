(help-measurement-and-adjusted-files)=
# Measurement And Adjusted Files

MatchPatch works with three kinds of processor files during a normal workflow:

- your original file;
- a measurement file;
- an adjusted file.

Knowing the difference helps you avoid importing the wrong file before a gig.

## Original File

This is the setlist or preset file you already have, such as `.hls`, `.hlx`,
`.pgs`, or `.pgp`.

Keep a backup of it before running MatchPatch.

(help-measurement-file)=
## Measurement File

A measurement file is a temporary processor file made for measuring. MatchPatch
changes routing so the computer can send the reference DI into the processor and
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

This is the file you import back into the processor after checking the results.
Adjusted files often use `_adjusted` in the filename.

Example:

```text
Songs.hls
Songs_adjusted.hls
```

## Save, Save As, And Save Measurement File

In the GUI:

- Save writes the current MatchPatch changes to the active processor file.
- Save As writes the changes to a new processor file.
- Save Measurement File creates a measurement file for the workflow.

Use Save As when you want to keep the original file untouched.

When several `.hlx` or `.pgp` presets from the same device family are opened
together, MatchPatch treats them as a temporary setlist while you work. Save
writes the edited presets back to their original files. Save As writes one new
matching setlist containing all open presets.

## File Extensions

The output file should keep the same extension as the input:

- `.hls` setlists save as `.hls`;
- `.hlx` presets save as `.hlx`;
- `.pgs` setlists save as `.pgs`;
- `.pgp` presets save as `.pgp`;
- multiple single-preset files opened together save back to their original files
  with Save, but Save As uses a matching setlist extension.

MatchPatch will warn you if the extension does not match.


## Next Step

- Finish safely: [Save And Import Files](../workflows/save-and-import.md)
- Main setlist workflow: [Normalize A Setlist](../workflows/normalize-setlist.md)
