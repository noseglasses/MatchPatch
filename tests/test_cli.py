from __future__ import annotations

import sys

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


def test_environment_command_prints_runtime(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["matchpatch", "--environment"])

    cli.main()

    output = capsys.readouterr().out
    assert "MatchPatch " in output
    assert "Platform:" in output
    assert "Python  :" in output


def test_no_command_prints_help(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["matchpatch"])

    cli.main()

    output = capsys.readouterr().out
    assert "usage:" in output
    assert "Normalization command:" in output
