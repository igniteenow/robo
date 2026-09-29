"""Windows ConPTY bridge for the `robo dashboard` chat tab.

Drop-in counterpart to ``robo_cli.pty_bridge.PtyBridge`` for native
Windows. Mirrors the exact public surface the ``/api/pty`` WebSocket
handler in ``robo_cli.web_server`` consumes: ``spawn``, ``read``,
``write``, ``resize``, ``close``, ``is_available``, plus the
``PtyUnavailableError`` type.

Backed by ``pywinpty`` (already a declared win32 dependency in
pyproject.toml) instead of ``ptyprocess``/``fcntl``/``termios``, none of
which exist on native Windows. The read/write/terminate calls here match
the working winpty usage already shipping in ``tools/process_registry.py``.
"""

from __future__ import annotations

import logging
import os
import select
import sys
import time
from typing import Optional, Sequence

try:
    from winpty import PtyProcess  # type: ignore
    _PTY_AVAILABLE = sys.platform.startswith("win")
except ImportError:  # pragma: no cover - non-Windows or pywinpty missing
    PtyProcess = None  # type: ignore
    _PTY_AVAILABLE = False


__all__ = ["WinPtyBridge", "PtyUnavailableError"]


# Same clamp ceiling as the POSIX bridge: a broken winsize probe must never
# reach the resize call. ConPTY tolerates large values better than ioctl,
# but we keep parity to avoid layout surprises.
_MIN_DIMENSION = 1
_MAX_COLS = 2000
_MAX_ROWS = 1000


# Coalescing ConPTY output into whole screen updates (see
# WinPtyBridge._with_trailing_pieces): a gap longer than _COALESCE_GAP_S ends
# the update; _COALESCE_MAX_S / _COALESCE_MAX_CHARS bound the added latency
# and the message size while output streams without pause.
_COALESCE_GAP_S = 0.003
_COALESCE_MAX_S = 0.012
_COALESCE_MAX_CHARS = 256 * 1024


_slow_pywinpty_warned = False


def _pywinpty_major(version: str) -> Optional[int]:
    try:
        return int(str(version).split(".", 1)[0])
    except (TypeError, ValueError):
        return None


def _warn_if_slow_pywinpty(version: Optional[str] = None) -> bool:
    """Log once when pywinpty < 3 is installed (100 ms stall per 4 KB read).

    Returns True when the warning applies. ``version`` is for tests.
    """
    global _slow_pywinpty_warned
    if version is None:
        try:
            import winpty  # type: ignore

            version = getattr(winpty, "__version__", "")
        except Exception:
            return False
    major = _pywinpty_major(version)
    if major is None or major >= 3:
        return False
    if not _slow_pywinpty_warned:
        _slow_pywinpty_warned = True
        logging.getLogger(__name__).warning(
            "pywinpty %s makes the dashboard chat slow on Windows (it waits "
            "100 ms before every 4 KB of output). Update Robo, or run: "
            "python -m pip install \"pywinpty>=3.0.5,<4\"",
            version,
        )
    return True


def _encode(data) -> bytes:
    if isinstance(data, bytes):
        return data
    # NOTE: pywinpty decodes internally, so a multibyte UTF-8 sequence
    # can in theory split across reads. xterm.js tolerates the rare
    # replacement char; this is the one fidelity tradeoff vs the POSIX
    # raw-fd path.
    return data.encode("utf-8", errors="replace")


