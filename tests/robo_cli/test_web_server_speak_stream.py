"""/api/audio/speak-stream — desktop streaming TTS over WebSocket."""

from __future__ import annotations

import json
import time
from urllib.parse import urlencode

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from robo_cli import web_server


@pytest.fixture
def stream_client(monkeypatch, _isolate_robo_home):
    previous_auth_required = getattr(web_server.app.state, "auth_required", None)
    web_server.app.state.auth_required = False

    client = TestClient(web_server.app)
    try:
        yield client
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            close()
        if previous_auth_required is None:
            if hasattr(web_server.app.state, "auth_required"):
                delattr(web_server.app.state, "auth_required")
        else:
            web_server.app.state.auth_required = previous_auth_required


def _url(token: str | None = None, **extra) -> str:
    params = {"token": token or web_server._SESSION_TOKEN, **extra}
    return f"/api/audio/speak-stream?{urlencode(params)}"


class _FakeStreamer:
    sample_rate = 24000
    channels = 1

    def __init__(self, chunks):
        self.chunks = chunks
        self.requests: list[str] = []

    def stream(self, text):
        self.requests.append(text)
        yield from self.chunks


def _patch_provider(monkeypatch, streamer, cap=4000):
    monkeypatch.setattr("tools.tts_streaming.resolve_streaming_provider", lambda cfg: streamer)
    monkeypatch.setattr("tools.tts_tool._load_tts_config", lambda: {})
    monkeypatch.setattr("tools.tts_tool._get_provider", lambda cfg: "fake")
    monkeypatch.setattr("tools.tts_tool._resolve_max_text_length", lambda provider, cfg: cap)






def test_streams_pcm_frames_then_end(stream_client, monkeypatch):
    streamer = _FakeStreamer([b"\x01\x02\x03\x04", b"\x05\x06"])
    _patch_provider(monkeypatch, streamer)

    with stream_client.websocket_connect(_url()) as conn:
        start = conn.receive_json()
        assert start == {"type": "start", "sample_rate": 24000, "channels": 1}

        conn.send_text(json.dumps({"text": "Hello there.", "done": True}))
        assert conn.receive_bytes() == b"\x01\x02\x03\x04"
        assert conn.receive_bytes() == b"\x05\x06"
        assert conn.receive_json() == {"type": "end"}

    assert streamer.requests == ["Hello there."]








def test_long_text_is_split_across_provider_requests(stream_client, monkeypatch):
    streamer = _FakeStreamer([b"\x00\x00"])
    _patch_provider(monkeypatch, streamer, cap=24)

    with stream_client.websocket_connect(_url()) as conn:
        assert conn.receive_json()["type"] == "start"
        conn.send_text(
            json.dumps(
                {"text": "First sentence here. Second sentence here. Third one.", "done": True}
            )
        )
        # One PCM frame per split piece, then end.
        frames = 0
        while True:
            message = conn.receive()
            if message.get("bytes") is not None:
                frames += 1
            else:
                assert json.loads(message["text"]) == {"type": "end"}
                break

    assert len(streamer.requests) > 1
    assert frames == len(streamer.requests)
    # Nothing lost in the split: every sentence reached the provider.
    joined = " ".join(streamer.requests)
    for fragment in ("First sentence here.", "Second sentence here.", "Third one."):
        assert fragment in joined


def test_split_text_respects_cap_and_preserves_content():
    text = "Alpha beta. Gamma delta epsilon. Zeta eta theta iota kappa."
    pieces = web_server._split_text_for_speak_stream(text, 30)
    assert pieces
    assert all(len(piece) <= 30 for piece in pieces)
    joined = " ".join(pieces)
    for word in text.replace(".", "").split():
        assert word in joined


# ── Providers with no chunked API: one audio file per sentence ─────────────
#
# Edge (the free default), Piper, KittenTTS, … have no PCM stream. The desktop
# used to get `fallback` and wait for the WHOLE reply plus one big synthesis
# before a word was heard. With `?encoded=1` the server speaks sentence by
# sentence through the ordinary synthesis path and ships each sentence as a
# complete file the client decodes — the first line plays while the model is
# still writing the second. Clients that did not opt in still get `fallback`.


def _patch_no_streamer(monkeypatch, tmp_path, *, fail_on: str | None = None):
    """No chunked provider; text_to_speech_tool writes a tiny fake MP3 per call."""
    spoken: list[str] = []

    def fake_tts(text, *args, **kwargs):
        spoken.append(text)
        if fail_on and fail_on in text:
            return json.dumps({"success": False, "error": "boom"})
        path = tmp_path / f"tts_{len(spoken)}.mp3"
        path.write_bytes(b"ID3" + text.encode("utf-8"))
        return json.dumps({"success": True, "file_path": str(path), "provider": "edge"})

    monkeypatch.setattr("tools.tts_streaming.resolve_streaming_provider", lambda cfg: None)
    monkeypatch.setattr("tools.tts_tool._load_tts_config", lambda: {})
    monkeypatch.setattr("tools.tts_tool._get_provider", lambda cfg: "edge")
    monkeypatch.setattr("tools.tts_tool._resolve_max_text_length", lambda provider, cfg: 4000)
    monkeypatch.setattr("tools.tts_tool.text_to_speech_tool", fake_tts)
    return spoken


