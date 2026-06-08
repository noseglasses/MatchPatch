# Screenshot Capture Plan

This directory is reserved for MatchPatch documentation screenshots.

Phase 6 completed the screenshot inventory and capture plan. Real screenshots
are still intentionally pending; the user-facing docs keep textual screenshot
placeholders until images are captured and reviewed.

## Capture Rules

- Use realistic musician examples.
- Avoid private file paths, private preset names, and personal user names.
- Prefer cropped screenshots when only one control matters.
- Keep the GUI readable at documentation size.
- Use the same visual theme and window size across related screenshots.
- Use `.png` files.
- Add alt text when replacing placeholders in docs.

## Suggested Filename Style

Use short lowercase names:

```text
main-window-start.png
open-file-screen.png
loaded-setlist.png
backend-selector.png
hardware-routing.png
timing-tab.png
failed-measurement-row.png
save-as-dialog.png
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

## Group 1: First-Run And Navigation

Capture these with the app newly opened or just after opening a file.

| Placeholder | Suggested File |
|---|---|
| MatchPatch main window after launch | `main-window-start.png` |
| Open-file screen with recent files | `open-file-screen.png` |
| Open a setlist or preset | `open-setlist-or-preset.png` |
| Full main window with Advanced visible | `main-window-advanced.png` |

## Group 2: Backend And Hardware Setup

Capture these from Advanced > Device.

| Placeholder | Suggested File |
|---|---|
| Backend selector | `backend-selector.png` |
| Backend set to loopback | `backend-loopback.png` |
| Backend set to simulated | `backend-simulated.png` |
| Backend set to hardware | `backend-hardware.png` |
| Helix audio routing settings | `helix-audio-routing.png` |
| Audio routing settings | `helix-audio-routing.png` |
| Helix MIDI steering settings | `helix-midi-steering.png` |
| Hardware check overlay | `hardware-check-overlay.png` |
| Hardware error popup | `hardware-error-popup.png` |

## Group 3: Setlist And Preset Tables

Capture these after opening realistic example files.

| Placeholder | Suggested File |
|---|---|
| Loaded .hls setlist | `loaded-setlist.png` |
| Selected presets | `selected-presets.png` |
| Preset table with selected presets | `selected-presets.png` |
| Preset table column labels | `preset-table-columns.png` |
| Single preset table | `single-preset-table.png` |
| Temporary preset slot cell | `temporary-slot-cell.png` |
| Missing preset ID highlight for .hlx | `missing-slot-highlight.png` |
| Missing slot warning | `missing-slot-warning.png` |
| Select changed button | `select-changed-button.png` |
| Previous setlist file picker | `previous-setlist-picker.png` |
| Changed presets selected | `changed-presets-selected.png` |

## Group 4: Snapshot Meaning And Results

Capture these with a completed or seeded result table.

| Placeholder | Suggested File |
|---|---|
| Solo snapshot star | `solo-star.png` |
| Ignored snapshot styling | `ignored-snapshot.png` |
| Solo and ignored regex fields | `solo-ignored-regex.png` |
| Successful result row | `successful-result-row.png` |
| Completed results table | `completed-results-table.png` |
| Completed loopback run | `completed-loopback-run.png` |
| Running measurement progress | `running-measurement-progress.png` |
| Failed measurement highlight | `failed-measurement-highlight.png` |
| Bad LUFS highlighted row | `bad-lufs-row.png` |
| Measurement failed adjustment cell | `measurement-failed-cell.png` |
| Custom adjustment displayed in blue | `custom-adjustment-blue.png` |
| Blue custom adjustment annotation in table | `custom-adjustment-blue.png` |
| Recorded-output playback button | `recorded-output-button.png` |
| Out dB and Delta dB cells | `out-delta-cells.png` |
| Retained CSV field, if temporary files are kept | `retained-csv-field.png` |

## Group 5: Files, Saving, And Importing

Capture these from toolbar actions and dialogs.

| Placeholder | Suggested File |
|---|---|
| Save / Save As buttons | `save-toolbar-buttons.png` |
| Save button enabled after results | `save-enabled.png` |
| Save As dialog | `save-as-dialog.png` |
| Save Measurement File dialog | `save-measurement-dialog.png` |
| Save Measurement File toolbar button | `save-measurement-button.png` |
| Completion popup | `completion-popup.png` |
| Completion popup telling user to save | `completion-popup.png` |
| Overwrite warning | `overwrite-warning.png` |

## Group 6: Timing And Optimization

Capture these from Advanced > Timing and the parameter study dialogs.

| Placeholder | Suggested File |
|---|---|
| Timing tab | `timing-tab.png` |
| Measurement time estimate | `measurement-time-estimate.png` |
| Determine optimal parameters button | `determine-parameters-button.png` |
| Parameter study setup dialog | `parameter-study-setup.png` |
| Parameter study progress table | `parameter-study-progress.png` |
| TOML result and Apply button | `parameter-study-result.png` |

## Group 7: Manual Editing, CSV, And Custom Adjustments

Capture these from table editing and Files tab controls.

| Placeholder | Suggested File |
|---|---|
| Edit manually checkbox | `edit-manually-checkbox.png` |
| Inline cell editor | `inline-cell-editor.png` |
| CSV open/save buttons | `csv-buttons.png` |
| CSV error popup | `csv-error-popup.png` |
| Custom adjustments file picker | `custom-adjustments-picker.png` |
| Reference DI field | `reference-di-field.png` |

## Group 8: Loudness And Diagrams

Capture or create these after deciding whether real screenshots or simple
diagrams are clearer.

| Placeholder | Suggested File |
|---|---|
| Loudness bar on target | `loudness-on-target.png` |
| Loudness bar above target | `loudness-above-target.png` |
| spiky signal versus compressed signal | `crest-factor-diagram.png` |

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
