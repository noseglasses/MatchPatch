# Project Improvements: 2026-06-12

This plan captures a broad quality, usability, maintainability, and product
polish scan of MatchPatch performed on 2026-06-12.

The project is already in a strong place. It is not a toy codebase: it has a
modern `src/` package layout, substantial user and developer documentation,
installer support, CI across Linux, Windows, and WSL, hardware-free tests for
hardware-facing behavior, and a clear device abstraction.

The next level is less about basic hygiene and more about making the existing
power easier to trust, easier to debug, and easier to evolve.

## Scan Scope

Reviewed areas:

- repository structure and top-level files;
- package metadata and dependency groups in `pyproject.toml`;
- README and Sphinx docs;
- core workflow, normalization, measurement, audio, config, and device modules;
- GUI window and worker structure;
- legacy Helix utilities under `Python/`;
- tests and testing guidance;
- GitHub Actions quality workflow;
- code size, TODO-like markers, broad exception handling, and coverage results.

Primary files and directories sampled:

- `README.md`
- `pyproject.toml`
- `.github/workflows/quality.yml`
- `docs/`
- `tests/`
- `src/matchpatch/`
- `src/matchpatch/gui/`
- `src/matchpatch/devices/`
- `Python/`
- `installer/`
- `scripts/`

## Verification Result

The full test suite was run with the existing WSL environment:

```bash
$HOME/.local/share/matchpatch/.venv-wsl/bin/pytest --cov=matchpatch --cov-report=term-missing
```

Result:

- `379 passed in 41.14s`
- total coverage: `86%`

Notable coverage readings:

- `src/matchpatch/gui/main_window.py`: `84%`
- `src/matchpatch/normalize.py`: `85%`
- `src/matchpatch/measure.py`: `87%`
- `src/matchpatch/workflow.py`: `96%`
- `src/matchpatch/devices/helix.py`: `92%`
- `src/matchpatch/gui/worker.py`: `65%`
- `src/matchpatch/custom_adjustments.py`: `75%`

The suite produced a coverage warning:

- `Module matchpatch was previously imported, but not measured`

The warning did not fail the run, but it is worth cleaning up if coverage
reporting should become stricter or more reproducible.

## Current Strengths

MatchPatch already has several unusually good foundations:

- installable Python package under `src/matchpatch`;
- top-level CLI and GUI console scripts;
- GUI-first user workflow;
- Sphinx documentation with user concepts, workflows, troubleshooting, FAQ, and
  developer docs;
- CI across Linux, Windows, WSL, and Python 3.12 through 3.14;
- Ruff lint, Ruff format check, `ty check`, pytest, docs build, and installer
  smoke tests in CI;
- Windows installer support with PyInstaller and Inno Setup;
- hardware-facing tests that mock audio and MIDI instead of requiring a Helix;
- loopback and simulated measurement backends;
- clear device-extension interfaces in `DeviceProfile`, `PatchFileHandler`, and
  `DeviceController`;
- a strong safety posture around backups, measurement files, and bad LUFS rows.

## Main Improvement Themes

The highest-leverage improvements fall into four themes:

1. Reduce maintenance drag from large modules.
2. Make hardware workflows easier to diagnose and trust.
3. Turn measurement data into clearer musician-facing guidance.
4. Make extension points real enough for future devices and contributors.

## Highest-Leverage Improvements

### 1. Split The GUI Monolith

`src/matchpatch/gui/main_window.py` is about 7,755 lines. The matching GUI test
file, `tests/test_gui.py`, is about 5,404 lines.

This is the main maintainability hotspot. It is a sign of a capable product
that has grown organically, not a failure, but it raises the cost of future
feature work.

Extract candidates:

- preset table model and table state;
- measurement result parsing and row/cell status calculation;
- save/export workflow;
- advanced settings state and config binding;
- hardware check UI flow;
- retained CSV/result presentation;
- logging panel behavior;
- import-confirmation dialog flow;
- reusable GUI formatting helpers.

Expected benefits:

- smaller, more focused tests;
- easier review of GUI changes;
- less risk when adding workflow features;
- easier reuse by future dialogs or panels;
- clearer separation between Qt widgets and domain state.

### 2. Retire Or Package The Legacy `Python/` Layer

The modern Helix adapter still delegates important `.hls` and `.hlx` work to
`Python/preset_handling.py`, which is about 1,853 lines.

The current adapter boundary in `src/matchpatch/devices/helix.py` is useful, but
shelling out to a legacy script keeps a quality ceiling in place.

Recommended direction:

- move reusable Helix parsing and rewriting into importable package modules;
- keep old scripts as thin CLI wrappers for compatibility;
- migrate one behavior at a time through the existing test suite;
- preserve the current `PatchFileHandler` interface while replacing the
  subprocess implementation internally;
- use structured return types instead of parsing stdout where practical.

Expected benefits:

- better error reporting;
- less subprocess/process-state complexity;
- easier type checking;
- easier unit testing;
- easier future support for non-Helix devices;
- cleaner installer behavior in frozen builds.

