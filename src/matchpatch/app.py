"""Unified MatchPatch application entry point."""

from __future__ import annotations

import sys

CLI_SWITCHES = {"--cli", "/cli"}
ATTACH_PARENT_PROCESS = 0xFFFFFFFF


def _stream_is_usable(stream: object) -> bool:
    write = getattr(stream, "write", None)
    flush = getattr(stream, "flush", None)
    if write is None or flush is None:
        return False
    try:
        write("")
        flush()
    except (AttributeError, OSError, ValueError):
        return False
    return True


def _attach_parent_console() -> bool:
    if sys.platform != "win32":
        return False

    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        attach_console = kernel32.AttachConsole
        attach_console.argtypes = [ctypes.c_uint32]
        attach_console.restype = ctypes.c_int
        attached = attach_console(ATTACH_PARENT_PROCESS) != 0
        already_attached = ctypes.get_last_error() == 5
        if not attached and not already_attached:
            return False
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    except (AttributeError, OSError, ValueError):
        return False
    return True


def _prepare_cli_stdout() -> bool:
    if _stream_is_usable(sys.stdout):
        return True
    if _attach_parent_console():
        return _stream_is_usable(sys.stdout)
    return False


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0].lower() in CLI_SWITCHES:
        if args[1:] == ["--version"] and not _prepare_cli_stdout():
            return

        from matchpatch.cli import main as cli_main

        cli_main(args[1:])
        return

    from matchpatch.gui.app import main as gui_main

    gui_main(args)


if __name__ == "__main__":  # pragma: no cover - frozen executable entry point
    main()
