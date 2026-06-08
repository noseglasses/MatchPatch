# Screenshot Capture Plan

This directory is reserved for MatchPatch documentation screenshots.

Phase 10 completed the screenshot inventory and capture plan. Real screenshots
are still intentionally pending; the user-facing docs keep textual screenshot
placeholders until images are captured and reviewed.

## Capture Rules

- Use realistic musician examples.
- Avoid private file paths, private preset names, and personal user names.
- Prefer workflow/state screenshots over tiny individual controls.
- Keep the GUI readable at documentation size.
- Use the same visual theme and window size across related screenshots.
- Use `.png` files.
- Add alt text when replacing placeholders in docs.

## Suggested Filename Style

Use short lowercase names:

```text
loaded-setlist.png
backend-selector.png
hardware-routing.png
timing-tab.png
completed-results-table.png
failed-measurement-row.png
save-import-dialogs.png
optimization-dialog.png
```

## README Screenshot Status

The README screenshot is still pending. Do not add an image link to `README.md`
until the file exists and has been reviewed.

Preferred README screenshot:

```text
docs/assets/screenshots/loaded-setlist.png
```

Acceptable alternatives:

- `docs/assets/screenshots/completed-results-table.png`
- `docs/assets/screenshots/main-window-advanced.png`

When the screenshot is ready, place it near the top of `README.md` with helpful
alt text, for example:

```markdown
![MatchPatch GUI showing a loaded Helix setlist](docs/assets/screenshots/loaded-setlist.png)
```

## Screenshot Inventory

Capture only these workflow and important-state screenshots for the first
documentation pass.

| Placeholder | Suggested File |
|---|---|
| loaded setlist with selected presets | `loaded-setlist.png` |
| backend selector in Advanced Device | `backend-selector.png` |
| hardware routing settings | `hardware-routing.png` |
| Timing tab with measurement estimate | `timing-tab.png` |
| Completed results table | `completed-results-table.png` |
| failed measurement row | `failed-measurement-row.png` |
| save, save-as, and import dialogs | `save-import-dialogs.png` |
| optimization setup and result dialog | `optimization-dialog.png` |

## Replacement Pattern

When a screenshot is ready, replace this:

```markdown
[Screenshot placeholder: Backend selector]
```

with this:

```markdown
![Backend selector in Advanced Device settings](assets/screenshots/backend-selector.png)
```

Adjust relative paths for nested pages:

```markdown
![Backend selector in Advanced Device settings](../assets/screenshots/backend-selector.png)
```

## Remaining Work

- Capture screenshots.
- Review screenshots for privacy and clarity.
- Replace placeholders in docs.
- Run `git diff --check -- docs`.
