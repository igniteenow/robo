"""Unit tests for robo_cli.win_pty_bridge — ConPTY spawning + byte forwarding.

Windows-only counterpart to tests/robo_cli/test_pty_bridge.py.  Drives
``WinPtyBridge`` with minimal Windows processes (``cmd.exe``, ``python -c …``)
to verify it behaves like a PTY you can read/write/resize/close, then a small
set of platform-fallback assertions (``is_available``, ``PtyUnavailableError``)
that run on every OS so the import surface stays exercised in CI.

The bridge is the ConPTY backend behind the dashboard ``/chat`` tab — see
``robo_cli/web_server.py`` ``/api/pty`` handler — so these tests are the
unit-level half of the integration check that the dashboard chat pane is
actually live on native Windows.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

# WinPtyBridge can be imported on every platform — ``is_available`` just
# returns False when pywinpty isn't usable.  Importing the module itself
# must never raise, otherwise the web_server import branch becomes a trap.
from robo_cli.win_pty_bridge import PtyUnavailableError, WinPtyBridge

windows_only = pytest.mark.skipif(
    not sys.platform.startswith("win"),
    reason="ConPTY bridge is Windows-only",
)


def _read_until(bridge: WinPtyBridge, needle: bytes, timeout: float = 10.0) -> bytes:
    """Accumulate PTY output until we see ``needle`` or time out.

    Mirrors the helper in test_pty_bridge.py so failures look familiar.
    """
    deadline = time.monotonic() + timeout
    buf = bytearray()
    while time.monotonic() < deadline:
        chunk = bridge.read(timeout=0.2)
        if chunk is None:
            break
        buf.extend(chunk)
        if needle in buf:
            return bytes(buf)
    return bytes(buf)


# ---------------------------------------------------------------------------
# Cross-platform fallback semantics
# ---------------------------------------------------------------------------


class TestWinPtyBridgeUnavailable:
    """Module-level surface that must stay importable on every OS so the
    web_server platform branch doesn't blow up at import time when pywinpty
    is missing or the host isn't Windows."""

    def test_error_is_importable_and_carries_message(self):
        err = PtyUnavailableError("conpty missing")
        assert "conpty" in str(err)

    def test_bridge_class_is_importable(self):
        # The platform-branched import in web_server.py relies on this:
        #     from robo_cli.win_pty_bridge import WinPtyBridge, PtyUnavailableError
        # Both symbols must always exist; ``is_available()`` is the gate.
        assert WinPtyBridge is not None
        assert callable(WinPtyBridge.is_available)

    @pytest.mark.skipif(sys.platform.startswith("win"), reason="non-Windows only")
    def test_spawn_raises_unavailable_off_windows(self):
        with pytest.raises(PtyUnavailableError):
            WinPtyBridge.spawn(["true"])


# ---------------------------------------------------------------------------
# Windows-only end-to-end behaviour
# ---------------------------------------------------------------------------


@windows_only
class TestWinPtyBridgeSpawn:

    def test_spawn_returns_bridge_with_pid(self):
        bridge = WinPtyBridge.spawn(["cmd.exe", "/c", "exit 0"])
        try:
            assert bridge.pid > 0
        finally:
            bridge.close()

    def test_spawn_raises_on_missing_argv0(self, tmp_path):
        # pywinpty wraps CreateProcessW failures; surface as OSError / RuntimeError.
        bogus = str(tmp_path / "definitely-not-a-real-binary.exe")
        with pytest.raises((FileNotFoundError, OSError, RuntimeError, PtyUnavailableError)):
            WinPtyBridge.spawn([bogus])


