# Crest Factor

Crest factor describes the difference between a sound's loudest peaks and its
average energy.

A spiky palm-muted rhythm part usually has a higher crest factor. A compressed
lead tone usually has a lower crest factor.

## Why MatchPatch Cares

Two snapshots can measure similarly in LUFS but still feel different. One may
have sharp peaks and lots of space between notes. Another may be compressed and
steady.

MatchPatch uses crest factor as part of the level decision so a very peaky or
very compressed sound does not lead to a misleading adjustment.

## Practical Example

Imagine two snapshots:

- Rhythm: hard palm-muted hits with big peaks.
- Lead: sustained notes with compression.

The rhythm snapshot may peak high but feel less loud. The lead snapshot may have
lower peaks but feel more present. Crest factor helps explain that difference.

> Warning:
> Do not over-focus on crest-factor numbers. Use them to understand why sounds
> behave differently, then listen in context.

[Screenshot or diagram placeholder: spiky signal versus compressed signal]

## Next Step

- Learn the main loudness target: [LUFS And Loudness](lufs-and-loudness.md)
- Learn how table results are shown: [Reading Results](reading-results.md)
