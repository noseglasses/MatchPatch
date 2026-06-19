(help-quick-start)=
# Quick Start

Use this guide for a first MatchPatch run in about 10 minutes.

If you only want to learn the app, use loopback mode first. If you want real
processor results, use hardware mode.

## Before You Start

- Back up your original Helix `.hls`/`.hlx` or Pod Go `.pgs`/`.pgp` file.
- Have a reference DI WAV ready, or use the default one.
- Decide which file you are working on:
  - `.hls` or `.pgs` for a setlist;
  - one `.hlx` or `.pgp` for one preset;
  - several `.hlx` or `.pgp` files from the same device family when you want
    MatchPatch to show them together as a temporary setlist.
- Decide which backend to use:
  - loopback for a safe no-hardware test;
  - hardware for real processor measurement.
- If this is your first hardware run, use Run preflight check in Advanced >
  Diagnostics before starting normalization.
- Optional: save a config file if you want the same defaults every time. On
  installed Windows builds, the automatic config path is
  `%APPDATA%\MatchPatch\config.toml`.

> Warning:
> Keep a backup of your original processor file before saving changes.

## Fast First Run: Loopback

Loopback is the easiest way to learn MatchPatch. It does not measure your real
processor, but it lets you practice the full GUI flow.

1. Open MatchPatch.
2. Open a supported setlist or preset file.
3. Open Advanced.
4. Go to the Device tab.
5. Set Backend to `loopback`.
6. If you opened a setlist, choose the presets you want to test.
7. If you opened a single preset file, enter a temporary slot such as `12A` in
   the Preset column.
8. Check the Reference DI field in Advanced > Files.
9. Click Start normalization.
10. Watch the progress area and result table.
11. Try Save As only if you intentionally want to test saving.


> Warning:
> Loopback mode does not measure your real processor preset levels.

For more detail, see [Test Without Hardware](workflows/test-without-hardware.md).

## Real Run: Hardware

Use hardware mode when you are ready to measure the processor.

1. Connect and power on the processor.
2. Open MatchPatch.
3. Open your supported setlist or preset file.
4. Open Advanced > Device.
5. Set Backend to `hardware`.
6. Check audio routing and MIDI steering.
7. Check the Reference DI in Advanced > Files.
8. Open Advanced > Diagnostics and click Run preflight check.
9. Select the presets you want to measure.
10. Click Start normalization.
11. Follow any import prompts.
12. Review the result table.
13. Click Save As and save an adjusted file, or click Save when you opened
    several single-preset files and want to overwrite those original files.
14. Import the adjusted file into the processor.
15. Listen through the presets and snapshots.


For more detail, see [Hardware Measurement](workflows/hardware-measurement.md)
and [Normalize A Setlist](workflows/normalize-setlist.md).

## Success Checklist

Before you trust the adjusted file, check:

- Measurement finished.
- No important rows are red.
- Solo snapshots have stars when expected.
- Ignored snapshots are grey only when you meant to skip them.
- Save or Save As completed.
- The adjusted file imports into the matching processor editor or device.
- The presets sound balanced when you play.

## If You Get A Warning

Do not panic. Most warnings are fixable.

Common causes are:

- the wrong backend;
- missing processor connection;
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
