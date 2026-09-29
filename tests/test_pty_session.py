import asyncio
import time

import pytest

from robo_cli.pty_session import RingBuffer


def test_ringbuffer_keeps_everything_under_capacity():
    rb = RingBuffer(10)
    rb.append(b"abc")
    rb.append(b"def")
    assert rb.snapshot() == b"abcdef"
    assert rb.truncated is False


def test_ringbuffer_drops_oldest_over_capacity():
    rb = RingBuffer(4)
    rb.append(b"abcdef")          # 6 bytes into a 4-byte buffer
    assert rb.snapshot() == b"cdef"
    assert rb.truncated is True


def test_truncated_replay_restores_full_screen_mode():
    """The TUI's one-time mode switches can fall off the front of the ring
    buffer; a reattaching browser must still land in full screen with the
    cursor hidden and bracketed paste on (otherwise a multi-line paste would
    be submitted line by line)."""
    rb = RingBuffer(16)
    rb.append(b"\x1b[?1049h\x1b[?25l\x1b[?2004h")
    rb.append(b"x" * 40)                  # pushes the switches out
    snap = rb.snapshot()
    assert snap.startswith(b"\x1b[?1049h\x1b[?25l\x1b[?2004h")
    assert snap.endswith(b"x" * 16)


def test_mode_switch_split_across_reads_is_tracked():
    rb = RingBuffer(8)
    rb.append(b"\x1b[?10")
    rb.append(b"49h" + b"y" * 20)
    assert rb.snapshot().startswith(b"\x1b[?1049h")


def test_modes_turned_back_off_are_not_reasserted():
    rb = RingBuffer(8)
    rb.append(b"\x1b[?1049h" + b"a" * 10 + b"\x1b[?1049l")
    rb.append(b"b" * 20)
    assert rb.snapshot() == b"b" * 8


def test_untruncated_replay_is_byte_exact():
    rb = RingBuffer(1024)
    rb.append(b"\x1b[?1049hhello")
    assert rb.snapshot() == b"\x1b[?1049hhello"




class FakeBridge:
    """Implements the bridge contract PtySession depends on."""

    def __init__(self, chunks):
        self._chunks = list(chunks)   # bytes; b"" = idle tick; None = EOF
        self.written = bytearray()
        self.closed = False
        self.resized = None

    def read(self, timeout):
        if not self._chunks:
            return b""                # idle
        return self._chunks.pop(0)

    def write(self, data):
        self.written.extend(data)

    def resize(self, cols, rows):
        self.resized = (cols, rows)

    def close(self):
        self.closed = True


class FakeWS:
    def __init__(self):
        self.sent = []               # list of ("bytes"|"text", payload)
        self.close_code = None

    async def send_bytes(self, data):
        self.sent.append(("bytes", bytes(data)))

    async def send_text(self, text):
        self.sent.append(("text", text))

    async def close(self, code=1000, reason=""):
        self.close_code = code


@pytest.mark.asyncio
async def test_attach_replays_buffer_then_streams_live():
    from robo_cli.pty_session import PtySession
    bridge = FakeBridge([b"hello ", b"world", None])
    s = PtySession("k", bridge, buffer_cap=1024, read_timeout=0.01)
    await s.start()
    await asyncio.sleep(0.05)                      # drain consumes "hello world"
    ws = FakeWS()
    await s.attach(ws)
    replay = b"".join(p for kind, p in ws.sent if kind == "bytes")
    assert replay == b"hello world"
    await s.close()




@pytest.mark.asyncio
async def test_eof_marks_dead_and_closes_socket_4410():
    from robo_cli.pty_session import PtySession
    bridge = FakeBridge([b"bye", None])
    s = PtySession("k", bridge, buffer_cap=1024, read_timeout=0.01)
    await s.start()
    ws = FakeWS()
    await s.attach(ws)
    await asyncio.sleep(0.05)                      # drain hits None (EOF)
    assert s.alive is False
    assert ws.close_code == 4410
    await s.close()


