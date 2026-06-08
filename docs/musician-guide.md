# Musician Guide

This is the main non-technical MatchPatch manual.

MatchPatch helps balance Helix presets and snapshots by measuring loudness and
writing output-level adjustments.

If this is your first time, start with [Quick Start](quick-start.md), then come
back here when you want the full picture.

## When To Use MatchPatch

Use MatchPatch:

- after building or editing presets;
- before rehearsal;
- before a gig;
- after changing amp, cab, drive, EQ, delay, or reverb settings;
- when solo snapshots are not lifting enough;
- when your sound engineer keeps asking for more consistent levels.

MatchPatch is especially useful for cover-band setlists where each song has its
own preset.

## What MatchPatch Changes

MatchPatch mainly adjusts Helix output block levels so snapshots land closer to
the target loudness.

It can also save manual edits you make in the table, such as preset names,
snapshot names, or manual gain values.

## What MatchPatch Does Not Replace

MatchPatch does not replace listening.

It cannot know:

- how loud the rest of your band is;
- whether a part should sit forward or back;
- whether a bright lead cuts more than a dark rhythm tone;
- whether a venue or sound engineer needs a different balance.

Use MatchPatch to get close. Then play through the adjusted file.

## Before You Start

Do this before any real run:

1. Back up your original `.hls` or `.hlx`.
2. Choose a reference DI.
3. Decide whether this is a no-hardware test or a real hardware measurement.
4. Confirm which presets or snapshots should be measured.
5. Decide whether solos need a boost.
6. Decide whether any snapshots should be ignored.

> Warning:
> Keep the original Helix file until you have listened to the adjusted file on
> the Helix.

## Choosing A Reference DI

The reference DI is the clean guitar performance MatchPatch plays through every
preset.

Choose a DI that sounds like the way you actually play. If your setlist is rock,
include rhythm attacks and lead notes. If your setlist is clean and ambient,
include ringing chords and softer picking.

Changing the reference DI can change the results.

See [Reference DI](concepts/reference-di.md).


## Choosing A Backend

The backend decides how MatchPatch gets sound to measure.

- Hardware measures the real Helix.
- Loopback lets you learn the app without hardware.
- Simulated gives a fake processor-style test without hardware.

Use hardware for final rehearsal or gig-ready results.

See [Backends](concepts/backends.md).

(help-opening-files)=
## Opening Files

MatchPatch works with:

- `.hls` Helix setlists;
- `.hlx` single Helix presets.

A setlist shows multiple preset rows. A single preset shows one row and needs a
temporary Helix slot, such as `12A`, so MatchPatch knows where to steer the
Helix during measurement.

Workflows:

- [Normalize A Setlist](workflows/normalize-setlist.md)
- [Normalize A Single Preset](workflows/normalize-single-preset.md)

## Selecting Presets

In a setlist, every non-empty preset appears in the table.

Use:

- the checkbox beside a preset to include or exclude it;
- Select all for a full setlist pass;
- Unselect all when you want to choose a few manually;
- Select changed when you only want presets changed since an older setlist.

See [Select Changed Presets](workflows/select-changed-presets.md).

(help-advanced-settings)=
## Snapshots, Solos, And Ignored Snapshots

MatchPatch measures snapshots inside each preset.

Solo snapshots can receive a boost. By default, MatchPatch looks for snapshot
names containing `solo` and marks them with a star.

Ignored snapshots are skipped and shown in grey.

Use clear snapshot names. Names like `Clean`, `Crunch`, `Lead`, and `Solo` make
the table easier to understand.

See [Snapshots, Solos, And Ignored Snapshots](concepts/snapshots-solos-and-ignored.md).


## Target LUFS And Loudness

Target LUFS is the loudness MatchPatch tries to match.

The default is a good starting point. Change it only when you have a musical
reason.

If a snapshot measures below the target, MatchPatch raises it. If it measures
above the target, MatchPatch lowers it.

See [LUFS And Loudness](concepts/lufs-and-loudness.md).

## Hardware Measurement

For real results, hardware mode must send audio to the Helix and record the
processed audio back.

Check:

- Helix USB connection;
- audio device;
- playback channels;
- recording channels;
- MIDI output;
- MIDI channel.

Use recorded-output playback if you want to confirm MatchPatch recorded the real
Helix sound.

See [Hardware Measurement](workflows/hardware-measurement.md) and
[Routing And Levels](concepts/routing-and-levels.md).

## Measurement Timing

Timing controls how long MatchPatch waits while switching presets and snapshots.

Use Default timing first. Fast timing can save time, but it can be unstable with
delay, reverb, or other trails.

If measurements vary between runs, use Determine optimal parameters.

See [Measurement Timing](concepts/timing.md) and
[Optimize Timing](workflows/optimize-timing.md).

## Reading The Result Table

After measurement, the table shows each preset and snapshot.

Important table signs:

- Delta dB is the level change MatchPatch wants to apply.
- Out dB is the current output level.
- A star means solo snapshot.
- Grey cells mean ignored snapshot.
- Red cells mean a failed or unsafe measurement.
- A playback button lets you hear recorded output when capture is enabled.

Do not ignore red cells. They often mean silence, wrong routing, or an unsafe
gain change.

See [Reading Results](concepts/reading-results.md).


## Manual Edits And CSV

You can edit some table values manually.

Use manual editing when:

- you want to rename a preset or snapshot;
- you need a small musical gain exception;
- you need to fix a result after reviewing it.

The table can also be saved and loaded as CSV.

See [Manual Editing And CSV](workflows/manual-editing-and-csv.md).

## Custom Adjustments

Custom adjustments are planned musical exceptions. They tell MatchPatch that a
specific preset snapshot should be louder or quieter than the normal target.

Use small values first.

See [Custom Adjustments](workflows/custom-adjustments.md).

## Saving And Importing

After reviewing results, save the adjusted file.

For most users, Save As is the safest choice because it keeps the original file
unchanged.

Then import the adjusted file into the Helix and listen through the setlist.

> Warning:
> A measurement file is not the final live file. Import the adjusted file for
> playing.

See [Save And Import Files](workflows/save-and-import.md) and
[Measurement And Adjusted Files](concepts/measurement-and-adjusted-files.md).


## After Importing

Play through the adjusted presets in a real musical context.

Listen for:

- rhythm sounds that jump out too much;
- leads that still disappear;
- clean parts that feel too quiet;
- special effects that should not have been normalized;
- snapshot changes that feel unnatural.

If one part still needs an exception, use manual editing or custom adjustments.

## If Something Goes Wrong

Start with [Troubleshooting](troubleshooting.md).

Common fixes include:

- choose the correct backend;
- check Helix USB and MIDI;
- check audio routing;
- choose the correct reference DI;
- slow down timing;
- rerun only affected presets;
- manually edit a small gain exception.

(help-metadata)=
## Next Steps

- First run: [Quick Start](quick-start.md)
- Main setlist workflow: [Normalize A Setlist](workflows/normalize-setlist.md)
- Single preset workflow: [Normalize A Single Preset](workflows/normalize-single-preset.md)
- Problems: [Troubleshooting](troubleshooting.md)
- Terms: [Glossary](glossary.md)
