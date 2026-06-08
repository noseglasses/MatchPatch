# Routing And Levels

Routing is the path the sound takes while MatchPatch measures your presets.

In hardware mode, the signal path is:

1. The computer plays the clean reference DI.
2. The DI enters the Helix.
3. The Helix processes the DI through the selected preset and snapshot.
4. The processed sound returns to the computer.
5. MatchPatch measures the recorded sound.

## Playback And Recording Channels

Playback channels send the reference DI from the computer to the Helix.

Recording channels bring the processed Helix sound back to the computer.

For a typical Helix setup, MatchPatch expects:

- processed recording on USB `1/2`;
- reference DI playback on USB `3/4`.

Your setup may differ. If the channels are wrong, MatchPatch may record silence
or the wrong signal.

## Output Level

The output block level is the final output gain inside a Helix preset.
MatchPatch adjusts this level per snapshot to balance loudness.

## Out dB And Delta dB

In the preset table:

- Out dB shows the current output level MatchPatch read from the preset.
- Delta dB shows the change MatchPatch wants to apply.

Example:

```text
Out dB: -4.0
Delta dB: +2.5
```

That means the current output level is `-4.0 dB`, and MatchPatch wants to raise
that snapshot by `2.5 dB`.

> Warning:
> Wrong routing is one of the most common causes of failed measurements and bad
> LUFS warnings.

[Screenshot placeholder: Audio routing settings]
[Screenshot placeholder: Out dB and Delta dB cells]

## Next Step

- Set up real measurement: [Hardware Measurement](../workflows/hardware-measurement.md)
- Fix routing problems: [Troubleshooting](../troubleshooting.md)
