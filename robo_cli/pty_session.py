"""Keep-alive PTY sessions for dashboard terminals.

A PTY process outlives the WebSocket that created it: a single drain task
always reads the PTY into a bounded RingBuffer and forwards to the attached
socket when present. Reconnecting with the same opaque token replays the
buffer and resumes live. See
docs/superpowers/specs/2026-06-20-pty-keepalive-reattach-design.md.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Optional

WS_CLOSE_PROCESS_EXITED = 4410
WS_CLOSE_SUPERSEDED = 4409


# Terminal modes the TUI switches on once, at start-up: full-screen
# (alternate screen), cursor visibility, bracketed paste, focus reporting.
# When the ring buffer drops its oldest bytes, those one-time switches can
# fall off the front of the replay — a reattaching browser would then draw a
# full-screen TUI into the normal buffer, show a stray cursor, or submit a
# multi-line paste line by line. We track their latest state and re-assert it
# ahead of a truncated replay.
_TRACKED_DEC_MODES = (1049, 25, 2004, 1004)
_DEC_MODE_DEFAULTS = {1049: False, 25: True, 2004: False, 1004: False}
_DEC_MODE_RE = re.compile(rb"\x1b\[\?([0-9;]+)([hl])")
_DEC_SCAN_TAIL = 32


class RingBuffer:
    """Keeps only the most recent ``capacity`` bytes appended to it."""

    def __init__(self, capacity: int) -> None:
        self._cap = capacity
        self._buf = bytearray()
        self._truncated = False
        self._modes = dict(_DEC_MODE_DEFAULTS)
        self._scan_tail = b""

    def _track_modes(self, data: bytes) -> None:
        # Carry a short tail so a sequence split across reads still matches.
        # Re-matching a sequence inside the tail is harmless: states are set,
        # not toggled, and matches are applied in stream order.
        window = self._scan_tail + data
        for match in _DEC_MODE_RE.finditer(window):
            enabled = match.group(2) == b"h"
            for part in match.group(1).split(b";"):
                try:
                    mode = int(part)
                except ValueError:
                    continue
                if mode in self._modes:
                    self._modes[mode] = enabled
        self._scan_tail = window[-_DEC_SCAN_TAIL:]

    def append(self, data: bytes) -> None:
        self._track_modes(data)
        self._buf.extend(data)
        overflow = len(self._buf) - self._cap
        if overflow > 0:
            del self._buf[:overflow]
            self._truncated = True

    def mode_preamble(self) -> bytes:
        """Escape sequences restoring the tracked modes' current state."""
        parts = []
        for mode in _TRACKED_DEC_MODES:
            if self._modes[mode] != _DEC_MODE_DEFAULTS[mode]:
                parts.append(b"\x1b[?%d%s" % (mode, b"h" if self._modes[mode] else b"l"))
        return b"".join(parts)

    def snapshot(self) -> bytes:
        if self._truncated:
            return self.mode_preamble() + bytes(self._buf)
        return bytes(self._buf)

    @property
    def truncated(self) -> bool:
        return self._truncated


class PtySession:
    def __init__(self, key: str, bridge, *, buffer_cap: int, read_timeout: float) -> None:
        self.key = key
        self.bridge = bridge
        self.buffer = RingBuffer(buffer_cap)
        self.alive = True
        self.attached = False
        self.last_detached_at: Optional[float] = None
        self._read_timeout = read_timeout
        self._ws = None
        # Arrival order of the attached connection (see attach()).
        self._ws_seq: Optional[int] = None
        self._drain_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._drain_task = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            chunk = await loop.run_in_executor(None, self.bridge.read, self._read_timeout)
            if chunk is None:                       # EOF — the agent process exited
                self.alive = False
                ws = self._ws
                if ws is not None:
                    try:
                        await ws.close(code=WS_CLOSE_PROCESS_EXITED)
                    except Exception:
                        pass
                return
            if not chunk:                            # idle tick
                await asyncio.sleep(0)
                continue
            self.buffer.append(chunk)
            ws = self._ws
            if ws is not None:
                try:
                    await ws.send_bytes(chunk)
                except Exception:
                    pass                             # detached mid-send; keep buffering

    async def attach(self, ws, seq: Optional[int] = None) -> bool:
        """Make ``ws`` the viewer; the previous one is superseded (4409).

        ``seq`` is the connection's arrival order. Two connections can race
        for one PTY (the page reconnects while its previous connection is
        still starting, e.g. when it jumps to a chat's latest continuation),
        and the older one may finish setting up last. It must never take the
        PTY from the newer, live viewer — that left the chat on screen
        frozen. An older connection is closed instead and False returned.
        """
        if seq is not None and self._ws_seq is not None and seq < self._ws_seq:
            try:
                await ws.close(code=WS_CLOSE_SUPERSEDED)
            except Exception:
                pass
            return False
        old = self._ws
        if old is not None and old is not ws:
            try:
                await old.close(code=WS_CLOSE_SUPERSEDED)
            except Exception:
                pass
        self._ws = ws
        if seq is not None:
            self._ws_seq = seq
        self.attached = True
        self.last_detached_at = None
        snap = self.buffer.snapshot()
        if snap:
            await ws.send_bytes(snap)
        return True

    def detach(self, ws) -> None:
        # Only the currently-attached socket may mark the session detached.
        # A superseded socket's handler also calls detach on its way out
        # (its ``finally`` runs after the new tab attached); flipping
        # ``attached`` then would make a session with a live viewer look
        # idle and reapable.
        if self._ws is not ws:
            return
        self._ws = None
        self.attached = False
        self.last_detached_at = time.monotonic()

    async def close(self) -> None:
        if self._drain_task is not None:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            # bridge.close() joins the child — blocking; keep it off the
            # event loop (#53227).
            await asyncio.to_thread(self.bridge.close)
        except Exception:
            pass


