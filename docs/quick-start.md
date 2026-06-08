(help-quick-start)=
# Quick Start

Use this guide for a first MatchPatch run in about 10 minutes.

If you only want to learn the app, use loopback mode first. If you want real
Helix results, use hardware mode.

## Before You Start

- Back up your original Helix `.hls` or `.hlx` file.
- Have a reference DI WAV ready, or use the default one.
- Decide which file you are working on:
  - `.hls` for a setlist;
  - `.hlx` for one preset.
- Decide which backend to use:
  - loopback for a safe no-hardware test;
  - hardware for real Helix measurement.

> Warning:
> Keep a backup of your original Helix file before saving changes.

## Fast First Run: Loopback

Loopback is the easiest way to learn MatchPatch. It does not measure your Helix,
but it lets you practice the full GUI flow.

1. Open MatchPatch.
2. Open a Helix `.hls` setlist or `.hlx` preset.
3. Open Advanced.
4. Go to the Device tab.
5. Set Backend to `loopback`.
6. If you opened a setlist, choose the presets you want to test.
7. If you opened a single `.hlx` preset, enter a temporary slot such as `12A` in
   the Preset column.
8. Check the Reference DI field in Advanced > Files.
9. Click Start normalization.
10. Watch the progress area and result table.
11. Try Save As only if you intentionally want to test saving.


> Warning:
> Loopback mode does not measure your real Helix preset levels.

For more detail, see [Test Without Hardware](workflows/test-without-hardware.md).

## Real Run: Hardware

Use hardware mode when you are ready to measure the Helix.

1. Connect and power on the Helix.
2. Open MatchPatch.
3. Open your `.hls` setlist or `.hlx` preset.
4. Open Advanced > Device.
5. Set Backend to `hardware`.
6. Check audio routing and MIDI steering.
7. Check the Reference DI in Advanced > Files.
8. Select the presets you want to measure.
9. Click Start normalization.
10. Follow any import prompts.
11. Review the result table.
12. Click Save As and save an adjusted file.
13. Import the adjusted file into the Helix.
14. Listen through the presets and snapshots.


For more detail, see [Hardware Measurement](workflows/hardware-measurement.md)
and [Normalize A Setlist](workflows/normalize-setlist.md).

## Success Checklist

Before you trust the adjusted file, check:

- Measurement finished.
- No important rows are red.
- Solo snapshots have stars when expected.
- Ignored snapshots are grey only when you meant to skip them.
- Save or Save As completed.
- The adjusted file imports into Helix.
- The presets sound balanced when you play.

## If You Get A Warning

Do not panic. Most warnings are fixable.

Common causes are:

- the wrong backend;
- missing Helix connection;
- wrong audio routing;
- missing reference DI;
- a snapshot recording silence;
- timing that is too fast for long delay or reverb trails.

See [Troubleshooting](troubleshooting.md).

## Where To Go Next

- Full manual: [Musician Guide](musician-guide.md)
- Setlist workflow: [Normalize A Setlist](workflows/normalize-setlist.md)
- Single preset workflow: [Normalize A Single Preset](workflows/normalize-single-preset.md)
- Terms: [Glossary](glossary.md)
