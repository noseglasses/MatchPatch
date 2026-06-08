(help-lufs-loudness)=
# LUFS And Loudness

LUFS is a way to measure perceived loudness. It is more useful than only looking
at the highest peak, because a sound can have low peaks and still feel loud, or
high peaks and still feel quiet.

MatchPatch uses LUFS to decide how much each preset snapshot should move up or
down.

## Target LUFS

Target LUFS is the loudness MatchPatch tries to match.

If a snapshot measures below the target, MatchPatch raises it. If a snapshot
measures above the target, MatchPatch lowers it.

The default target is a starting point. Use it first unless you already have a
musical reason to change it.

## Why Peaks Are Not Enough

A clean sound with sharp attacks may hit high peaks without feeling very loud.
A compressed lead sound may have lower peaks but feel much louder because its
average energy is higher.

That is why MatchPatch measures loudness, not just peak level.

## The Loudness Bar

During measurement, the GUI shows the latest loudness reading.

The loudness bar shows:

- where the measured sound sits;
- where the target sits;
- whether the result is close or far from the target.

The text will say whether the sound is above target, below target, or on target.

## Final Listening Still Matters

LUFS is a strong guide, but it cannot know the full band mix. A bright lead, a
dark rhythm tone, and a clean ambient part may sit differently even when the
numbers are close.

> Warning:
> Use LUFS to get close. Use your ears to make final musical decisions.


## Next Step

- Learn how results appear: [Reading Results](reading-results.md)
- Set solo behavior: [Snapshots, Solos, And Ignored Snapshots](snapshots-solos-and-ignored.md)
