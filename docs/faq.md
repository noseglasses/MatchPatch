# FAQ

Quick answers to common MatchPatch questions.

## What Does MatchPatch Actually Change In My Helix File?

MatchPatch mainly changes output block levels so presets and snapshots land
closer to the target loudness.

If you manually edit names or gain values in the table, those edits can also be
saved.

See [Reading Results](concepts/reading-results.md).

## Will MatchPatch Change My Tone?

MatchPatch is meant to balance level, not redesign your tone.

It changes output level rather than amp, cab, drive, or effect settings. Still,
always listen after importing the adjusted file, because level changes can affect
how a sound feels in the mix.

## Can I Undo Changes?

The safest undo is your backup.

Keep the original `.hls` or `.hlx` file, and use Save As when possible. If you
do not like the adjusted file, import the original backup again.

## Can I Use MatchPatch Without A Helix Connected?

Yes. Use loopback or simulated mode to learn the app without hardware.

Those modes are useful for practice, but they do not measure your real Helix
tones.

See [Test Without Hardware](workflows/test-without-hardware.md).

## What Is Loopback Mode For?

Loopback mode measures the reference DI directly. It is a safe way to test the
MatchPatch workflow without connecting a Helix.

Do not use loopback results as final live preset levels.

See [Backends](concepts/backends.md).

## What Is Simulated Mode For?

Simulated mode pretends to be a processor. It is useful for testing the workflow
without hardware while seeing more varied fake results than loopback.

It is not a real Helix measurement.

## When Should I Use Hardware Mode?

Use hardware mode when you want real results for rehearsal or stage use.

Hardware mode measures the actual Helix sound.

See [Hardware Measurement](workflows/hardware-measurement.md).

## Why Do I Need A Reference DI?

MatchPatch needs the same performance through every preset so the comparison is
fair.

The DI should match your playing style. A metal rhythm DI and a clean ambient DI
can lead to different balancing decisions.

See [Reference DI](concepts/reference-di.md).

## Which Reference DI Should I Use?

Use a clean DI that represents the music you are balancing.

For rock, include palm mutes, chords, and lead notes. For clean or ambient
music, include ringing chords and softer playing.

## What Target LUFS Should I Choose?

Use the default first.

Change target LUFS only when you have a musical reason or a repeatable band
setup that needs a different level.

See [LUFS And Loudness](concepts/lufs-and-loudness.md).

## Why Are Solo Snapshots Treated Differently?

Solos often need to sit above rhythm parts. MatchPatch can add a solo boost to
snapshots it recognizes as solos.

See [Snapshots, Solos, And Ignored Snapshots](concepts/snapshots-solos-and-ignored.md).

## How Does MatchPatch Know A Snapshot Is A Solo?

It looks at the snapshot name. By default, names containing `solo` are treated as
solo snapshots and marked with a star.

Clear snapshot names help.

## Why Are Some Snapshots Grey?

Grey snapshots are ignored. MatchPatch skips them and does not adjust them.

This is useful for unused snapshots or placeholders.

## Why Did I Get A Red Warning Cell?

A red cell means MatchPatch could not safely calculate a normal adjustment.

Common causes are silence, wrong routing, missing loudness data, or an output
level that would go outside the Helix range.

See [Troubleshooting](troubleshooting.md).

## What Is A Measurement File?

A measurement file is a temporary Helix file made so MatchPatch can measure the
processor correctly.

It is not the final file for playing.

See [Measurement And Adjusted Files](concepts/measurement-and-adjusted-files.md).

## Can I Use The Measurement File Live?

No.

> Warning:
> Measurement files are for measurement only. Use the adjusted file for playing.

## Why Does A Single `.hlx` Preset Need A Temporary Slot?

A single `.hlx` preset does not know where it lives on the Helix. MatchPatch
needs a temporary slot, such as `12A`, so it can switch to the right location
during measurement.

See [Normalize A Single Preset](workflows/normalize-single-preset.md).

## Should I Normalize Before Or After Rehearsal?

Both can help.

Normalize before rehearsal to start from balanced levels. After rehearsal, rerun
or manually adjust any presets that still feel wrong in the band mix.

## Can I Normalize Only Changed Presets?

Yes, for setlists.

Use Select changed and choose a previous version of the same `.hls` setlist.

See [Select Changed Presets](workflows/select-changed-presets.md).

## Can I Edit The Results Manually?

Yes. Enable Edit manually, then double-click editable cells.

Use small gain changes and save a backup.

See [Manual Editing And CSV](workflows/manual-editing-and-csv.md).

## Can I Save Table Changes As CSV?

Yes. The table has CSV open and save buttons.

This is useful if you want to review or edit preset names, snapshot names, and
gain adjustments outside MatchPatch.

## What Should I Do If Measurements Vary Between Runs?

Use Default timing first. If results still vary, run Determine optimal
parameters.

Long delay or reverb trails often need slower timing.

See [Optimize Timing](workflows/optimize-timing.md).

## What Should I Send If I Need Help?

Send:

- what you were trying to do;
- whether you used hardware, loopback, or simulated mode;
- the warning text;
- a screenshot of the result table;
- a screenshot of the Log tab;
- whether recorded-output playback sounded correct.

Do not send private files unless you are comfortable sharing them.
