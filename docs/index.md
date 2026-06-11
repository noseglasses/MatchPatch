# MatchPatch Docs

```{image} assets/matchmatch-logo.png
:alt: MatchPatch logo
:class: matchpatch-index-logo
:width: 220px
```

Start here if you want to balance Helix preset and snapshot loudness with
MatchPatch.

MatchPatch measures your presets, calculates output-level changes, and helps you
save an adjusted Helix file.

> Warning:
> Keep a backup of your original `.hls` or `.hlx` before saving or importing
> adjusted files.

## Where Should I Go?

| I want to... | Read this |
|---|---|
| Try MatchPatch quickly | [Quick Start](quick-start.md) |
| Read the main user manual | [Musician Guide](musician-guide.md) |
| Balance a full setlist | [Normalize A Setlist](workflows/normalize-setlist.md) |
| Balance one preset | [Normalize A Single Preset](workflows/normalize-single-preset.md) |
| Test without connecting a Helix | [Test Without Hardware](workflows/test-without-hardware.md) |
| Fix a problem | [Troubleshooting](troubleshooting.md) |
| Plan or record the teaser video | [Video](video.md) |
| Look up a short answer | [FAQ](faq.md) |
| Look up a term | [Glossary](glossary.md) |

## Main Workflows

- [Test Without Hardware](workflows/test-without-hardware.md)
- [Hardware Measurement](workflows/hardware-measurement.md)
- [Normalize A Setlist](workflows/normalize-setlist.md)
- [Normalize A Single Preset](workflows/normalize-single-preset.md)
- [Select Changed Presets](workflows/select-changed-presets.md)
- [Manual Editing And CSV](workflows/manual-editing-and-csv.md)
- [Custom Adjustments](workflows/custom-adjustments.md)
- [Optimize Timing](workflows/optimize-timing.md)
- [Save And Import Files](workflows/save-and-import.md)
- [Video](video.md)

## Learn The Ideas

- [Backends](concepts/backends.md)
- [Reference DI](concepts/reference-di.md)
- [LUFS And Loudness](concepts/lufs-and-loudness.md)
- [Crest Factor](concepts/crest-factor.md)
- [Measurement And Adjusted Files](concepts/measurement-and-adjusted-files.md)
- [Routing And Levels](concepts/routing-and-levels.md)
- [Snapshots, Solos, And Ignored Snapshots](concepts/snapshots-solos-and-ignored.md)
- [Measurement Timing](concepts/timing.md)
- [Reading Results](concepts/reading-results.md)

## Supported Files

MatchPatch currently focuses on Line 6 Helix files:

- `.hls` setlists;
- `.hlx` single presets.

## For Maintainers

Normal users should not need this section.

- [Developer Notes](developer-notes.md)
- [Existing technical docs](dev/architecture.md)

```{toctree}
:hidden:
:caption: User Docs
:maxdepth: 2

quick-start
musician-guide
workflows/test-without-hardware
workflows/hardware-measurement
workflows/normalize-setlist
workflows/normalize-single-preset
workflows/select-changed-presets
workflows/manual-editing-and-csv
workflows/custom-adjustments
workflows/optimize-timing
workflows/save-and-import
video
concepts/backends
concepts/reference-di
concepts/lufs-and-loudness
concepts/crest-factor
concepts/measurement-and-adjusted-files
concepts/routing-and-levels
concepts/snapshots-solos-and-ignored
concepts/timing
concepts/reading-results
troubleshooting
faq
glossary
```

```{toctree}
:hidden:
:caption: Maintainer Docs
:maxdepth: 2

developer-notes
dev/architecture
dev/commands
dev/file-formats
```