from typing import Callable, Dict, Tuple


class RegistryFull(Exception):
    pass


async def run_reaper(registry: "PtySessionRegistry", *, interval: float = 60.0) -> None:
    """Periodically reap idle/dead keep-alive sessions. Cancelled on shutdown."""
    while True:
        await asyncio.sleep(interval)
        try:
            await registry.reap_idle()
        except Exception:
            pass


class PtySessionRegistry:
    def __init__(self, *, ttl: float, max_sessions: int,
                 buffer_cap: int, read_timeout: float) -> None:
        self._ttl = ttl
        self._max = max_sessions
        self._buffer_cap = buffer_cap
        self._read_timeout = read_timeout
        self._sessions: Dict[str, PtySession] = {}
        # One lock per key: two connections for the same chat arriving
        # together must share ONE PTY, not each spawn an agent.
        self._key_locks: Dict[str, asyncio.Lock] = {}

    async def attach_or_spawn(self, key: str, *, spawn: Callable[[], object]
                              ) -> Tuple[PtySession, bool]:
        lock = self._key_locks.setdefault(key, asyncio.Lock())
        async with lock:
            return await self._attach_or_spawn_locked(key, spawn)

    async def _attach_or_spawn_locked(self, key: str, spawn: Callable[[], object]
                                      ) -> Tuple[PtySession, bool]:
        await self.reap_idle()
        existing = self._sessions.get(key)
        if existing is not None and existing.alive:
            return existing, False
        if existing is not None:                       # dead remnant
            await existing.close()
            self._sessions.pop(key, None)
        if len(self._sessions) >= self._max:
            self._reap_one_idle_or_raise()
        # PTY spawn does blocking fork/exec work — keep it off the event
        # loop (#53227).
        bridge = await asyncio.to_thread(spawn)
        session = PtySession(key, bridge, buffer_cap=self._buffer_cap,
                             read_timeout=self._read_timeout)
        await session.start()
        self._sessions[key] = session
        return session, True

    def detach(self, key: str, ws) -> None:
        s = self._sessions.get(key)
        if s is not None:
            s.detach(ws)

    async def reap_idle(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        doomed = [
            key for key, s in self._sessions.items()
            if (not s.alive)
            or (not s.attached and s.last_detached_at is not None
                and (now - s.last_detached_at) > self._ttl)
        ]
        for key in doomed:
            await self._sessions.pop(key).close()
            self._forget_key_lock(key)

    def _forget_key_lock(self, key: str) -> None:
        lock = self._key_locks.get(key)
        if lock is not None and not lock.locked():
            self._key_locks.pop(key, None)

    def _reap_one_idle_or_raise(self) -> None:
        idle = [s for s in self._sessions.values()
                if not s.attached and s.last_detached_at is not None]
        if not idle:
            raise RegistryFull()
        oldest = min(idle, key=lambda s: s.last_detached_at or 0.0)
        self._sessions.pop(oldest.key, None)
        self._forget_key_lock(oldest.key)
        asyncio.create_task(oldest.close())

    async def close_all(self) -> None:
        for key in list(self._sessions):
            await self._sessions.pop(key).close()
            self._forget_key_lock(key)
