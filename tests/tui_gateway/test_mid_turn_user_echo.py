"""A message sent while a turn is running is echoed the moment it is accepted.

The gateway used to echo ``message.user`` only when ``prompt.submit`` redirected
the live turn. A steered or queued submit, and the ``session.steer`` /
``session.redirect`` RPCs the clients use directly, accepted the text silently:
the model read it later, the user saw nothing land. Every accepted mid-turn
path now fires one ``message.user`` frame tagged ``mid_turn`` + ``status`` so
each client can paint the bubble at once (and dedupe its own optimistic echo).
"""

import threading
import time
import types

from tui_gateway import server


def _session(agent=None, **extra):
    return {
        "agent": agent if agent is not None else types.SimpleNamespace(),
        "session_key": "session-key",
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "transport": None,
        "attached_images": [],
        **extra,
    }


def _capture_emits(monkeypatch):
    emitted: list[tuple[str, str, dict | None]] = []
    monkeypatch.setattr(
        server,
        "_emit",
        lambda event, sid, payload=None: emitted.append((event, sid, payload)),
    )
    return emitted


def _user_echoes(emitted):
    return [(sid, payload) for event, sid, payload in emitted if event == "message.user"]


# ── helper ─────────────────────────────────────────────────────────────────


def test_mid_turn_echo_frame_shape(monkeypatch):
    emitted = _capture_emits(monkeypatch)
    before = time.time()

    server._emit_mid_turn_user_echo("sid", "  also check auth.log  ", "steered")

    assert len(emitted) == 1
    event, sid, payload = emitted[0]
    assert event == "message.user"
    assert sid == "sid"
    assert payload["text"] == "also check auth.log"
    assert payload["mid_turn"] is True
    assert payload["status"] == "steered"
    assert payload["ts"] >= before


def test_mid_turn_echo_skips_blank_text(monkeypatch):
    emitted = _capture_emits(monkeypatch)

    server._emit_mid_turn_user_echo("sid", "   ", "queued")
    server._emit_mid_turn_user_echo("sid", None, "queued")

    assert emitted == []


def test_mid_turn_echo_never_raises(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("transport gone")

    monkeypatch.setattr(server, "_emit", boom)

    # The agent already accepted the message; a failed echo must not turn the
    # RPC into an error.
    assert server._emit_mid_turn_user_echo("sid", "hello", "redirected") is None


# ── prompt.submit busy policy (_handle_busy_submit) ────────────────────────


def test_busy_steer_mode_echoes_accepted_message(monkeypatch):
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "steer")
    emitted = _capture_emits(monkeypatch)
    agent = types.SimpleNamespace(steer=lambda text: True, interrupt=lambda *a, **k: None)
    session = _session(agent=agent, running=True)
    session["inflight_turn"] = {"user": "original request", "assistant": "partial"}

    resp = server._handle_busy_submit("r1", "sid", session, "nudge", "ws-1")

    assert resp["result"]["status"] == "steered"
    echoes = _user_echoes(emitted)
    assert len(echoes) == 1
    assert echoes[0][0] == "sid"
    assert echoes[0][1]["text"] == "nudge"
    assert echoes[0][1]["mid_turn"] is True
    assert echoes[0][1]["status"] == "steered"
    # Same bookkeeping as session.steer: resume can rebuild the bubble.
    assert session["inflight_turn"]["user"] == "original request"
    assert session["inflight_turn"]["corrections"] == ["nudge"]
    assert session.get("queued_prompt") is None


def test_busy_interrupt_mode_echoes_redirected_message(monkeypatch):
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "interrupt")
    emitted = _capture_emits(monkeypatch)
    agent = types.SimpleNamespace(
        _supports_active_turn_redirect=True,
        redirect=lambda text: True,
        interrupt=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no hard interrupt")),
    )
    session = _session(agent=agent, running=True)

    resp = server._handle_busy_submit("r1", "sid", session, "use Postgres", "ws-1")

    assert resp["result"]["status"] == "redirected"
    echoes = _user_echoes(emitted)
    assert len(echoes) == 1
    assert echoes[0][0] == "sid"
    assert echoes[0][1]["text"] == "use Postgres"
    assert echoes[0][1]["mid_turn"] is True
    assert echoes[0][1]["status"] == "redirected"


def test_busy_interrupt_fallback_echoes_queued_message(monkeypatch):
    """Older agent (no redirect): the text is queued for the next turn — still echoed."""
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "interrupt")
    emitted = _capture_emits(monkeypatch)
    interrupted = threading.Event()
    agent = types.SimpleNamespace(interrupt=lambda *a, **k: interrupted.set())
    session = _session(agent=agent, running=True)

    resp = server._handle_busy_submit("r1", "sid", session, "continue", "ws-1")

    assert resp["result"]["status"] == "queued"
    assert session["queued_prompt"]["text"] == "continue"
    echoes = _user_echoes(emitted)
    assert len(echoes) == 1
    assert echoes[0][1]["text"] == "continue"
    assert echoes[0][1]["status"] == "queued"
    assert interrupted.wait(2.0)