### 3. Make Diagnostics First-Class

Hardware/audio/MIDI workflows are inherently hard to troubleshoot. MatchPatch
already has logs and progress events, but an extraordinary version should make
diagnostics exportable and user-friendly.

Add a diagnostic bundle or "Doctor" feature that collects:

- MatchPatch version;
- Python executable and runtime mode;
- platform and WSL/native status;
- selected backend;
- active device profile;
- resolved config values after precedence;
- config file path;
- reference DI path and sample rate validation result;
- audio device list;
- MIDI output list;
- selected input/output channel mappings;
- recent progress events;
- recent GUI log lines;
- retained CSV path and row summary;
- failed/ignored/skipped snapshot summary;
- optional recorded-output metadata.

GUI affordances:

- "Run preflight check";
- "Export diagnostic bundle";
- "Copy diagnostic summary";
- "Open troubleshooting page for this error".

Implementation status:

- Implemented: GUI Diagnostics tab with "Run preflight check",
  "Copy diagnostic summary", "Export diagnostic bundle", log view, and privacy
  notice.
- Implemented: diagnostic bundle export with summary text, JSON, effective
  config, GUI logs, progress events, and safe retained-CSV summaries.
- Implemented: structured hardware diagnostics for native `check-hardware` and
  WSL/GUI collection, including improved automatic hardware-check reporting.
- Implemented: preflight checks for request/config summary, device profile,
  input/output validation, reference DI, custom adjustments, backend, hardware
  diagnostics, and snapshot selection.
- Implemented: focused worker cancellation/failure tests and docs updates.
- Remaining: a standalone `matchpatch diagnose` CLI command and direct
  audio/MIDI device-list capture in exported bundles are still future work.

Expected benefits:

- faster support;
- fewer mysterious hardware failures;
- safer user self-diagnosis;
- better bug reports.

### 4. Add A Guided Setup And Preflight Wizard

The docs are good, but the app should guide musicians through the risky setup
path directly.

Suggested preflight flow:

1. Choose backend: loopback for learning, hardware for real measurement.
2. Validate input file.
3. Validate reference DI path and sample rate.
4. Detect audio device.
5. Detect MIDI output.
6. Validate channel capacity.
7. Run a one-preset or loopback smoke measurement.
8. Explain any failure with specific next steps.

Expected benefits:

- better first-run experience;
- fewer failed full-setlist measurements;
- less reliance on users reading docs in the right order;
- more confidence before writing adjusted files.

### 5. Add Richer Measurement Confidence Reporting

MatchPatch currently calculates LUFS and crest factor and flags problematic
rows. The next step is turning raw measurement outcomes into guidance.

Add confidence labels or explanations such as:

- signal present;
- silence suspected;
- clipping suspected;
- unstable loudness across analysis windows;
- high crest-factor correction applied;
- manual override applied;
- solo boost applied;
- ignored by snapshot rule;
- skipped because unchanged;
- output gain unchanged because of deadband;
- unsafe or out-of-range adjustment prevented.

Possible UI labels:

- `Trusted`
- `Check`
- `Skipped`
- `Manual`
- `Failed`

Expected benefits:

- more musician-friendly results;
- clearer safety posture;
- easier decision-making after a run;
- better session reports.

### 6. Use Stronger Typed Config And Request Validation

`src/matchpatch/config.py` currently uses loose `dict[str, Any]`, while
`src/matchpatch/normalize.py` performs a lot of merging, casting, and fallback
logic.

Recommended direction:

- introduce typed config dataclasses for normalized settings;
- keep the existing TOML format stable;
- separate raw TOML loading from validated effective config;
- expose a single effective-config object to CLI and GUI;
- include source information where helpful, such as CLI, environment, config,
  or device default.

Expected benefits:

- fewer config precedence bugs;
- clearer diagnostics;
- easier GUI binding;
- easier type checking;
- simpler docs.

### 7. Make Device Extensibility More Real

The device abstraction is already a strong start:

- `DeviceProfile`
- `PatchFileHandler`
- `DeviceController`

To make this extraordinary, add a second-device skeleton or simulated reference
device that exercises the interface without requiring real hardware.

Recommended work:

- document the minimal implementation steps for a new device;
- add a fake/test profile outside GUI tests;
- ensure generic workflow docs do not assume Helix everywhere;
- identify and remove Helix-specific assumptions from core and GUI paths;
- add tests that prove the GUI can load and use a non-Helix profile in a basic
  loopback/simulated workflow.

Expected benefits:

- hardens the architecture;
- invites contributors;
- makes future processor support less expensive.

### 8. Improve CLI Ergonomics

`src/matchpatch/cli.py` manually forwards `normalize` and `measure`.

Consider a more discoverable subcommand tree:

- `matchpatch normalize`
- `matchpatch measure`
- `matchpatch devices`
- `matchpatch config export`
- `matchpatch diagnose`
- `matchpatch doctor`
- `matchpatch environment`

Expected benefits:

- clearer help output;
- better power-user experience;
- easier scripting;
- easier docs.