from robo_cli.pty_session import PtySessionRegistry, RegistryFull


def make_registry(ttl=1800.0, max_sessions=16):
    return PtySessionRegistry(ttl=ttl, max_sessions=max_sessions,
                              buffer_cap=1024, read_timeout=0.01)


@pytest.mark.asyncio
async def test_same_key_reattaches_same_session():
    reg = make_registry()
    b1 = FakeBridge([b"", b"", b""])
    s1, created1 = await reg.attach_or_spawn("tok", spawn=lambda: b1)
    s2, created2 = await reg.attach_or_spawn("tok", spawn=lambda: FakeBridge([]))
    assert created1 is True and created2 is False
    assert s1 is s2
    assert s2.bridge is b1                     # second spawn callable was NOT used
    await reg.close_all()




@pytest.mark.asyncio
async def test_new_key_at_capacity_raises_when_none_reapable():
    reg = make_registry(max_sessions=1)
    b = FakeBridge([b"", b""])
    s, _ = await reg.attach_or_spawn("a", spawn=lambda: b)
    await s.attach(FakeWS())                    # attached → not reapable
    with pytest.raises(RegistryFull):
        await reg.attach_or_spawn("b", spawn=lambda: FakeBridge([]))
    await reg.close_all()


@pytest.mark.asyncio
async def test_reaper_loop_invokes_reap(monkeypatch):
    from robo_cli.pty_session import run_reaper
    reg = make_registry()
    calls = {"n": 0}

    async def fake_reap(now=None):
        calls["n"] += 1

    monkeypatch.setattr(reg, "reap_idle", fake_reap)
    task = asyncio.create_task(run_reaper(reg, interval=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert calls["n"] >= 2


# ---------------------------------------------------------------------------
# Two connections racing for one chat (the dashboard page reconnects while
# the first connection is still starting, e.g. when it jumps to a chat's
# latest continuation). The live viewer must never lose the PTY to the older,
# already-abandoned connection — that froze every other chat opened.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_older_connection_never_takes_the_pty_from_a_newer_one():
    from robo_cli.pty_session import PtySession
    s = PtySession("k", FakeBridge([b"", b"", b""]), buffer_cap=1024, read_timeout=0.01)
    await s.start()
    newer, older = FakeWS(), FakeWS()
    assert await s.attach(newer, seq=2) is True
    assert await s.attach(older, seq=1) is False     # finished setting up last
    assert older.close_code == 4409
    assert newer.close_code is None                  # the live viewer keeps it
    assert s.attached is True
    await s.close()


@pytest.mark.asyncio
async def test_a_newer_connection_still_takes_over():
    from robo_cli.pty_session import PtySession
    s = PtySession("k", FakeBridge([b"", b"", b""]), buffer_cap=1024, read_timeout=0.01)
    await s.start()
    first, second = FakeWS(), FakeWS()
    assert await s.attach(first, seq=1) is True
    assert await s.attach(second, seq=2) is True     # reconnect / newer tab
    assert first.close_code == 4409
    assert second.close_code is None
    await s.close()


@pytest.mark.asyncio
async def test_concurrent_connections_to_one_chat_start_one_pty():
    import threading
    reg = make_registry()
    spawned = []
    gate = threading.Event()

    def slow_spawn():
        spawned.append(1)
        gate.wait(1.0)                               # a real spawn takes a while
        return FakeBridge([b"", b"", b""])

    first = asyncio.create_task(reg.attach_or_spawn("chat", spawn=slow_spawn))
    await asyncio.sleep(0.05)
    second = asyncio.create_task(reg.attach_or_spawn("chat", spawn=slow_spawn))
    await asyncio.sleep(0.05)
    gate.set()
    (s1, created1), (s2, created2) = await asyncio.gather(first, second)
    assert len(spawned) == 1
    assert s1 is s2 and created1 is True and created2 is False
    await reg.close_all()