@windows_only
class TestWinPtyBridgeIO:

    def test_write_sends_to_child_stdin(self):
        # python -c reads stdin, echoes a marker, exits.  More reliable than
        # ``cat`` (not on Windows) and doesn't depend on a particular shell.
        script = (
            "import sys; "
            "line = sys.stdin.readline().strip(); "
            "sys.stdout.write('GOT:' + line + '\\n'); "
            "sys.stdout.flush()"
        )
        bridge = WinPtyBridge.spawn([sys.executable, "-c", script])
        try:
            bridge.write(b"hello-pty\r\n")
            output = _read_until(bridge, b"GOT:hello-pty")
            assert b"GOT:hello-pty" in output
        finally:
            bridge.close()


    def test_read_returns_none_after_child_exits(self):
        bridge = WinPtyBridge.spawn(["cmd.exe", "/c", "echo done"])
        try:
            _read_until(bridge, b"done")
            # Give the child a beat to exit, then drain until EOF.
            deadline = time.monotonic() + 5.0
            while bridge.is_alive() and time.monotonic() < deadline:
                bridge.read(timeout=0.1)
            got_none = False
            for _ in range(20):
                if bridge.read(timeout=0.1) is None:
                    got_none = True
                    break
            assert got_none, "WinPtyBridge.read did not return None after child EOF"
        finally:
            bridge.close()


@windows_only
class TestWinPtyBridgeResize:
    def test_resize_does_not_raise_on_live_child(self):
        # ConPTY exposes no ioctl-equivalent for reading the child's current
        # winsize from Python land, so we can't verify the new dimensions
        # the way the POSIX test does (which reads TIOCGWINSZ).  What we
        # CAN guarantee is what the dashboard depends on: ``resize`` never
        # raises, the bridge stays alive, and subsequent I/O still works.
        bridge = WinPtyBridge.spawn(
            [sys.executable, "-c", "import time; time.sleep(1.0)"],
            cols=80,
            rows=24,
        )
        try:
            bridge.resize(cols=123, rows=45)
            assert bridge.is_alive()
        finally:
            bridge.close()


    def test_resize_after_close_is_silent(self):
        bridge = WinPtyBridge.spawn(["cmd.exe", "/c", "exit 0"])
        bridge.close()
        # Must not raise — closed bridges still receive late resize escapes
        # from xterm.js when the browser tab is closed mid-stream.
        bridge.resize(cols=100, rows=40)


@windows_only
class TestClampDimension:
    """The clamp helper is the load-bearing piece — the dashboard sends
    untrusted winsize values straight from xterm.js, and pywinpty's
    setwinsize will happily raise on out-of-range u16 values."""

    def test_clamps_above_max(self):
        from robo_cli.win_pty_bridge import _MAX_COLS, _MAX_ROWS, _clamp

        assert _clamp(131072, _MAX_COLS) == _MAX_COLS
        assert _clamp(131072, _MAX_ROWS) == _MAX_ROWS


    def test_non_numeric_falls_back_to_min(self):
        from robo_cli.win_pty_bridge import _MAX_COLS, _clamp

        assert _clamp(None, _MAX_COLS) == 1  # type: ignore[arg-type]
        assert _clamp("not-a-number", _MAX_COLS) == 1  # type: ignore[arg-type]
        assert _clamp(float("nan"), _MAX_COLS) == 1  # type: ignore[arg-type]
        assert _clamp(float("inf"), _MAX_COLS) == 1  # type: ignore[arg-type]


@windows_only
class TestWinPtyBridgeClose:

    def test_close_terminates_long_running_child(self):
        bridge = WinPtyBridge.spawn(
            [sys.executable, "-c", "import time; time.sleep(30)"]
        )
        pid = bridge.pid
        assert bridge.is_alive(), f"child pid {pid} not alive before close"
        bridge.close()
        # The bridge itself reports liveness via pywinpty.isalive(), which is
        # the same probe the dashboard PTY reader uses to decide when to stop
        # forwarding bytes — verifying that flips to False is the contract
        # that matters for /api/pty.
        deadline = time.monotonic() + 5.0
        while bridge.is_alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not bridge.is_alive(), (
            f"WinPtyBridge.is_alive() still True after close(); pid {pid}"
        )


