# Adding Devices

MatchPatch keeps device support in the source tree. Adding a device should be a
small, explicit change:

1. Add a new package under `src/matchpatch/devices/`.
2. Implement a `DeviceProfile`, `PatchFileHandler`, and, when needed, a
   `DeviceController`.
3. Add one instance of the profile to `DEVICE_PROFILES` in
   `src/matchpatch/devices/available.py`.
4. Add focused tests for the profile, file handler, and any GUI behavior.

The in-tree demo device in `src/matchpatch/devices/demo/` is the reference
implementation for developers. It is deterministic, offline, heavily commented,
and intentionally simple. Its `.demobank` JSON format is fake example data, not
a recommendation for real processor file formats.

## Directory Layout

Each device gets its own sibling directory:

```text
src/matchpatch/devices/
  available.py
  base.py
  demo/
    __init__.py
  helix/
    __init__.py
    file_ops.py
    preset_handling.py
  line6/
    common.py
    file_ops.py
    helix/
      __init__.py
    podgo/
      __init__.py
      preset_handling.py
```

For a new device named `my_device`, create:

```text
src/matchpatch/devices/my_device/
  __init__.py
```

Large devices can split helpers into additional files inside that directory.
Keep device-specific parsing, subprocess adapters, SDK wrappers, and steering
code inside the device package.

## Registration

Register built-in devices in exactly one place:

```python
# src/matchpatch/devices/available.py
from matchpatch.devices.my_device import MyDeviceProfile

DEVICE_PROFILES = (
    HelixDeviceProfile(),
    PodGoDeviceProfile(),
    DemoDeviceProfile(),
    MyDeviceProfile(),
)
```

The registry validates the list and exposes `get_device_profile(name)` and
`list_device_profiles()`. Built-in Line 6 devices currently include `helix` and
`podgo`. Device names must be unique, non-empty strings. The GUI, CLI, config
loader, workflows, diagnostics, and file-operation helpers all use that same
registry, so adding the profile instance makes the device selectable everywhere.

## DeviceProfile

`DeviceProfile` describes device-wide behavior. The demo profile shows the
minimum shape:

```python
class DemoDeviceProfile(DeviceProfile):
    name = "demo-device"
    display_name = "Demo Device"
    snapshot_count = 2
    max_snapshot_count = 8

    def create_patch_file_handler(self, project_dir: Path) -> PatchFileHandler:
        return DemoPatchFileHandler()

    def default_audio_routing(self) -> AudioRouting:
        return AudioRouting(None, 48000, (1, 2), (1, 2))

    def default_steering_options(self) -> SteeringOptions:
        return SteeringOptions(None, 1, 0.0, 0.0, 0.0)

    def create_controller(self, options: SteeringOptions) -> DeviceController:
        return DemoController()
```

Required methods:

- `create_patch_file_handler(project_dir)` returns a fresh file adapter.
- `default_audio_routing()` returns audio defaults. Channel mappings are
  one-based stereo pairs.
- `default_steering_options()` returns target-selection defaults. MIDI channels
  are zero-based.
- `create_controller(options)` returns a controller for hardware-style target
  and subdivision activation.

Useful optional overrides:

- `terminology()` changes words such as device, preset, snapshot, and setlist.
- `file_capabilities()` advertises device-level file operations.
- `measurement_backends()` declares supported measurement modes.
- `audio_transport_factories()` adds custom device audio transports.
- `diagnostics_provider()` adds preflight checks.
- `supports_normalization()` and `normalization_unavailable_message()` let
  example, inspection-only, or file-operation-only devices appear in the GUI
  without starting normalization.
- `naming_rules()` validates and sanitizes device-owned names.
- `setting_descriptors()` defines GUI-free settings.
- `format_patch_id()` formats numeric preset IDs for status text and CSVs.

The demo device intentionally returns `False` from `supports_normalization()`.
When selected in the GUI, pressing Normalize shows a short message explaining
that Demo Device is only an example and cannot normalize files.

## PatchFileHandler

`PatchFileHandler` owns device files. MatchPatch calls it for path validation,
target discovery, selector parsing, measurement-file creation, adjustment
writes, and file-operation workflows.

Required methods:

- `validate_input(input_path)` checks source files.
- `validate_output(input_path, output_path)` checks destination files.
- `list_assignments(input_path)` returns legacy numeric `PatchAssignment`
  values.
- `parse_patch_set(value)` parses numeric preset selectors.
- `select_preset_ids(input_path, assignments, requested_ids)` resolves legacy
  numeric preset selections.
- `format_patch_id(preset_id)` formats numeric IDs.
- `create_measurement_file(input_path, output_path)` writes a measurement
  variant.
- `apply_analysis_csv(...)` writes normalized output from MatchPatch analysis.
- `automation_output_path(input_path, postfix)` builds device-compatible
  sibling output paths.

The demo handler implements these methods for a small JSON file. Real devices
should use structured parsing for their actual file format and should preserve
unknown or unrelated fields when writing adjusted files.

## Targets And Gain Points

Modern devices should implement `list_targets()` in addition to
`list_assignments()`. This avoids forcing every processor into Helix-style
numeric preset IDs.

`MeasurementTarget` models a measurable top-level item. IDs may be integers or
strings. Targets include a display label, zero-based index, name, optional
source filename, optional numeric compatibility ID, target-level gain points,
and subdivisions.

`MeasurementSubdivision` models snapshots, scenes, channels, layers, or any
within-target concept. The demo device maps presets to targets and scenes to
subdivisions:

