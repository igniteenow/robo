"""Push-to-talk works in every web-dashboard chat, not only the first.

All browser chats share the dashboard's one in-process gateway and the host
microphone. Each chat's TUI arms the wake-word listener when it starts, so the
first chat owned the mic and voice.record in any other chat answered busy
("voice: still transcribing") while that chat stayed open. The dashboard turns
on a mic handoff; a standalone TUI and the desktop backend don't.
"""

from __future__ import annotations

import sys
import types

import pytest

from tui_gateway import server


@pytest.fixture
def mic(monkeypatch):
    from tools import wake_word

    state = {"owner": None, "paused": False, "pause_calls": [], "resume_calls": []}
    voice_callbacks: dict = {}

    def start_listening(callback, *, owner, config, external_audio=False):
        if state["owner"] is not None and state["owner"] is not owner:
            raise wake_word.WakeWordInUse
        state.update(owner=owner, paused=False)

    def pause_listening(*, owner):
        state["pause_calls"].append(owner)
        if state["owner"] is not owner:
            return False
        state["paused"] = True
        return True

    def resume_listening(*, owner):
        state["resume_calls"].append(owner)
        if state["owner"] is not owner:
            return False
        state["paused"] = False
        return True

    def stop_listening(*, owner):
        if state["owner"] is not owner:
            return False
        state.update(owner=None, paused=False)
        return True

    def start_continuous(**callbacks):
        voice_callbacks.update(callbacks)
        return True

    monkeypatch.setattr(wake_word, "load_wake_word_config", lambda: {
        "enabled": True, "phrase": "hey robo", "surface": "auto", "start_new_session": True,
    })
    monkeypatch.setattr(wake_word, "check_wake_word_requirements", lambda _cfg: {
        "available": True, "phrase": "hey robo", "provider": "test", "hint": "",
    })
    monkeypatch.setattr(wake_word, "start_listening", start_listening)
    monkeypatch.setattr(wake_word, "pause_listening", pause_listening)
    monkeypatch.setattr(wake_word, "resume_listening", resume_listening)
    monkeypatch.setattr(wake_word, "stop_listening", stop_listening)
    monkeypatch.setattr(wake_word, "owns_listener", lambda owner: state["owner"] is owner)
    monkeypatch.setattr(
        wake_word, "is_listening", lambda: state["owner"] is not None and not state["paused"]
    )
    monkeypatch.setitem(
        sys.modules,
        "robo_cli.voice",
        types.SimpleNamespace(
            start_continuous=start_continuous,
            stop_continuous=lambda **_kwargs: None,
        ),
    )
    monkeypatch.setenv("ROBO_VOICE", "1")
    monkeypatch.setattr(server, "_wake_owner_transport", None)
    monkeypatch.setattr(server, "_wake_owner_surface", "")
    monkeypatch.setattr(server, "_voice_wake_owner", None)
    state["callbacks"] = voice_callbacks
    return state


def _two_chats():
    return types.SimpleNamespace(_closed=False), types.SimpleNamespace(_closed=False)


def _arm_wake(first):
    r = server.dispatch(
        {"id": "w", "method": "wake.start", "params": {"surface": "tui", "session_id": "a"}},
        transport=first,
    )
    assert r["result"]["started"] is True


def _record(transport, action="start", sid="b"):
    return server.dispatch(
        {"id": f"v-{action}", "method": "voice.record",
         "params": {"action": action, "session_id": sid}},
        transport=transport,
    )


def test_without_the_dashboard_switch_behaviour_is_unchanged(mic, monkeypatch):
    monkeypatch.setattr(server, "_shared_gateway_mic_handoff", False)
    first, second = _two_chats()
    _arm_wake(first)
    assert _record(second)["result"] == {"status": "busy", "reason": "wake_owned"}
    assert mic["pause_calls"] == []


def test_dashboard_chat_borrows_the_mic_and_gives_it_back(mic, monkeypatch):
    monkeypatch.setattr(server, "_shared_gateway_mic_handoff", True)
    first, second = _two_chats()
    _arm_wake(first)

    r = _record(second)

    assert r["result"] == {"status": "recording"}
    assert mic["pause_calls"] == [first]
    assert mic["paused"] is True
    # The wake listener still belongs to the first chat...
    assert server._wake_owner_transport is first
    # ...and is handed back when the capture finishes.
    mic["callbacks"]["on_status"]("idle")
    assert mic["resume_calls"][-1] is first
    assert mic["paused"] is False


def test_dashboard_clears_a_lease_left_by_a_closed_chat(mic, monkeypatch):
    monkeypatch.setattr(server, "_shared_gateway_mic_handoff", True)
    first, second = _two_chats()
    _arm_wake(first)
    first._closed = True

    r = _record(second)

    assert r["result"] == {"status": "recording"}
    assert server._wake_owner_transport is None
    assert mic["owner"] is None


def test_owner_chat_still_records_as_before(mic, monkeypatch):
    monkeypatch.setattr(server, "_shared_gateway_mic_handoff", True)
    first, _second = _two_chats()
    _arm_wake(first)
    assert _record(first, sid="a")["result"] == {"status": "recording"}
    assert mic["pause_calls"] == [first]


def test_dashboard_turns_the_handoff_on_when_a_chat_connects(monkeypatch):
    from starlette.testclient import TestClient

    from robo_cli import web_server

    monkeypatch.setattr(server, "_shared_gateway_mic_handoff", False)
    monkeypatch.setattr(web_server.app.state, "dashboard_voice_handoff", True, raising=False)

    async def _noop_handle_ws(ws):
        await ws.accept()
        await ws.close()

    import tui_gateway.ws as gw_ws

    monkeypatch.setattr(gw_ws, "handle_ws", _noop_handle_ws)
    client = TestClient(web_server.app)
    with client.websocket_connect(f"/api/ws?token={web_server._SESSION_TOKEN}"):
        pass
    assert server._shared_gateway_mic_handoff is True


def test_backend_without_web_ui_leaves_it_off(monkeypatch):
    from starlette.testclient import TestClient

    from robo_cli import web_server

    monkeypatch.setattr(server, "_shared_gateway_mic_handoff", False)
    monkeypatch.setattr(web_server.app.state, "dashboard_voice_handoff", False, raising=False)

    async def _noop_handle_ws(ws):
        await ws.accept()
        await ws.close()

    import tui_gateway.ws as gw_ws

    monkeypatch.setattr(gw_ws, "handle_ws", _noop_handle_ws)
    client = TestClient(web_server.app)
    with client.websocket_connect(f"/api/ws?token={web_server._SESSION_TOKEN}"):
        pass
    assert server._shared_gateway_mic_handoff is False
