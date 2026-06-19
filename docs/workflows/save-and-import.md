(help-save-import)=
# Save And Import Files

Use this workflow after measurement to write the adjusted Helix or Pod Go file
and import it back into the matching processor.

## Before You Save

Check the result table:

- no important rows are red;
- ignored snapshots are intentional;
- solo snapshots are marked correctly;
- manual edits look right;
- gain changes look reasonable.

See also: [Reading Results](../concepts/reading-results.md).

## Save

Save writes changes to the active processor file.

Use Save when you are comfortable replacing the active file and you already have
a backup.

If you opened several single-preset files at once, Save writes each edited
preset back to its original file. The first overwrite prompt includes a checkbox
for approving the rest of the batch without being asked for every file.

(help-save-as)=
## Save As

Save As writes a new processor file.

This is the safer choice for most users because it keeps the original file
untouched.

If you opened several single-preset files at once, Save As writes one matching
setlist that contains all of those open presets. It does not write several
separate preset files.

Example:

```text
Original: My Setlist.hls
Adjusted: My Setlist Adjusted.hls
```


## Save Measurement File

Save Measurement File creates a temporary file used for measurement routing.

Use it when the workflow asks you to import a measurement file, or when a
parameter study requires a prepared measurement file on the processor.

> Warning:
> Never use the measurement file as your final live file.


## File Extensions

Keep the same file type:

- `.hls` setlist saves as `.hls`;
- `.hlx` preset saves as `.hlx`;
- `.pgs` setlist saves as `.pgs`;
- `.pgp` preset saves as `.pgp`;
- several open single-preset files save individually with Save, but Save As
  writes a matching setlist.

MatchPatch warns you if the saved file extension does not match.

(help-unsaved-changes)=
## Overwrite Prompts

If the file already exists, MatchPatch asks before overwriting it.

Read the path carefully before confirming.

## Import The Adjusted File

After saving:

1. Open the matching processor editor or import method.
2. Import the adjusted `.hls`, `.hlx`, `.pgs`, or `.pgp` file.
3. Confirm the presets and snapshots are in the expected slots.
4. Play through the setlist.
5. Listen for level balance in context.

## What Success Looks Like

- The adjusted file saves successfully.
- The file imports into the matching processor.
- Presets and snapshots are in the expected places.
- The setlist sounds more even.
- You still have the original backup.

## If Something Looks Wrong

- Reimport the original backup if needed.
- Reopen MatchPatch and check the result table.
- Rerun measurement for affected presets.
- Use manual editing for small musical exceptions.

> Warning:
> Do not overwrite a live file unless you are certain the adjusted file is ready.

See also: [Measurement And Adjusted Files](../concepts/measurement-and-adjusted-files.md).