@windows_only
class TestWinPtyBridgeEnv:
    def test_cwd_is_respected(self, tmp_path):
        bridge = WinPtyBridge.spawn(
            [sys.executable, "-c", "import os; print(os.getcwd())"],
            cwd=str(tmp_path),
        )
        try:
            # Path is case-insensitive on Windows; compare lowercased.
            needle_resolved = str(tmp_path.resolve()).lower().encode()
            deadline = time.monotonic() + 5.0
            buf = bytearray()
            while time.monotonic() < deadline:
                chunk = bridge.read(timeout=0.2)
                if chunk is None:
                    break
                buf.extend(chunk)
                if needle_resolved in bytes(buf).lower():
                    break
            assert needle_resolved in bytes(buf).lower(), (
                f"cwd {tmp_path!s} not echoed by child; got {bytes(buf)!r}"
            )
        finally:
            bridge.close()

    def test_env_is_forwarded(self):
        bridge = WinPtyBridge.spawn(
            [
                sys.executable,
                "-c",
                "import os; print('ROBO_PTY_TEST=' + os.environ.get('ROBO_PTY_TEST',''))",
            ],
            env={**os.environ, "ROBO_PTY_TEST": "pty-env-works"},
        )
        try:
            output = _read_until(bridge, b"pty-env-works")
            assert b"pty-env-works" in output
        finally:
            bridge.close()



# ---------------------------------------------------------------------------
# Screen updates arrive whole (cross-platform: fake pywinpty over a socket)
# ---------------------------------------------------------------------------


class _SocketPtyProcess:
    """pywinpty's ``PtyProcess`` read path: ``read`` recv()s from ``fileobj``,
    the socket its reader thread feeds ConPTY output into."""

    def __init__(self):
        import socket

        self.fileobj, self.feed = socket.socketpair()

    def read(self, size=1024):
        data = self.fileobj.recv(size)
        if not data:
            raise EOFError("Pty is closed")
        return data.decode("utf-8")

    def close(self):
        self.feed.close()
        self.fileobj.close()


class TestScreenUpdatesArriveWhole:
    def test_pieces_of_one_update_come_back_as_one_read(self):
        import threading

        proc = _SocketPtyProcess()
        bridge = WinPtyBridge(proc)
        frame = [f"row{i:02d}-".encode() * 400 for i in range(5)]  # 5 pieces

        def feed():
            for piece in frame:
                proc.feed.sendall(piece)
                time.sleep(0.001)  # pywinpty's reader-thread cadence

        t = threading.Thread(target=feed)
        t.start()
        try:
            got = bridge.read(timeout=0.2)
            t.join()
            assert got == b"".join(frame)
        finally:
            proc.close()

    def test_separate_updates_are_not_merged(self):
        proc = _SocketPtyProcess()
        bridge = WinPtyBridge(proc)
        try:
            proc.feed.sendall(b"first")
            assert bridge.read(timeout=0.2) == b"first"
            time.sleep(0.05)
            proc.feed.sendall(b"second")
            assert bridge.read(timeout=0.2) == b"second"
        finally:
            proc.close()

    def test_nonstop_output_is_still_delivered_promptly(self):
        import threading

        proc = _SocketPtyProcess()
        bridge = WinPtyBridge(proc)
        stop = threading.Event()

        def flood():
            while not stop.is_set():
                try:
                    proc.feed.sendall(b"x" * 4096)
                except OSError:
                    return
                time.sleep(0.001)

        t = threading.Thread(target=flood, daemon=True)
        t.start()
        try:
            start = time.monotonic()
            got = bridge.read(timeout=0.2)
            assert got and time.monotonic() - start < 0.5
        finally:
            stop.set()
            proc.close()

    def test_eof_after_the_update_is_reported_on_the_next_read(self):
        proc = _SocketPtyProcess()
        bridge = WinPtyBridge(proc)
        proc.feed.sendall(b"bye")
        proc.feed.close()
        try:
            assert bridge.read(timeout=0.2) == b"bye"
            assert bridge.read(timeout=0.2) is None
        finally:
            proc.fileobj.close()

    def test_without_the_socket_reads_are_unchanged(self):
        class NoSocket:
            def read(self, size=1024):
                return "plain"

        assert WinPtyBridge(NoSocket()).read(timeout=0.2) == b"plain"


class TestSlowPywinptyWarning:
    def test_pywinpty_2_is_flagged_and_3_is_not(self, monkeypatch):
        import robo_cli.win_pty_bridge as bridge

        monkeypatch.setattr(bridge, "_slow_pywinpty_warned", False)
        assert bridge._warn_if_slow_pywinpty("2.0.15") is True
        assert bridge._warn_if_slow_pywinpty("3.0.5") is False
        assert bridge._warn_if_slow_pywinpty("4.1.0") is False
        assert bridge._warn_if_slow_pywinpty("not-a-version") is False
