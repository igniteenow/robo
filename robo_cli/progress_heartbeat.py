"""A line every half minute while a long, quiet step runs.

``npm ci`` with its progress display off, the Electron packager, a vite
build: minutes of work that print nothing a person can read, on a terminal
that otherwise looks frozen. People close the window. This prints

    … installing desktop packages (1 min 30 s) — a few minutes the first time

on an interval until the step finishes, so the wait is visibly alive and
roughly sized. It is a thread, not a progress bar: it never needs to know how
far along the step is, and it writes whole lines, so it cannot garble a
terminal that something else is writing to.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator, Optional, TextIO

DEFAULT_INTERVAL_SECONDS = 30.0


def format_elapsed(seconds: float) -> str:
    """``45 s`` · ``1 min 30 s`` · ``12 min 05 s``."""
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    if minutes == 0:
        return f"{secs} s"
    return f"{minutes} min {secs:02d} s"


def heartbeat_line(label: str, elapsed: float, hint: str = "") -> str:
    tail = f" — {hint}" if hint else ""
    return f"  … {label} ({format_elapsed(elapsed)}){tail}"


@contextmanager
def heartbeat(
    label: str,
    *,
    hint: str = "",
    interval: float = DEFAULT_INTERVAL_SECONDS,
    out: Optional[TextIO] = None,
    write: Optional[Callable[[str], None]] = None,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[None]:
    """Print ``heartbeat_line`` every *interval* seconds until the block ends.

    *write* takes one complete line (without newline); default prints to
    *out* (``sys.stdout`` at call time) and flushes. The hint is shown on the
    first line only — after that the elapsed time says it all. Never raises
    into the caller: a broken pipe or a closed stream stops the beat quietly.
    """
    stop = threading.Event()
    started = clock()

    def _emit(line: str) -> None:
        try:
            if write is not None:
                write(line)
                return
            import sys

            stream = out if out is not None else sys.stdout
            stream.write(line + "\n")
            stream.flush()
        except Exception:
            stop.set()

    def _run() -> None:
        first = True
        while not stop.wait(interval):
            _emit(heartbeat_line(label, clock() - started, hint if first else ""))
            first = False

    thread = threading.Thread(target=_run, name="robo-progress-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1.0)