def test_busy_queue_mode_echoes_queued_message(monkeypatch):
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "queue")
    emitted = _capture_emits(monkeypatch)
    agent = types.SimpleNamespace(interrupt=lambda *a, **k: None)
    session = _session(agent=agent, running=True)

    resp = server._handle_busy_submit("r1", "sid", session, "later please", "ws-1")

    assert resp["result"]["status"] == "queued"
    assert [p["status"] for _, p in _user_echoes(emitted)] == ["queued"]
    assert _user_echoes(emitted)[0][1]["text"] == "later please"


def test_busy_multimodal_queue_has_no_text_echo(monkeypatch):
    """Image payloads queue as before; there is no plain text to echo."""
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "interrupt")
    emitted = _capture_emits(monkeypatch)
    rich = [
        {"type": "text", "text": "caption"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]
    agent = types.SimpleNamespace(
        _supports_active_turn_redirect=True,
        redirect=lambda text: True,
        interrupt=lambda *a, **k: None,
    )
    session = _session(agent=agent, running=True)

    resp = server._handle_busy_submit("r1", "sid", session, rich, "ws-1")

    assert resp["result"]["status"] == "queued"
    assert _user_echoes(emitted) == []


def test_busy_helper_does_not_echo_when_turn_already_finished(monkeypatch):
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "interrupt")
    emitted = _capture_emits(monkeypatch)
    session = _session(running=False)

    assert server._handle_busy_submit("r1", "sid", session, "run now", "ws-1") is None
    assert _user_echoes(emitted) == []


# ── session.steer / session.redirect RPCs ──────────────────────────────────


def _rpc(method: str, text: str) -> dict:
    return server.handle_request(
        {"id": "1", "method": method, "params": {"session_id": "sid", "text": text}}
    )


def test_session_steer_rpc_echoes_accepted_message(monkeypatch):
    emitted = _capture_emits(monkeypatch)
    agent = types.SimpleNamespace(steer=lambda text: True)
    session = _session(agent=agent, running=True)
    session["inflight_turn"] = {"user": "original", "assistant": ""}
    server._sessions["sid"] = session
    try:
        resp = _rpc("session.steer", "also check auth.log")
    finally:
        server._sessions.pop("sid", None)

    assert resp["result"]["status"] == "queued"
    echoes = _user_echoes(emitted)
    assert len(echoes) == 1
    assert echoes[0][0] == "sid"
    assert echoes[0][1]["text"] == "also check auth.log"
    assert echoes[0][1]["status"] == "steered"
    assert echoes[0][1]["mid_turn"] is True
    assert session["inflight_turn"]["corrections"] == ["also check auth.log"]


def test_session_steer_rpc_rejected_has_no_echo(monkeypatch):
    emitted = _capture_emits(monkeypatch)
    server._sessions["sid"] = _session(agent=types.SimpleNamespace(steer=lambda text: False))
    try:
        resp = _rpc("session.steer", "too late")
    finally:
        server._sessions.pop("sid", None)

    assert resp["result"]["status"] == "rejected"
    assert _user_echoes(emitted) == []


def test_session_redirect_rpc_echoes_accepted_message(monkeypatch):
    emitted = _capture_emits(monkeypatch)
    agent = types.SimpleNamespace(
        _supports_active_turn_redirect=True, redirect=lambda text: True
    )
    server._sessions["sid"] = _session(agent=agent, running=True)
    try:
        resp = _rpc("session.redirect", "use Postgres")
    finally:
        server._sessions.pop("sid", None)

    assert resp["result"] == {"status": "redirected", "text": "use Postgres"}
    echoes = _user_echoes(emitted)
    assert len(echoes) == 1
    assert echoes[0][1]["text"] == "use Postgres"
    assert echoes[0][1]["status"] == "redirected"


def test_session_redirect_rpc_rejected_has_no_echo(monkeypatch):
    emitted = _capture_emits(monkeypatch)
    agent = types.SimpleNamespace(
        _supports_active_turn_redirect=True, redirect=lambda text: False
    )
    server._sessions["sid"] = _session(agent=agent, running=True)
    try:
        resp = _rpc("session.redirect", "too late")
    finally:
        server._sessions.pop("sid", None)

    assert resp["result"]["status"] == "rejected"
    assert _user_echoes(emitted) == []


def test_session_redirect_rpc_build_window_queues_and_echoes(monkeypatch):
    """running=True with no agent yet: queued server-side, and echoed as such."""
    emitted = _capture_emits(monkeypatch)
    session = _session(running=True)
    session["agent"] = None
    server._sessions["sid"] = session
    try:
        resp = _rpc("session.redirect", "build-window nudge")
    finally:
        server._sessions.pop("sid", None)

    assert resp["result"] == {"status": "queued", "text": "build-window nudge"}
    assert session["queued_prompt"]["text"] == "build-window nudge"
    echoes = _user_echoes(emitted)
    assert len(echoes) == 1
    assert echoes[0][1]["text"] == "build-window nudge"
    assert echoes[0][1]["status"] == "queued"
