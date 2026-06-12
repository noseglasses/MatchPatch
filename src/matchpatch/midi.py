"""Small wrappers around MIDI backend discovery."""

from __future__ import annotations


def midi_output_names() -> list[str]:
    try:
        import mido

        return list(mido.get_output_names())
    except ModuleNotFoundError as exc:
        if exc.name in {"mido", "mido.backends.rtmidi", "rtmidi"}:
            raise ValueError(
                "MIDI output backend is unavailable. Reinstall MatchPatch or run the "
                "Windows environment sync, then connect the device and try again."
            ) from exc
        raise
    except ImportError as exc:
        raise ValueError(
            "MIDI output backend is unavailable. Reinstall MatchPatch or run the "
            "Windows environment sync, then connect the device and try again."
        ) from exc
