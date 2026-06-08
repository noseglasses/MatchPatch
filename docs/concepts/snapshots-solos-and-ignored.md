(help-snapshots-solos-ignored)=
# Snapshots, Solos, And Ignored Snapshots

MatchPatch measures snapshots inside each selected preset. You choose how many
snapshots to measure in the Misc tab.

For Helix, the current maximum is 8 snapshots.

## Snapshot Names

MatchPatch reads snapshot names from the Helix file. Names matter because the
GUI can use them to identify solos and snapshots that should be skipped.

Clear snapshot names make the automatic behavior easier to understand.

(help-snapshot-count)=
## Solo Snapshots

Solo snapshots are detected by name. By default, a snapshot with `solo` in the
name is treated as a solo.

Solo snapshots:

- are marked with a star in the table;
- get the configured solo boost;
- are still measured like normal snapshots.

Example:

```text
Snapshot name: Solo
Solo boost: +3 dB
```

That snapshot gets the normal MatchPatch adjustment plus the solo boost.

## Ignored Snapshots

Ignored snapshots are skipped. They are shown in grey, and their adjustment cell
shows `-`.

A snapshot might be ignored when:

- it is unused;
- it is a placeholder;
- it is a special effect that should not be normalized;
- it still has a default name such as `SNAPSHOT 4`.

(help-snapshot-regex)=
## Changing Detection

The LUFS tab contains regex fields for Solo and Ignored snapshot names. In
musician terms, these are name-matching rules.

If you change the ignored rule, the table updates right away.

> Warning:
> Make sure ignored snapshots are truly safe to skip. MatchPatch will not adjust
> them.

> Tip:
> Naming snapshots clearly, such as `Clean`, `Crunch`, `Lead`, and `Solo`, makes
> MatchPatch easier to read.


## Next Step

- Read measured results: [Reading Results](reading-results.md)
- Normalize a full setlist: [Normalize A Setlist](../workflows/normalize-setlist.md)
