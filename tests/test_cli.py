from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from matchpatch import cli
from matchpatch.file_operations import JoinPresetFilesResult, SplitSetlistFileResult


def test_devices_command_lists_helix(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["matchpatch", "--devices"])

    cli.main()

    output = capsys.readouterr().out
    assert "helix\tLine 6 Helix" in output
    assert "podgo\tLine 6 Pod Go" in output


def test_normalize_command_is_dispatched(monkeypatch) -> None:
    import matchpatch.normalize

    calls = []
    monkeypatch.setattr(matchpatch.normalize, "main", calls.append)
    monkeypatch.setattr(sys, "argv", ["matchpatch", "normalize", "--device", "helix"])

    cli.main()

    assert calls == [["--device", "helix"]]


def test_measure_command_is_dispatched(monkeypatch) -> None:
    import matchpatch.measure

    calls = []
    monkeypatch.setattr(matchpatch.measure, "main", calls.append)
    monkeypatch.setattr(
        sys, "argv", ["matchpatch", "measure", "check-hardware", "--device", "helix"]
    )

    cli.main()

    assert calls == [["check-hardware", "--device", "helix"]]


def test_files_join_command_dispatches_file_operation(monkeypatch, capsys) -> None:
    from matchpatch import file_operations

    calls = []

    def fake_join_preset_files(device, preset_paths, output_path, *, slot_ids=None):
        calls.append((device, preset_paths, output_path, slot_ids))
        return JoinPresetFilesResult(output_path=output_path)

    monkeypatch.setattr(file_operations, "join_preset_files", fake_join_preset_files)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "matchpatch",
            "files",
            "join",
            "--device",
            "helix",
            "--output",
            "out.hls",
            "--preset-set",
            "01A,02B",
            "preset1.hlx",
            "preset2.hlx",
        ],
    )

    cli.main()

    assert calls == [
        (
            "helix",
            [Path("preset1.hlx"), Path("preset2.hlx")],
            Path("out.hls"),
            [1, 6],
        )
    ]
    assert "Joined 2 preset files into out.hls" in capsys.readouterr().out


def test_files_split_command_dispatches_file_operation(monkeypatch, capsys) -> None:
    from matchpatch import file_operations

    calls = []

    def fake_split_setlist_file(device, input_path, output_dir, *, selected_ids=None):
        calls.append((device, input_path, output_dir, selected_ids))
        return SplitSetlistFileResult(created_paths=[output_dir / "Lead.hlx"])

    monkeypatch.setattr(file_operations, "split_setlist_file", fake_split_setlist_file)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "matchpatch",
            "files",
            "split",
            "--device",
            "helix",
            "--input",
            "setlist.hls",
            "--output-dir",
            "presets",
            "--preset-set",
            "01A",
        ],
    )

    cli.main()

    assert calls == [("helix", Path("setlist.hls"), Path("presets"), [1])]
    output = capsys.readouterr().out
    assert "Split 1 preset files into presets" in output
    assert str(Path("presets") / "Lead.hlx") in output


def test_environment_command_prints_runtime(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["matchpatch", "--environment"])

    cli.main()

    output = capsys.readouterr().out
    assert "MatchPatch " in output
    assert "Platform:" in output
    assert "Python  :" in output


def test_export_default_config_command_writes_toml(tmp_path, monkeypatch, capsys) -> None:
    path = tmp_path / "defaults.toml"
    monkeypatch.setattr(sys, "argv", ["matchpatch", "--export-default-config", str(path)])

    cli.main()

    output = capsys.readouterr().out
    assert "Wrote default config:" in output
    assert tomllib.loads(path.read_text(encoding="utf-8"))["normalize"]["backend"] == "hardware"


def test_no_command_prints_help(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["matchpatch"])

    cli.main()

    output = capsys.readouterr().out
    assert "usage:" in output
    assert "Normalization command:" in output
