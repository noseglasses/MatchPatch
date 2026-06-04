# Commands

Canonical commands for MatchPatch development. Run from the repository root.

## Environment

Create or update the shared WSL development environment:

```bash
scripts/sync-wsl.sh
```

Activate it when running commands interactively:

```bash
source "$HOME/.local/share/matchpatch/.venv-wsl/bin/activate"
```

Create or update the native Windows environment used for hardware audio/MIDI
work from WSL:

```bash
scripts/sync-windows-from-wsl.sh
```

The Windows environment is stored in `.venv-windows`. The WSL environment is
stored under `${XDG_DATA_HOME:-$HOME/.local/share}/matchpatch/.venv-wsl`.

## Test

Use the shared WSL pytest binary:

```bash
$HOME/.local/share/matchpatch/.venv-wsl/bin/pytest
```

Run a focused test:

```bash
$HOME/.local/share/matchpatch/.venv-wsl/bin/pytest tests/test_measure.py::test_loopback_backend_writes_compatible_csv
```

Run GUI tests:

```bash
scripts/test-gui.sh
```

Run a focused GUI test:

```bash
scripts/test-gui.sh tests/test_gui.py::test_loaded_file_updates_window_title_and_save_as_state
```

Do not rely on bare `pytest`; it may not be on `PATH`. Avoid `uv run pytest`
for local work when the project-local `.venv` is stale or incomplete.

## Quality

After syncing and activating the WSL env:

```bash
ruff check .
ruff format --check .
ty check
$HOME/.local/share/matchpatch/.venv-wsl/bin/pytest
```

Run the same local hooks used for pre-push:

```bash
pre-commit install --install-hooks
pre-commit run --all-files --hook-stage pre-push
```

CI runs equivalent `uv run --frozen --no-default-groups --group wsl` commands on
Linux, Windows, and WSL for Python 3.12, 3.13, and 3.14.

## Run The CLI

Show environment:

```bash
matchpatch --environment
```

List supported processor profiles:

```bash
matchpatch --devices
```

Export default config:

```bash
matchpatch --export-default-config ~/.config/matchpatch/config.toml
```

Normalize without hardware:

```bash
matchpatch normalize --device helix --backend loopback -i setlist.hls -o setlist_adjusted.hls -S 01A --keep-temp
```

Normalize with simulated hardware:

```bash
matchpatch normalize --device helix --backend simulated -i setlist.hls -o setlist_adjusted.hls -S 01A,01B --keep-temp
```

Guided hardware workflow:

```bash
matchpatch normalize --device helix -a -i setlist.hls
```

Single `.hlx` preset measurement requires one temporary Helix slot:

```bash
matchpatch normalize --device helix -a -i Song.hlx -S 12A
```

Select only presets changed relative to an earlier setlist:

```bash
matchpatch normalize --device helix -a -i current.hls --diff-input previous.hls
```

## Native Measurement Worker

From WSL, list native Windows audio/MIDI devices:

```bash
scripts/measure-windows-from-wsl.sh devices
```

Run a direct loopback measurement:

```bash
python -m matchpatch.measure measure --device helix --backend loopback --preset-ids 1,6 --csv /tmp/lufs_analysis.csv --reference-di audio/reference-di/DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav
```

Run the Windows worker from WSL:

```bash
scripts/measure-windows-from-wsl.sh measure --device helix --backend hardware --preset-ids 1,6 --csv "$(wslpath -w /tmp/lufs_analysis.csv)" --reference-di "$(wslpath -w audio/reference-di/DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav)"
```

Check hardware availability:

```bash
scripts/measure-windows-from-wsl.sh check-hardware --device helix
```

## GUI

Install GUI dependencies into the WSL env:

```bash
scripts/sync-wsl.sh --extra gui
```

Launch:

```bash
matchpatch-gui
```

The GUI starts with the configured backend and can run loopback/simulated flows
without Helix hardware. Hardware mode requires the native Windows environment
and visible audio/MIDI endpoints.

## Legacy Helix Utilities

Run from the repository root:

```bash
python3 Python/preset_handling.py --help
python3 Python/decrypt_hls.py --help
python3 Python/encrypt_hls.py --help
```

Useful integrated operations:

```bash
python3 Python/preset_handling.py -i setlist.hls -o setlist_measurement.hls --measurement
python3 Python/preset_handling.py -i setlist.hls --list-presets
python3 Python/preset_handling.py -i current.hls --diff-presets previous.hls
```

## Build

Build wheel and source distribution:

```bash
uv build --no-sources
```

Smoke-test built artifacts:

```bash
uv run --isolated --no-project --with dist/*.whl python -c "import matchpatch"
uv run --isolated --no-project --with dist/*.tar.gz python -c "import matchpatch"
```

## Packaging

Application packaging is not yet completed in the checked-in project. Current
canonical package artifacts are the Python wheel and source distribution built
with `uv build --no-sources`.

Brand assets for future app packaging live in `doc/assets/`.

## Docs

There is no separate docs build configured yet. Developer docs are plain
Markdown under `docs/dev/`; project-facing documentation is in `README.md`.

Suggested checks for docs-only changes:

```bash
ruff format --check .
git diff --check
```

## Release

Release automation is tag-driven and publishes to PyPI from GitHub Actions.

1. Update `project.version` in `pyproject.toml`.
2. Commit the version change.
3. Tag with `v<version>` matching `pyproject.toml`.
4. Push the tag.

```bash
git tag v0.1.0
git push origin v0.1.0
```

The release workflow verifies the tag/version match, runs `uv build
--no-sources`, smoke-tests the wheel and source distribution, then publishes
with PyPI trusted publishing. Additional release packaging is pending.
