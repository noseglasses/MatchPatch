## Noseglasses
Record a demo video that can be displayed on the readme page in github.
The first thing the demo displays is the about window (with the logo and the VERSION).

Remove your name from any Preset/Snapshot information!

## Agent

The icon after the status word in the Status pane is a wireframe box rather than a proper emoji. Fix.

The first colum (selected files) is too wide. It should be exactly as wide as the contained checkboxes.

Use fa-star as solo icon in highlighted snapshot name colums of the presets table instead of the currently used icon.

Make sure that any zero valued db values in the gain adjustment colums are displayed as 0 (without a leading +).

Preset table is still not sortable by clicking on column headers. Please fix.

Add a setlist diff feature: In presets tab of the advanced pane there should be a file selection displayed that allows for selecting a "previous version" of the hls file. There should also be a "select modified" button next to the file selection. When this button is clicked, only those presets are activated (selected) whose representations differ from those defined in the setlist file selected in the general pane.
Presets differ if either the block ordering (wiring) or the block parameters changed. Presets do NOT differ if only the preset name changed or the colors associated to the preset or any blocks. Only changes that can affect the preset sound and loudness must be considered.
The file selection and "select modified" button must only be displayed after a hls file was selected in the general pane. They must not be visisble if a hlx file was selected.

---

Add an emoji after the status word displayed in the Progress pane. E.g. something that represents a celebration if "Completed" is displayed and a warning symbol if something goes wrong and also a suitable emoji that represents measurment going on. (done, tested)

Remove the colum header of the first colum "Selected". It is already obvious that this column is about selection. (done, tested)

The solo icon displayed in the snapshot name column is rendered as a square outline. Fix this. (done, tested)

Make sure that there are no line wraps in the presets table of the GUI, e.g. in adjustment columns.
Add the unit (dB) to the headers of the adjustment columns and do not display it behind the actual values in the adjustment column cells. (done, tested)

Allow the presets table to sorted by clicking on column headers. (done, tested)

Add below the preset selection table a Label that says that only the non-empty presets are being listed. (done, tested)

Add a nice explanatory/motivating preface/introduction to the README.md. Something in the line of "You are playing in a cover band, having one preset per song. Have you ever struggled with getting your presets and snapshots to equal volume? Are your sound engineers frequently mad with you because of that? Nobody heard your gorgious solo because the output level was too low? Then MatchPatch is the right tool for you.". Keep the wording concise and catchy. (done, tested)

Make the README.md more GUI centered and add the CLI command information later on in the text. (done, tested)

The project logo in the About window is displayed too small. The text below the logo symbol is barely unreadable. Enlarge. (done, tested)

Do the following for the MatchPatch gui (python code in src/matchpatch/gui):
Mark rows in the preset table of those presets that has associated snapshots where bad LUFS values were registered during measurment by giving them a light red background (or is there a better way of highlighting?). (done)