def test_encoded_client_gets_one_file_per_sentence_then_end(stream_client, monkeypatch, tmp_path):
    spoken = _patch_no_streamer(monkeypatch, tmp_path)

    with stream_client.websocket_connect(_url(encoded="1")) as conn:
        assert conn.receive_json() == {"type": "start", "format": "encoded"}

        conn.send_text(json.dumps({"text": "The first sentence is here. And the second one is here too.", "done": True}))
        first = conn.receive_bytes()
        second = conn.receive_bytes()
        assert conn.receive_json() == {"type": "end"}

    # Each frame is a whole file for one sentence, in order, and the temp
    # files are gone once shipped.
    assert first == b"ID3The first sentence is here."
    assert second == b"ID3And the second one is here too."
    assert spoken == ["The first sentence is here.", "And the second one is here too."]
    assert not list(tmp_path.glob("tts_*.mp3"))


def test_encoded_client_hears_the_opening_clause_first(stream_client, monkeypatch, tmp_path):
    # A live reply starts speaking at its first clause, not its first full
    # stop: the rest of the sentence is synthesized while the clause plays.
    spoken = _patch_no_streamer(monkeypatch, tmp_path)

    with stream_client.websocket_connect(_url(encoded="1")) as conn:
        assert conn.receive_json() == {"type": "start", "format": "encoded"}

        conn.send_text(
            json.dumps({"text": "The weather in Lahore is warm and sunny, with clear skies and a light breeze.", "done": True})
        )
        first = conn.receive_bytes()
        second = conn.receive_bytes()
        assert conn.receive_json() == {"type": "end"}

    assert first == b"ID3The weather in Lahore is warm and sunny,"
    assert second == b"ID3with clear skies and a light breeze."
    assert spoken == ["The weather in Lahore is warm and sunny,", "with clear skies and a light breeze."]


def test_encoded_path_skips_a_failed_sentence_and_keeps_going(stream_client, monkeypatch, tmp_path):
    spoken = _patch_no_streamer(monkeypatch, tmp_path, fail_on="second")

    with stream_client.websocket_connect(_url(encoded="1")) as conn:
        assert conn.receive_json()["format"] == "encoded"
        conn.send_text(
            json.dumps({"text": "The first sentence is fine. The second sentence fails. The third is fine.", "done": True})
        )
        frames = []
        while True:
            message = conn.receive()
            if message.get("bytes") is not None:
                frames.append(message["bytes"])
            else:
                assert json.loads(message["text"]) == {"type": "end"}
                break

    assert len(spoken) == 3
    assert frames == [b"ID3The first sentence is fine.", b"ID3The third is fine."]


def test_client_without_the_opt_in_still_gets_fallback(stream_client, monkeypatch, tmp_path):
    spoken = _patch_no_streamer(monkeypatch, tmp_path)

    with stream_client.websocket_connect(_url()) as conn:
        assert conn.receive_json() == {"type": "fallback"}

    assert spoken == []


def test_chunked_provider_still_streams_pcm_for_an_encoded_client(stream_client, monkeypatch):
    """The opt-in only changes what happens when there is no PCM stream."""
    streamer = _FakeStreamer([b"\x01\x02"])
    _patch_provider(monkeypatch, streamer)

    with stream_client.websocket_connect(_url(encoded="1")) as conn:
        assert conn.receive_json() == {"type": "start", "sample_rate": 24000, "channels": 1}
        conn.send_text(json.dumps({"text": "Hello there, how are you today.", "done": True}))
        assert conn.receive_bytes() == b"\x01\x02"
        assert conn.receive_json() == {"type": "end"}


def test_speak_sentence_encoded_reads_and_removes_the_file(monkeypatch, tmp_path):
    path = tmp_path / "one.mp3"
    path.write_bytes(b"ID3abc")
    monkeypatch.setattr(
        "tools.tts_tool.text_to_speech_tool",
        lambda text, *a, **k: json.dumps({"success": True, "file_path": str(path)}),
    )
    assert web_server._speak_sentence_encoded("hello") == b"ID3abc"
    assert not path.exists()

    monkeypatch.setattr(
        "tools.tts_tool.text_to_speech_tool", lambda text, *a, **k: json.dumps({"success": False, "error": "no"})
    )
    assert web_server._speak_sentence_encoded("hello") is None
