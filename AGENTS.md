# MatchPatch Agent Notes

Python package in `src/matchpatch`; legacy Helix JSON/HLS utilities live in `Python/`.
Use existing WSL env, not bare `pytest` or a stale project `.venv`:

```bash
scripts/sync-wsl.sh
$HOME/.local/share/matchpatch/.venv-wsl/bin/pytest
```

For GUI work use:

```bash
scripts/test-gui.sh [pytest args]
```

Quality checks:

```bash
ruff check .
ruff format --check .
ty check
```

Run them from the synced WSL env, or via the pre-push hook. GUI tests use PySide6
with offscreen Qt. Prefer focused tests in `tests/test_gui.py` for window/widget
changes, and broaden only when behavior crosses workflows.

MatchPatch normalizes Helix `.hls` setlists and `.hlx` presets. Core flow:
`workflow.py` creates/uses measurement CSVs, `normalize.py` bridges WSL to the
native Windows worker, `measure.py` records/analyzes audio, device profiles adapt
processor files and steering. Keep new device-specific behavior behind
`DeviceProfile`/`PatchFileHandler`/`DeviceController`. Preserve the user’s dirty
worktree; do not revert unrelated edits. Prefer `rg`, focused patches, and tests
that mock hardware unless the user explicitly asks for real-device integration.