def _clamp(value: int, maximum: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return _MIN_DIMENSION
    if n < _MIN_DIMENSION:
        return _MIN_DIMENSION
    if n > maximum:
        return maximum
    return n


class PtyUnavailableError(RuntimeError):
    """Raised when a PTY cannot be created on this platform."""


class WinPtyBridge:
    """pywinpty-backed bridge with the same interface as ``PtyBridge``.

    ``web_server`` calls :meth:`read` inside ``run_in_executor``, so a
    blocking/polling read here never stalls the event loop. ConPTY exposes
    no selectable fd, so we poll with a short sleep instead of ``select``.
    """

    def __init__(self, proc: "PtyProcess") -> None:  # type: ignore[name-defined]
        self._proc = proc
        self._closed = False

    # -- lifecycle --------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        return bool(_PTY_AVAILABLE)

    @classmethod
    def spawn(
        cls,
        argv: Sequence[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
        cols: int = 80,
        rows: int = 24,
    ) -> "WinPtyBridge":
        if not _PTY_AVAILABLE:
            if PtyProcess is None:
                raise PtyUnavailableError(
                    "pywinpty is not installed. Install with: pip install pywinpty"
                )
            raise PtyUnavailableError("ConPTY is unavailable on this platform.")
        # See pty_bridge.py: exact-preservation factory for the env=None fallback.
        from tools.environments.local import build_subprocess_env
        spawn_env = (
            build_subprocess_env(scrub_secrets=False, inherit_profile_home=False)
            if env is None else dict(env)
        )
        if not spawn_env.get("TERM"):
            spawn_env["TERM"] = "xterm-256color"
        _warn_if_slow_pywinpty()
        # pywinpty mirrors ptyprocess: dimensions=(rows, cols).
        # This call shape is the one already used in tools/process_registry.py.
        proc = PtyProcess.spawn(  # type: ignore[union-attr]
            list(argv),
            cwd=cwd,
            env=spawn_env,
            dimensions=(rows, cols),
        )
        return cls(proc)

    @property
    def pid(self) -> int:
        return int(self._proc.pid)

    def is_alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self._proc.isalive())
        except Exception:
            return False

    # -- I/O --------------------------------------------------------------

    def read(self, timeout: float = 0.2) -> Optional[bytes]:
        """Child output: one screen update's worth, up to ~256 KiB.

        Returns bytes, ``b""`` when nothing is available this tick, or
        ``None`` once the child has exited (EOF).
        """
        if self._closed:
            return None
        try:
            data = self._proc.read(65536)  # pywinpty returns str
        except EOFError:
            return None
        except Exception:
            return None
        if not data:
            # No fd to select on; poll politely so the executor thread
            # doesn't pin a core while the TUI is idle.
            time.sleep(min(timeout, 0.02))
            return b""
        return b"".join(_encode(piece) for piece in self._with_trailing_pieces(data))

    def _with_trailing_pieces(self, first):
        """``first`` plus the pieces of the same screen update behind it.

        pywinpty's reader thread forwards ConPTY output in 4096-char pieces,
        about a millisecond apart, so one TUI frame arrives as several reads.
        Sent one by one, the browser can paint between them and show half a
        frame. Keep reading while the next piece follows within
        ``_COALESCE_GAP_S`` (bounded in time and size) and send the frame
        whole. Needs pywinpty's socket (``fileobj``); without it, returns
        ``first`` alone, as before.
        """
        pieces = [first]
        sock = getattr(self._proc, "fileobj", None)
        if sock is None:
            return pieces
        size = len(first)
        deadline = time.monotonic() + _COALESCE_MAX_S
        while size < _COALESCE_MAX_CHARS:
            wait = min(_COALESCE_GAP_S, deadline - time.monotonic())
            if wait <= 0:
                break
            try:
                ready, _, _ = select.select([sock], [], [], wait)
            except (OSError, ValueError):
                break
            if not ready:
                break
            try:
                more = self._proc.read(65536)
            except Exception:
                # EOF (or a dead socket) — the next read() reports it.
                break
            if more:
                pieces.append(more)
                size += len(more)
        return pieces

    def write(self, data: bytes) -> None:
        if self._closed or not data:
            return
        try:
            # The dashboard sends raw keystroke bytes; pywinpty.write wants text.
            self._proc.write(data.decode("utf-8", errors="replace"))
        except Exception:
            return

    def resize(self, cols: int, rows: int) -> None:
        if self._closed:
            return
        cols = _clamp(cols, _MAX_COLS)
        rows = _clamp(rows, _MAX_ROWS)
        try:
            self._proc.setwinsize(rows, cols)  # pywinpty: (rows, cols)
        except Exception:
            pass

    # -- teardown ---------------------------------------------------------

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._proc.terminate(force=True)
        except Exception:
            pass

    def __enter__(self) -> "WinPtyBridge":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
