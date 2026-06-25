(help-routing-levels)=
# Routing And Levels

Routing is the path the sound takes while MatchPatch measures your presets.

In hardware mode, the signal path is:

1. The computer plays the clean reference DI.
2. The DI enters the processor.
3. The selected preset and snapshot shape the DI.
4. The processed sound returns to the computer.
5. MatchPatch measures the recorded sound.

(help-audio-routing)=
## Playback And Recording Channels

Playback channels send the reference DI from the computer to the processor.

Recording channels bring the processed sound back to the computer.

For typical Helix and Pod Go setups, MatchPatch expects:

- processed recording on USB `1/2`;
- reference DI playback on USB `3/4`.

Your setup may differ. If the channels are wrong, MatchPatch may record silence
or the wrong signal.

## Output Level

The output block level is the final output gain inside a supported processor
preset.
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


## Next Step

- Set up real measurement: [Hardware Measurement](../workflows/hardware-measurement.md)
- Fix routing problems: [Troubleshooting](../troubleshooting.md)
