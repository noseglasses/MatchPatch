# Glossary

Short explanations of MatchPatch terms. These are written for musicians, not
software developers.

## Adjusted File

The Helix file MatchPatch saves after calculating level changes. This is the
file you import back into the Helix after checking the results.

See also: [Measurement And Adjusted Files](concepts/measurement-and-adjusted-files.md).

## Analysis Interval

How often MatchPatch checks loudness while listening through the recorded audio.
A shorter interval checks more often.

## Analysis Window

The length of audio MatchPatch listens to for each loudness measurement. A longer
window can be steadier, but it needs enough recorded audio.

## ASIO

A low-latency Windows audio driver type often used by audio interfaces and
processors. If you use hardware mode, the Helix audio device may appear through
ASIO.

## Backend

The way MatchPatch gets sound to measure:

- hardware measures a real Helix;
- loopback tests the app without a Helix;
- simulated uses a fake processor for testing.

See also: [Backends](concepts/backends.md).

## Block Size

The audio buffer size used while recording and playing audio. Most users can
leave this at `0`, which lets the audio system choose.

## Crest Factor

The gap between the loudest peaks and the average energy of a sound. A sharp,
spiky rhythm part has a higher crest factor than a compressed lead tone.

See also: [Crest Factor](concepts/crest-factor.md).

## Custom Adjustment

A manual loudness exception for one preset snapshot. For example, you can tell
MatchPatch to make snapshot 2 of `01A` 1.5 dB louder than the normal target.

## dB

Decibels. Guitar processors use dB to describe level changes. A `+3 dB` change
is louder; a `-3 dB` change is quieter.

## Deadband

A small level-change range where MatchPatch may leave things alone. This avoids
tiny edits that do not matter musically.

## DI

Direct input. A clean guitar recording before amp, cab, and effects. MatchPatch
plays this clean recording through every preset so each preset is measured from
the same performance.

See also: [Reference DI](concepts/reference-di.md).

## Gain Delta

The level change MatchPatch calculated for a snapshot. In the table, this is the
Delta dB value.

## Hardware Mode

The backend that measures a real Helix. Use this for real results.

See also: [Hardware Measurement](workflows/hardware-measurement.md).

## Helix

The Line 6 Helix guitar processor family. MatchPatch currently focuses on Helix
`.hls` setlists and `.hlx` presets.

## LUFS

A loudness measurement that is closer to perceived loudness than a simple peak
meter. MatchPatch uses LUFS to decide how much each snapshot should move up or
down.

See also: [LUFS And Loudness](concepts/lufs-and-loudness.md).

## Loopback Mode

A no-hardware mode where MatchPatch measures the reference DI directly. It is
good for learning the app, but it does not measure your Helix tone.

See also: [Test Without Hardware](workflows/test-without-hardware.md).

## Measurement CSV

A file containing measured loudness and crest-factor results for each preset and
snapshot. Most musicians do not need to open it.

## Measurement File

A temporary Helix file created for measuring. It changes routing so MatchPatch
can send the DI into the Helix and record the result.

> Warning:
> A measurement file is not meant for live playing.

See also: [Measurement And Adjusted Files](concepts/measurement-and-adjusted-files.md).

## MIDI

The control connection MatchPatch uses to switch Helix presets and snapshots
during hardware measurement.

## Output Block Level

The final output level inside a Helix preset. MatchPatch adjusts this level per
snapshot to balance loudness.

See also: [Routing And Levels](concepts/routing-and-levels.md).

## Patch

Another word for a preset. On Helix, a patch or preset lives in a slot such as
`01A` or `12D`.

## Pre-Roll

Silence recorded before the reference DI starts. It gives the audio recording a
little room before the performance.

## Post-Roll

Silence recorded after the reference DI ends. It gives the audio recording room
for latency and short tails.

## Preset

A stored Helix sound, usually one song, tone, or rig.

## Reference DI

The clean guitar WAV MatchPatch plays through every selected preset. A good
reference DI should match your real playing style.

See also: [Reference DI](concepts/reference-di.md).

## Round-Trip Latency

The small time delay caused by sending audio out to the Helix and recording it
back into the computer.

## Routing

The path audio takes. In hardware mode, the reference DI leaves the computer,
goes into the Helix, and the processed sound comes back to the computer.

See also: [Routing And Levels](concepts/routing-and-levels.md).

## Simulated Mode

A no-hardware mode that pretends to be a processor. It is useful for testing the
workflow, but it is not a real Helix measurement.

## Snapshot

A variation inside one Helix preset. For example, one preset might have Clean,
Crunch, Lead, and Solo snapshots.

## Solo Boost

Extra level added to snapshots that MatchPatch recognizes as solos. The default
solo boost is 3 dB.

See also: [Snapshots, Solos, And Ignored Snapshots](concepts/snapshots-solos-and-ignored.md).

## Steering

The automatic preset and snapshot switching MatchPatch performs during hardware
measurement.

## Target LUFS

The loudness MatchPatch tries to match. If a snapshot is below the target,
MatchPatch raises it; if it is above the target, MatchPatch lowers it.

## USB Channels

The audio paths between the computer and Helix over USB. MatchPatch needs the
playback and recording channels to match the Helix routing.

## WSL And WSLg

Windows Subsystem for Linux and its graphical app support. Some users run the
MatchPatch GUI from WSL while hardware measurement uses a Windows audio setup.
