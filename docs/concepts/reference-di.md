# Reference DI

A reference DI is a clean guitar recording before amp, cab, and effects.
MatchPatch plays this same performance through every selected preset.

Using the same DI for every preset makes the measurement fair. The preset is the
only thing changing.

## Why It Matters

Presets react differently to playing style. Palm-muted rhythm, open chords,
single-note leads, and sustained notes can all push amps and effects in different
ways.

If the DI does not sound like the way you actually play, the balanced results may
not feel right in rehearsal.

For example, a tight palm-muted rhythm DI may make MatchPatch balance heavy
rhythm presets very well, but it may not tell the full story for clean ambient
presets with long swells. A soft clean DI has the opposite problem: it can be
great for clean sounds, but less useful for checking how distorted presets react
to strong attacks.

## A Good Reference DI

Use a DI that:

- matches your music style;
- includes the kinds of attacks you care about;
- has both rhythm and lead material if your presets need both;
- is not clipped;
- is long enough for the loudness measurement;
- has the sample rate expected by your audio setup;
- is clean and unprocessed.

## When To Make Your Own

Make your own reference DI when:

- your picking dynamics are very different from the bundled DI;
- you play a different instrument;
- you use very clean, ambient, metal, funk, or acoustic-style presets;
- your band needs a specific part to define the level balance.

## Examples

For a rock cover-band setlist, a good DI might include palm-muted low-string
hits, a couple of power chords, and a short lead phrase.

For ambient or worship-style sounds, a better DI might include clean chord
swells, ringing notes, and softer picking.

For bass, acoustic instruments, or other sources, use a reference track made for
that instrument. The best DI is one that feels like the way the preset will be
used on stage.

## Bundled Reference Tracks

Bundled reference tracks live in `audio/reference-di/`.

The shorter Strandberg track is the current default. It is intended for a
guitarist playing several styles, mainly rock. The guitar is tuned to E-flat.
The notes below are written as played, so they sound one semitone lower.

It includes:

- two palm-muted chugs on the low E string;
- an A5 chord rooted on the low E string;
- a B5 chord rooted on the low E string;
- 12th fret on the G string;
- 12th fret on the B string;
- 15th fret on the B string;
- 15th fret on the high E string, ringing out.

```text
    1      &      2      &      3      &      4      &
e|------------------------------------------------15~~~~|
B|----------------------------12------15----------------|
G|--------------------12--------------------------------|
D|------7------9----------------------------------------|
A|------7------9----------------------------------------|
E|-0.-0-5------7----------------------------------------|
    PM-- PM-
```

## Choosing Your Own DI

Use the bundled DI for a first run. Then decide whether it represents your real
playing.

1. Pick a short part that feels normal for your set.
2. Include the attacks that matter: muted hits, chords, lead notes, swells, or
   whatever drives your presets.
3. Record it clean, before amp, cab, and effects.
4. Avoid clipping.
5. Use the same DI for every preset you want to compare.

Example:

If your set has clean verses and loud lead boosts, record a DI with both a
clean chord phrase and a short lead phrase. Do not use only a gentle clean
arpeggio if the lead snapshot is meant to cut through a band.

> Warning:
> A reference DI that does not match your playing style can balance presets in a
> way that looks correct but feels wrong.

[Screenshot placeholder: Reference DI field]

## Next Step

- First run: [Quick Start](../quick-start.md)
- Real measurement: [Hardware Measurement](../workflows/hardware-measurement.md)
