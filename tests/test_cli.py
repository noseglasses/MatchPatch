from __future__ import annotations

import sys
import tomllib

from matchpatch import cli


def test_devices_command_lists_helix(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["matchpatch", "--devices"])

    cli.main()

    assert "helix\tLine 6 Helix" in capsys.readouterr().out


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