```python
MeasurementTarget(
    id="preset:clean",
    display_label="D001",
    index=0,
    name="Clean",
    subdivisions=(
        MeasurementSubdivision(
            id="scene:intro",
            display_label="Intro",
            index=0,
            name="Intro",
            gain_points=(GainPoint(...),),
        ),
    ),
    compat_numeric_id=1,
)
```

Use `GainPoint` for adjustable device controls. Set `scope="target"` for
target-level controls and `scope="subdivision"` for per-scene or per-snapshot
controls. Override `apply_gain_adjustments(input_path, output_path,
adjustments)` when the device can apply explicit gain changes. The demo device
supports one subdivision gain point named `main-output` and changes only a
scene's `output_level_db`, leaving unrelated JSON data intact.

## File Types And Capabilities

File metadata drives GUI filters, validation, and file-operation commands.

`file_types()` returns user-facing extensions:

```python
DeviceFileType(
    kind="setlist",
    extensions=(".demobank",),
    description="Demo Device Banks",
)
```

`file_kind(path)` classifies paths as `"preset"`, `"setlist"`, or `"unknown"`.
`file_capabilities()` returns `FileOperationCapabilities`:

- `reads_preset_files` and `writes_preset_files`;
- `reads_setlist_files` and `writes_setlist_files`;
- `joins_presets_to_setlist`;
- `splits_setlist_to_presets`;
- `replaces_setlist_slots`;
- `exports_selected_setlist_slots`.

Only advertise operations the handler really implements. Unsupported optional
operations should keep the base behavior, which raises `NotImplementedError`.

## Settings And GUI

`DeviceSettingDescriptor` is the device settings API. MatchPatch uses
descriptors for config defaults, CLI flags, validation, diagnostics, and the
generic GUI settings panel.

Descriptor fields include:

- `name`, `scope`, and `kind`;
- `default`;
- `config_path`;
- `cli_flags`;
- `label` and `help`;
- `choices`, `minimum`, `maximum`, and `required`.
- `show_in_gui`, which defaults to `True`.

Supported kinds are `string`, `integer`, `float`, `boolean`, `choice`, `path`,
and `channel_mapping`. The base `validate_settings()` checks required settings,
types, numeric ranges, choices, and one-based channel mappings. Unknown settings
are ignored so config files can carry values for code that has not loaded them.

The base `DeviceProfile.setting_descriptors()` already exposes common audio and
steering settings. Override it when a device needs different defaults or
device-specific settings. The demo adds a `demo_mode` choice setting, and the
GUI uses the generic `DescriptorSettingsPanel` for it automatically. The demo
also marks `preset_wait`, `snapshot_wait`, and `measurement_wait` with
`show_in_gui=False`: those settings remain available to config, CLI, and
normalization plumbing, but they are hidden from the device panel because the
GUI already exposes them in the timing tab.

If a device needs a bespoke GUI, add it directly to
`src/matchpatch/gui/device_panels.py` and keep device-specific widgets small.
Prefer descriptors whenever possible.

## Validation And Diagnostics

Validation happens in layers:

- registry validation checks profile names, display names, and handler creation;
- `validate_settings(settings)` validates descriptors;
- `validate_input()` and `validate_output()` reject unsupported paths before
  writing;
- `naming_rules()` can enforce device name limits and allowed characters.

For preflight checks, return a `DiagnosticsProvider` from
`diagnostics_provider()`. MatchPatch passes a `DiagnosticsContext` containing
the request, profile, handler, resolved settings, and project directory. Provider
exceptions are caught and reported as failed diagnostics.

## Audio Transports

Most hardware-style devices can use the built-in hardware, loopback, or
simulated backends. Devices that need custom processing can return factories
from `audio_transport_factories()`.

An `AudioTransportFactory` exposes:

- `capabilities`, an `AudioTransportCapabilities` object;
- `supports(mode, settings)`;
- `create(context)`.

Created transports implement `process(reference_audio)` for real-time style
measurement or `process_offline(request)` for offline rendering. If your device
expects a custom mode such as `offline`, include that mode in
`measurement_backends()`.

## Testing A Device

Keep new device tests deterministic and offline unless hardware coverage is
explicitly required. Follow `tests/test_devices.py` and
`tests/test_gui_settings_renderer.py`:

- assert the profile is listed by the static registry;
- write a small fixture in a temporary directory;
- verify `list_targets()`, `list_gain_points()`, and selectors;
- verify adjustment writes mutate only the intended fields;
- verify unsupported capabilities fail clearly;
- verify GUI selection when the device should appear in the main window;
- add focused parser tests for any real file format helpers.

Useful checks while developing device-facing changes:

```bash
UV_CACHE_DIR=/tmp/matchpatch-uv-cache UV_PROJECT_ENVIRONMENT="$HOME/.local/share/matchpatch/.venv-wsl" uv run --frozen --no-default-groups --group wsl pytest tests/test_devices.py tests/test_gui_settings_renderer.py
UV_CACHE_DIR=/tmp/matchpatch-uv-cache UV_PROJECT_ENVIRONMENT="$HOME/.local/share/matchpatch/.venv-wsl" uv run --frozen --no-default-groups --group wsl ruff check src/matchpatch/devices tests/test_devices.py tests/test_gui_settings_renderer.py
UV_PROJECT_ENVIRONMENT="$HOME/.local/share/matchpatch/.venv-wsl" uv run --frozen --no-default-groups --group docs sphinx-build -W --keep-going -b html docs docs_html
```
