"""Keep a late Ctrl+C from spoiling a clean exit.

When the terminal app closes, the ``robo`` command still has a goodbye to
print and a few files to tidy. People press Ctrl+C two or three times to quit,
and the extra presses land right there. With nothing left to interrupt, an
extra press must not turn the goodbye into a Python traceback (or, on Windows,
into cmd.exe's "Terminate batch job (Y/N)?" from the ``robo.cmd`` launcher).

:func:`ignore_ctrl_c` switches Ctrl+C off for that short stretch and returns
the function that switches it back on.
"""

from __future__ import annotations

import signal
import sys
from typing import Callable, Optional

__all__ = ["ignore_ctrl_c"]

# SetConsoleMode flag: the console turns Ctrl+C into an interrupt for every
# program attached to it instead of handing the key to whoever reads input.
ENABLE_PROCESSED_INPUT = 0x0001
_STD_INPUT_HANDLE = -10


def _noop() -> None:
    return None


def _silence_console_ctrl_c(get_mode, set_mode, flush_input) -> Callable[[], None]:
    """Stop the console from turning Ctrl+C into an interrupt.

    ``get_mode(std_handle_id)`` returns the console mode, or ``None`` when the
    stream is not a console (redirected from a file or pipe). Returns the undo:
    it drops the Ctrl+C keystrokes typed meanwhile, so they are not handed to
    the shell as input, and puts the mode back exactly as it was.
    """
    mode = get_mode(_STD_INPUT_HANDLE)
    if mode is None or not mode & ENABLE_PROCESSED_INPUT:
        return _noop
    if not set_mode(_STD_INPUT_HANDLE, mode & ~ENABLE_PROCESSED_INPUT):
        return _noop

    def undo() -> None:
        flush_input(_STD_INPUT_HANDLE)
        set_mode(_STD_INPUT_HANDLE, mode)

    return undo


def _win32_flush_input(std_id: int) -> bool:
    """Discard whatever is waiting in a console input buffer."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.FlushConsoleInputBuffer.argtypes = [wintypes.HANDLE]
    kernel32.FlushConsoleInputBuffer.restype = wintypes.BOOL
    handle = kernel32.GetStdHandle(std_id)
    if not handle or handle == ctypes.c_void_p(-1).value:
        return False
    return bool(kernel32.FlushConsoleInputBuffer(handle))


def _silence_windows_console() -> Callable[[], None]:
    from robo_cli.stdio import _win32_console_mode_fns

    get_mode, set_mode = _win32_console_mode_fns()
    return _silence_console_ctrl_c(get_mode, set_mode, _win32_flush_input)


def _ignore_sigint() -> Optional[Callable[[], None]]:
    """Ignore SIGINT; return the undo, or ``None`` when it cannot be changed
    here (signal handlers can only be set from the main thread)."""
    try:
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (ValueError, OSError):
        return None
    if previous is None:
        # The handler in place was not installed from Python; the best
        # equivalent to hand back is Python's own default.
        previous = signal.default_int_handler

    def undo() -> None:
        signal.signal(signal.SIGINT, previous)

    return undo


def ignore_ctrl_c() -> Callable[[], None]:
    """Switch Ctrl+C off for this process; return the function that undoes it.

    Never raises, and neither does the returned function, which is safe to
    call more than once. Child processes started meanwhile ignore Ctrl+C too,
    which is what cleanup commands want.
    """
    undos: list[Callable[[], None]] = []
    try:
        sigint_undo = _ignore_sigint()
        if sigint_undo is not None:
            undos.append(sigint_undo)
        if sys.platform == "win32":
            undos.append(_silence_windows_console())
    except Exception:
        pass

    def restore() -> None:
        while undos:
            undo = undos.pop()
            try:
                undo()
            except Exception:
                pass

    return restore
