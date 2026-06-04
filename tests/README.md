# Test Suite

MatchPatch uses pytest with branch coverage configured in `pyproject.toml`.
Tests live directly under `tests/` and are organized by module or workflow.

## Running Tests

Use the existing WSL environment:

```bash
scripts/sync-wsl.sh
$HOME/.local/share/matchpatch/.venv-wsl/bin/pytest
```

For GUI-focused work:

```bash
scripts/test-gui.sh
```

Pass normal pytest arguments through the GUI wrapper:

```bash
scripts/test-gui.sh tests/test_gui.py::test_loaded_file_updates_window_title_and_save_as_state
```

Do not rely on bare `pytest`; it may not be on `PATH`.

## Categories

- `test_analysis.py`: LUFS windowing, crest factor, invalid audio shapes, and
  analysis edge cases.
- `test_audio.py`: `sounddevice` routing, ASIO setup, device resolution, channel
  validation, pre/post-roll, and latency trimming.
- `test_cli.py`: top-level `matchpatch` CLI behavior.
- `test_config.py`: TOML config loading, default export, precedence helpers, and
  channel mapping parsing.
- `test_devices.py`: device registry and base device contracts.
- `test_helix.py`: Helix patch IDs, file-handler delegation to the legacy
  utility, MIDI steering, metadata/diff handling, and CSV translation.
- `test_measure.py`: native measurement worker behavior, loopback and simulated
  backends, hardware backend wiring via mocks, CSV output, progress events, and
  worker CLI parsing.
- `test_normalize.py`: WSL orchestration, config merging, Windows command
  construction, cancellation, retained CSV handling, deferred export, and
  workflow error handling.
- `test_preset_handling.py`: legacy Helix gain math, custom/manual adjustments,
  routing conversion, and name validation.
- `test_progress.py`: structured progress JSON serialization.
- `test_gui_app.py`: GUI app bootstrap helpers, WSLg runtime, desktop entry, and
  terminal interrupt handling.
- `test_gui_dialogs.py`: About/Help dialogs and Qt message filtering.
- `test_gui.py`: main-window behavior, preset table editing, CSV import/export,
  metadata display, save/save-as workflow, worker integration, cancellation, and
  hardware-check behavior.

Some working trees may also contain in-progress tests for measurement timing
optimization; treat those as feature work until tracked.

## Fixtures And Helpers

Most tests create temporary inputs with `tmp_path` instead of storing binary
fixtures. Important recurring fixtures/helpers:

- `tmp_path`: temporary files for config, CSVs, patch placeholders, and retained
  workflow directories.
- `monkeypatch`: replaces subprocess, audio, MIDI, dialogs, and profile lookups
  so tests stay deterministic and hardware-free.
- `capsys`: asserts CLI stdout/stderr and error reporting.
- `app` fixture in GUI tests: module-scoped `QApplication`, with
  `QT_QPA_PLATFORM=offscreen`.
- `load_legacy_preset_handling`: imports `Python/preset_handling.py` directly so
  legacy behavior can be tested without installing it as a package module.
- `FakePatchFileHandler`, `FakeDeviceProfile`, and GUI-local fake dialogs/workers
  isolate workflow and UI behavior from real files and devices.

The bundled reference DI under `audio/reference-di/` is production data rather
than a unit-test fixture. Tests generally synthesize short NumPy signals unless
they specifically need reference-file loading behavior.

## Hardware And Integration Boundaries

The suite is intended to run without connected Helix hardware.

Hardware-facing code is tested with mocks:

- `sounddevice` functions are monkeypatched in audio and measurement tests.
- MIDI output discovery and ports are monkeypatched for Helix steering tests.
- `HardwareBackend` is tested for delegation and wait behavior, not real audio.
- Native Windows worker calls are asserted as subprocess command construction.

Portable integration behavior uses:

- `LoopbackBackend` for device-independent audio analysis smoke tests.
- `SimulatedHardwareBackend` for stateful preset/snapshot steering, routing
  validation, deterministic gain changes, and injected preset failures.

There are currently no custom pytest markers such as `hardware` or
`integration` registered in the checked-in configuration. If real hardware tests
are added later, mark them explicitly and keep them opt-in so CI and ordinary
developer runs remain hardware-free.

## GUI Notes

GUI tests import PySide6 with `pytest.importorskip("PySide6")`; they skip if the
GUI extra is not installed. The GUI wrapper defaults to `tests/test_gui.py`.

Prefer focused GUI tests for small widget, dialog, and table changes. Broaden
only when behavior crosses file loading, normalization, save/export, or worker
flows. Avoid real blocking dialogs by monkeypatching `QFileDialog` and
`QMessageBox` as the existing tests do.

## Property Tests

Hypothesis is used for small invariants such as patch ID round-trips and channel
parsing. Keep generated examples cheap and deterministic; the suite should stay
fast enough for pre-push hooks.