### 9. Raise Coverage Where It Matters

Do not chase 100% coverage for its own sake. Add tests around the highest-risk
behavior:

- GUI worker cancellation and failure paths;
- Windows worker process cancellation;
- config edge cases and invalid TOML shapes;
- save/export failure handling;
- retained CSV handling after partial failures;
- custom adjustment parsing and validation;
- hardware check error presentation;
- coverage warning cleanup.

Priority files:

- `src/matchpatch/gui/worker.py`
- `src/matchpatch/custom_adjustments.py`
- `src/matchpatch/normalize.py`
- selected branches in `src/matchpatch/gui/main_window.py`

### 10. Polish Release Trust

CI and installer smoke tests are already strong. Additional release polish:

- signed Windows installer;
- published SHA256 checksums;
- release notes generated from conventional commits;
- GUI About dialog includes environment and version details;
- diagnostic output includes build/install channel;
- release checklist verifies docs, screenshots, installer, PyPI, and GitHub
  Release artifacts.

## Product Features That Would Make MatchPatch Shine

Potential high-impact user-facing features:

- one-click "measure changed presets only" as a prominent workflow;
- before/after loudness visualization per preset and snapshot;
- exportable session report with CSV plus human-readable summary;
- A/B listening helper using recorded processed output;
- preset risk labels such as silent, clipped, unstable, adjusted, unchanged, or
  manual override;
- batch preset-name and snapshot-name tools folded into the GUI;
- automatic backup creation before writing adjusted files;
- hardware profile presets for common Helix routing setups;
- sample/demo workflow so new users can learn without finding their own files;
- clearer "safe to trust" summary after measurement;
- built-in link from each warning to the relevant troubleshooting section.

## Suggested Priority Waves

### Wave 1: Trust And Diagnosis

Goal: make failures easier to understand before changing core architecture.

Status: substantially implemented. The GUI now has a Diagnostics tab with
preflight, diagnostic summary copy, diagnostic bundle export, recent logs, and a
privacy notice. Structured hardware diagnostics feed preflight and automatic
hardware-check failure reporting. Remaining work is mostly CLI-level diagnosis
and future polish.

Work:

- done: add diagnostic bundle export;
- done: add a GUI preflight/doctor workflow;
- done: improve hardware check reporting;
- done: expose effective config in a readable way;
- done: add focused tests for worker and cancellation failures.

Why first:

- users benefit immediately;
- support burden drops;
- the work clarifies data boundaries needed for later refactors.

### Wave 2: GUI Maintainability

Goal: reduce the cost and risk of future GUI feature work.

Work:

- extract preset table state/model;
- extract result parsing and display state;
- extract save/export workflow;
- split advanced settings state from widget construction;
- split `tests/test_gui.py` into narrower files as modules are extracted.

Why second:

- the GUI is the largest maintenance hotspot;
- product polish will be much easier afterward.

### Wave 3: Helix File-Core Modernization

Goal: replace subprocess legacy internals with importable package code.

Work:

- carve out Helix file loading/writing;
- carve out assignment listing and metadata;
- carve out diff logic;
- carve out gain application;
- keep compatibility wrappers in `Python/`;
- preserve current behavior through existing tests.

Why third:

- it is high-value but riskier;
- stronger diagnostics and cleaner GUI boundaries will make regressions easier
  to catch.

### Wave 4: Product Excellence And Extensibility

Goal: make MatchPatch feel polished and ready for broader adoption.

Work:

- richer confidence reporting;
- before/after visualizations;
- session reports;
- second-device skeleton;
- contributor-facing device guide;
- release trust polish.

Why fourth:

- these features build on the earlier structural work;
- they make the product feel extraordinary rather than merely functional.

## Concrete Near-Term Backlog

Good first implementation tickets:

1. Add `matchpatch diagnose` CLI command that prints version, platform, Python,
   config paths, device profiles, and optional audio/MIDI discovery.
2. Done: add GUI "Copy diagnostic summary" action using the same diagnostic data
   source.
3. Done: add tests for `NormalizationWorker.cancel()` while waiting for import
   confirmation.
4. Split result log parsing from `MainWindow` into a small pure module.
5. Split preset table selection state from `MainWindow` into a pure dataclass
   helper.
6. Add structured confidence flags to measurement/result rows.
7. Done: document diagnostic bundles and preflight checks in the troubleshooting,
   quick-start, and hardware-measurement docs.
8. Add a fake device profile used by tests to harden non-Helix paths.
9. Convert one small legacy Helix script behavior into an importable package
   function as a migration pilot.
10. Clean up the coverage warning so coverage output is deterministic.

## Success Criteria

The project will feel significantly stronger when:

- a new user can run a guided setup and know what to fix before a full
  measurement;
- a failed hardware run produces a useful diagnostic bundle;
- GUI feature work no longer requires editing a 7,000+ line file for routine
  changes;
- Helix file handling can be tested without subprocess indirection;
- measurement results explain trust and risk, not just numbers;
- adding a second device is documented, tested, and realistic;
- release artifacts are easy for users to verify and trust.
