# Device Plugins

MatchPatch discovers third-party device profiles with the
`matchpatch.devices` Python entry point group. The built-in Helix profile is
registered directly in `matchpatch.devices.registry`; plugins use packaging
metadata instead.

```toml
[project.entry-points."matchpatch.devices"]
my-device = "my_package.matchpatch_plugin:MyDeviceProfile"
```

The loaded object may be a `DeviceProfile` instance, a `DeviceProfile` subclass,
or an iterable of `DeviceProfile` instances. Every profile must expose a unique
non-empty `name`, a non-empty `display_name`, and
`create_patch_file_handler(project_dir)`. Duplicate names and import errors are
recorded by the registry and reported by `plugin_load_errors()` or when an
unknown device is requested.

## Profile Contract

Device plugins implement `matchpatch.devices.base.DeviceProfile`. The required
methods are:

- `create_patch_file_handler(project_dir)`: returns the file adapter for the
  device.
- `default_audio_routing()`: returns an `AudioRouting` default for device name,
  sample rate, and one-based stereo input/output channels.
- `default_steering_options()`: returns `SteeringOptions` for MIDI or other
  target selection timing defaults.
- `create_controller(options)`: returns a `DeviceController` that can activate
  numeric presets and one-based subdivisions for hardware-style measurement.

Profiles may also override `terminology()`, `file_capabilities()`,
`measurement_backends()`, `audio_transport_factories()`,
`diagnostics_provider()`, `naming_rules()`, `setting_descriptors()`, and
`format_patch_id()`.

## Settings Descriptors

`DeviceSettingDescriptor` is the GUI-free settings surface. MatchPatch uses it
to resolve defaults, config paths, CLI flags, validation, diagnostics, and the
generic GUI settings panel.

The default `DeviceProfile.setting_descriptors()` returns descriptors for:

- `audio_device`, `sample_rate`, `input_mapping`, `output_mapping`, and
  `blocksize` under the `audio` scope.
- `midi_output`, `midi_channel`, `preset_wait`, `snapshot_wait`, and
  `measurement_wait` under the `steering` scope.

Descriptors support `string`, `integer`, `float`, `boolean`, `choice`, `path`,
and `channel_mapping` kinds. Numeric ranges, choices, `required`, labels, help
text, config paths, and CLI flags are enforced or rendered by the existing
settings code. Unknown settings are currently ignored by
`DeviceProfile.validate_settings()`.

## Diagnostics Providers

A profile can return a `DiagnosticsProvider` from `diagnostics_provider()`.
During preflight, MatchPatch builds a `DiagnosticsContext` containing the
normalization request, profile, file handler, resolved device settings, and
project directory, then calls `run_checks(context)`.

The provider returns `DiagnosticCheck` objects from `matchpatch.diagnostics`.
Provider exceptions are caught and turned into a failed `device_diagnostics`
check, so a broken plugin does not stop the rest of preflight.

## Audio Transports

Profiles can provide custom audio backends with `audio_transport_factories()`.
Each `AudioTransportFactory` has `capabilities`, `supports(mode, settings)`,
and `create(context)`. MatchPatch checks plugin factories before its built-in
hardware, loopback, and simulated factories.

`AudioTransportCapabilities` declares the backend mode and behavior such as
sample rates, channel layout, real-time/offline operation, async operation,
alignment guarantees, and debug-output support. The supported backend names
advertised by `measurement_backends()` must include any plugin-only mode the
profile expects to use, such as `offline`.

The created transport implements either `process(reference_audio)` for
real-time style processing or `process_offline(request)` for offline rendering.

## Target Model

Patch handlers expose measurable content as `MeasurementTarget` objects. A
target has an `id`, display label, zero-based `index`, name, optional source
filename, optional `compat_numeric_id`, target-level gain points, and
subdivisions.

Subdivisions are `MeasurementSubdivision` objects. The built-in Helix profile
uses snapshots as subdivisions, but plugins can use string IDs and labels for
other device concepts. Legacy numeric preset/snapshot helpers are still present:
if a handler only implements `list_assignments()`, MatchPatch adapts
`PatchAssignment` values into measurement targets and subdivisions.

## File Handlers And Capabilities

`PatchFileHandler` is responsible for device-owned files. Required methods
validate input/output paths, list assignments, parse numeric preset selectors,
select presets, format numeric IDs, create measurement files, apply analysis
CSVs, and build automation output paths.

Optional methods describe richer devices:

- `file_types()` and `file_kind()` advertise user-facing extensions.
- `file_capabilities()` returns `FileOperationCapabilities`, which gates GUI and
  command support for reading/writing preset files, reading/writing setlist
  files, joining presets into setlists, splitting setlists, replacing setlist
  slots, and exporting selected slots.
- `list_targets()`, `parse_target_set()`, `select_targets()`,
  `diff_targets()`, and `diff_subdivisions()` support non-Helix target IDs.
- `list_gain_points()` and `apply_gain_adjustments()` support target-level or
  subdivision-level gain points.

The default capabilities are all false, and unsupported optional operations
raise `NotImplementedError`.

## Optional GUI Panels

GUI-only plugins can register a settings panel factory with the
`matchpatch.device_gui_panels` entry point group:

```toml
[project.entry-points."matchpatch.device_gui_panels"]
my-device-panel = "my_package.matchpatch_gui:MyPanelFactory"
```

The loaded object may be a factory object or a callable returning one. It must
define `device_name` and `create_panel(profile, backend_selector)`. If
`device_name` matches the active profile name, the returned `QWidget` replaces
the built-in or descriptor-rendered settings panel. GUI panel load errors are
logged and recorded by `matchpatch.gui.device_panel_registry.plugin_load_errors()`.

Plugins that do not need custom Qt controls should prefer settings descriptors;
the generic renderer handles the current descriptor kinds.

## Minimal Example

A small read-only example plugin lives in `examples/device_plugin/`. It shows
the package metadata entry point and the minimum profile/file-handler classes
needed for discovery. It is intentionally not a complete processor integration:
the file handler lists no targets and raises for measurement and save operations.
