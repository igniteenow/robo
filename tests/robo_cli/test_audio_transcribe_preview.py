"""``POST /api/audio/transcribe`` with ``preview: true`` — the desktop shows the
words of a dictation while it is still being recorded by transcribing the
recording so far every couple of seconds. That only runs on a local provider:
on a cloud provider every preview would bill the same audio again.
"""

import base64

import pytest

AUDIO = "data:audio/webm;base64," + base64.b64encode(b"\x1aE\xdf\xa3 fake webm").decode()


@pytest.fixture
def client(monkeypatch, tmp_path, _isolate_robo_home):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    import robo_state
    from robo_constants import get_robo_home
    from robo_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    home = get_robo_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(robo_state, "DEFAULT_DB_PATH", home / "state.db")
    c = TestClient(app)
    c.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return c


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_transcribe(path, model=None):
        seen.append(path)
        return {"success": True, "transcript": "hello there", "provider": "fake"}

    monkeypatch.setattr("tools.voice_mode.transcribe_recording", fake_transcribe)
    return seen


def _provider(monkeypatch, name):
    monkeypatch.setattr("tools.transcription_tools._get_provider", lambda cfg: name)


@pytest.mark.parametrize("provider", ["local", "local_command"])
def test_preview_runs_on_a_local_provider(client, calls, monkeypatch, provider):
    _provider(monkeypatch, provider)

    resp = client.post("/api/audio/transcribe", json={"data_url": AUDIO, "preview": True})

    assert resp.status_code == 200
    assert resp.json()["transcript"] == "hello there"
    assert "preview_unsupported" not in resp.json()
    assert len(calls) == 1


@pytest.mark.parametrize("provider", ["openai", "groq", "mistral", "elevenlabs", "none"])
def test_preview_never_reaches_a_cloud_provider(client, calls, monkeypatch, provider):
    _provider(monkeypatch, provider)

    resp = client.post("/api/audio/transcribe", json={"data_url": AUDIO, "preview": True})

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "transcript": "", "preview_unsupported": True}
    assert calls == []


def test_the_final_transcription_is_unchanged_on_any_provider(client, calls, monkeypatch):
    _provider(monkeypatch, "openai")

    resp = client.post("/api/audio/transcribe", json={"data_url": AUDIO})

    assert resp.status_code == 200
    assert resp.json()["transcript"] == "hello there"
    assert len(calls) == 1


def test_a_provider_lookup_error_means_no_preview(client, calls, monkeypatch):
    def boom(cfg):
        raise RuntimeError("config unreadable")

    monkeypatch.setattr("tools.transcription_tools._get_provider", boom)

    resp = client.post("/api/audio/transcribe", json={"data_url": AUDIO, "preview": True})

    assert resp.json().get("preview_unsupported") is True
    assert calls == []
