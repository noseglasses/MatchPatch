# MatchPatch Example Device Plugin

This package is a minimal, read-only example of the
`matchpatch.devices` entry point. It is useful as a starting point for plugin
discovery and settings experiments, not as a complete device integration.

Install it into the same environment as MatchPatch while developing:

```bash
pip install -e examples/device_plugin
```

The important metadata is:

```toml
[project.entry-points."matchpatch.devices"]
example-device = "matchpatch_example_device:ExampleDeviceProfile"
```

After installation, `matchpatch --device example-device ...` can discover the
profile, but normalization still needs real file parsing, measurement-file
creation, and adjustment application before it can be useful.
