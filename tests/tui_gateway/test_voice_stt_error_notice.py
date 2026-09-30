"""A failed transcription shows the user why nothing was sent.

``voice.record`` hands ``on_error`` to the voice loop; when speech-to-text
fails, the gateway emits a ``notification.show`` notice (the TUI shows it in
its status bar, the desktop app as a toast) instead of dropping the
recording silently.
"""

import sys
import types

from tui_gateway import server


def _capture_emits(monkeypatch):
    emitted: list[tuple] = []
    monkeypatch.setattr(
        server, "_emit", lambda event, sid, payload=None: emitted.append((event, sid, payload))
    )
    return emitted


def test_voice_record_start_wires_an_error_notice(monkeypatch):
    captured: dict = {}

    def fake_start_continuous(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setitem(
        sys.modules,
        "robo_cli.voice",
        types.SimpleNamespace(
            start_continuous=fake_start_continuous, stop_continuous=lambda **_k: None
        ),
    )
    monkeypatch.setenv("ROBO_VOICE", "1")
    monkeypatch.setattr(server, "_load_cfg", lambda: {"voice": {}})

    resp = server.dispatch(
        {
            "id": "voice-record",
            "method": "voice.record",
            "params": {"action": "start", "session_id": "sid-voice"},
        }
    )
    assert resp["result"]["status"] == "recording"
    assert callable(captured.get("on_error"))

    emitted = _capture_emits(monkeypatch)
    captured["on_error"](
        "Local transcription failed: open() got an unexpected keyword argument 'metadata_errors'"
    )

    notices = [e for e in emitted if e[0] == "notification.show"]
    assert len(notices) == 1
    _event, sid, payload = notices[0]
    assert sid == "sid-voice"
    assert payload["level"] == "error"
    assert payload["kind"] == "ttl" and payload["ttl_ms"] > 0
    assert payload["key"] == payload["id"] == "voice.stt_error"
    assert payload["text"].startswith("✕ Voice: couldn't turn your recording into text")
    assert "metadata_errors" in payload["text"]


def test_long_errors_are_clipped_to_one_line(monkeypatch):
    emitted = _capture_emits(monkeypatch)

    server._voice_stt_error_notice("line one\nline two " + "x" * 400)

    (_event, _sid, payload), = emitted
    assert "\n" not in payload["text"]
    assert payload["text"].endswith("...")
    assert len(payload["text"]) < 260


def test_empty_error_still_explains(monkeypatch):
    emitted = _capture_emits(monkeypatch)

    server._voice_stt_error_notice(None)

    (_event, _sid, payload), = emitted
    assert payload["text"].endswith("speech-to-text failed")
