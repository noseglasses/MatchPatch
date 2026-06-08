# Backends

A backend is how MatchPatch gets sound to measure.

For real results, use hardware mode. For learning the app without a Helix, use
loopback. For testing a more complete fake workflow without hardware, use
simulated mode.

## Which Backend Should I Choose?

| If you want to... | Choose |
|---|---|
| Balance real Helix presets | Hardware |
| Learn the GUI without connecting anything | Loopback |
| Test the workflow with fake preset and snapshot changes | Simulated |
| Make final gig-ready level decisions | Hardware |

## Hardware Mode

Hardware mode measures your real Helix.

MatchPatch plays the reference DI from the computer into the Helix, switches
presets and snapshots, records the processed sound, and calculates the gain
changes.

Use hardware mode when you want results you can trust for rehearsal or stage
use.

You need:

- Helix connected by USB.
- Correct audio input and output channels.
- A visible MIDI output for the Helix.
- A reference DI WAV.

See also: [Hardware Measurement](../workflows/hardware-measurement.md).

## Loopback Mode

Loopback mode does not use the Helix.

MatchPatch measures the reference DI directly, as if the processor were doing
nothing. This is helpful when you want to learn the buttons, test file opening,
or practice the save workflow.

> Warning:
> Loopback mode does not measure your Helix tone. Do not use loopback results as
> final preset levels.

See also: [Test Without Hardware](../workflows/test-without-hardware.md).

## Simulated Mode

Simulated mode uses a fake processor inside MatchPatch. It pretends that presets
and snapshots change level, and it can also create fake failures for testing.

This is mainly useful for trying the workflow without hardware while seeing more
interesting table results than loopback.

> Warning:
> Simulated mode is not a substitute for listening to the real Helix.

## Practical Recommendation

If this is your first time, run loopback once so the app feels familiar. Then
switch to hardware mode for the real setlist.

[Screenshot placeholder: Backend selector]

## Next Step

- Practice first: [Test Without Hardware](../workflows/test-without-hardware.md)
- Measure the real Helix: [Hardware Measurement](../workflows/hardware-measurement.md)
