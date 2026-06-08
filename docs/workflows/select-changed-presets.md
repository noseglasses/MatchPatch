(help-select-changed)=
# Select Changed Presets

Use this workflow when you have edited only part of a setlist and do not want to
remeasure everything.

MatchPatch compares your current setlist to an older version and selects presets
whose sound content changed.

## Before You Start

- Have the current `.hls` setlist.
- Have the previous `.hls` setlist.
- Make sure both files are versions of the same setlist.
- Back up the current file.

> Warning:
> This workflow is for `.hls` setlists. It is not for single `.hlx` presets.

## Steps

1. Open MatchPatch.
2. Open the current `.hls` setlist.
3. Click Select changed.
4. Choose the previous `.hls` setlist.
5. Review which presets are now checked.
6. Manually check or uncheck any presets if needed.
7. Run normalization.


## What Counts As Changed?

The goal is to find presets whose sound changed. A renamed preset may not count
as changed if the tone itself is the same.

This is useful after rehearsal when you changed a few tones but kept most of the
setlist untouched.

## If No Presets Are Selected

If no presets are selected:

- you may have chosen the wrong previous file;
- the setlist may not have changed in a way MatchPatch needs to measure;
- the changes may only be names or other non-sound details.

You can still select presets manually.

## What Success Looks Like

- Only changed presets are checked.
- You agree with the selected presets.
- Normalization runs on the smaller selection.

## If Something Goes Wrong

- If no presets are selected, confirm you chose the correct previous setlist.
- If the file is rejected, confirm both files are `.hls`.
- If the selected presets look wrong, adjust the checkboxes manually.
- If you are unsure, run [Normalize A Setlist](normalize-setlist.md) with a
  manual preset selection.

> Warning:
> Use the previous version of the same setlist, not a different bank of songs.

See also: [Normalize A Setlist](normalize-setlist.md).
