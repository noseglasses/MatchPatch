# MatchPatch Agent Notes

## Testing

Use the existing WSL virtual environment for tests:

```bash
$HOME/.local/share/matchpatch/.venv-wsl/bin/pytest
```

For GUI-focused changes, prefer the wrapper:

```bash
scripts/test-gui.sh
```

You can pass normal pytest arguments through it:

```bash
scripts/test-gui.sh tests/test_gui.py::test_loaded_file_updates_window_title_and_save_as_state
```

Do not rely on bare `pytest`; it may not be on `PATH`. `uv run pytest` may also fail when the project-local `.venv` is stale or incomplete.

## GUI Tests

GUI tests live in `tests/test_gui.py` and use PySide6. Prefer focused GUI tests for small window, dialog, and widget changes, then broaden only when the changed behavior crosses multiple workflows.
