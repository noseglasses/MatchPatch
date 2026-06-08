(help-custom-adjustments)=
# Custom Adjustments

Use custom adjustments when one preset snapshot needs an intentional musical
exception from the normal loudness target.

For example, one intro snapshot might need to be quieter, or one featured lead
snapshot might need to be louder than the usual solo boost.

## Before You Start

- Decide which preset slots need exceptions.
- Decide which snapshots need small dB changes.
- Keep the values modest at first.
- Know how many snapshots MatchPatch will measure.

See also: [Snapshots, Solos, And Ignored Snapshots](../concepts/snapshots-solos-and-ignored.md).

## How To Think About It

Custom adjustments are added on top of the normal MatchPatch calculation.

Example:

| Preset | Snapshot | Musical goal | Custom adjustment |
|---|---|---|---|
| `01A` | 2 | Lead should lift a little more | `+1.5 dB` |
| `04C` | 1 | Intro should sit back | `-2.0 dB` |

## Simple File Example

For four measured snapshots, a custom adjustment file can look like this:

```text
01A,0,1.5,,-2
04C,-2,,,
```

The first value is the preset slot. The next values are snapshot 1, snapshot 2,
snapshot 3, and snapshot 4.

Empty cells mean no custom adjustment for that snapshot.

## Steps

1. Create the custom adjustment file.
2. Open MatchPatch.
3. Open your setlist or preset.
4. Open Advanced.
5. Go to Files.
6. Browse for the Custom adjustments file.
7. Start normalization.
8. Review the table.


## Reading The Table

Custom adjustments appear in blue parentheses.

Example:

```text
+1.0 (+1.5)
```

The value in parentheses is the custom adjustment.

## What Success Looks Like

- The custom adjustment file loads without an error.
- The affected snapshots show blue parenthesized values.
- The saved file reflects the intended musical exceptions.

## If Something Goes Wrong

- If the file is rejected, check the number of columns.
- If a preset does not change, confirm the preset slot matches the table.
- If the adjustment feels too strong, reduce the value and rerun or edit
  manually.
- If you are unsure, remove the custom adjustment and use the normal target first.

> Warning:
> Custom adjustments are added on top of normal MatchPatch calculations. Use
> small values first.

If the file does not load, see [Troubleshooting](../troubleshooting.md).
