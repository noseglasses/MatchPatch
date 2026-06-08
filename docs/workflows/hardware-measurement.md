# Hardware Measurement

Use hardware mode when you want MatchPatch to measure your real Helix.

Hardware mode gives the results you should use for rehearsal, stage preparation,
and final setlist balancing.

## Before You Start

- Connect the Helix by USB.
- Make sure the Helix is powered on.
- Make sure your computer can see the Helix audio device.
- Make sure your computer can see the Helix MIDI output.
- Have a reference DI WAV ready.
- Back up your original `.hls` or `.hlx` file.

See also:

- [Backends](../concepts/backends.md)
- [Reference DI](../concepts/reference-di.md)
- [Routing And Levels](../concepts/routing-and-levels.md)

## What Hardware Mode Does

MatchPatch sends the reference DI to the Helix, switches presets and snapshots,
records the processed sound, and measures the loudness.

The Helix is doing the real tone work. MatchPatch is listening and calculating
the output-level changes.

## Check The Backend

1. Open Advanced.
2. Go to the Device tab.
3. Set Backend to `hardware`.

[Screenshot placeholder: Backend set to hardware]

## Check Audio Routing

In the Helix device settings, check:

- Audio device.
- Recording channels.
- Playback channels.
- Sample rate.
- Block size.

For many Helix setups:

- processed Helix audio returns on USB `1/2`;
- the reference DI is sent to Helix USB `3/4`.

Your own system may differ.

[Screenshot placeholder: Helix audio routing settings]

## Check MIDI Steering

In the Helix device settings, check:

- MIDI output.
- MIDI channel.
- Preset wait.
- Snapshot wait.
- Measurement wait.

MIDI steering is how MatchPatch changes presets and snapshots during the run.

[Screenshot placeholder: Helix MIDI steering settings]

## Run The Hardware Check

When you start a hardware run, MatchPatch checks whether the backend is
available.

If the check succeeds, measurement continues.

If the check fails, MatchPatch shows an error. Check USB connection, audio
device name, MIDI output name, and whether the Helix is powered on.

[Screenshot placeholder: Hardware check overlay]

## Use Recorded-Output Playback

The toolbar can record measured output and play it back.

Use this to confirm MatchPatch actually recorded the processed Helix signal. If
you hear silence or the wrong sound, check routing before trusting the results.

## What Success Looks Like

- Hardware check passes.
- Presets switch on the Helix during measurement.
- Snapshot changes happen during measurement.
- The loudness bar updates.
- Recorded-output playback sounds like the processed Helix tone.
- The result table does not show unexpected red warnings.

## If Something Goes Wrong

- If hardware is not found, check USB, audio device, and MIDI output.
- If recorded-output playback is silent, check routing.
- If rows are red, use Default timing and check [Troubleshooting](../troubleshooting.md).
- If measurements vary, read [Measurement Timing](../concepts/timing.md).

> Warning:
> Wrong USB channels can record silence. Silence often causes bad LUFS or
> implausible output-gain warnings.

> Warning:
> Use slower timing for presets with long delay or reverb trails. Fast timing can
> make one snapshot bleed into the next measurement.
