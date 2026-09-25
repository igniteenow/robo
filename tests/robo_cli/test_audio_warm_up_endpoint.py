"""``POST /api/audio/warm-up`` — the desktop preloads local STT before the first
spoken turn of a voice chat (the TUI's ``/voice on`` does the same). The
endpoint returns at once; the model load runs on a worker thread, scoped to
the requested profile, and is never started inside the test process.
"""

import pytest


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


def test_warm_up_is_a_no_op_inside_the_test_process(client):
    resp = client.post("/api/audio/warm-up")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "scheduled": False}


def test_endpoint_reports_what_the_scheduler_did(client, monkeypatch):
    from robo_cli import web_server

    seen = []
    monkeypatch.setattr(web_server, "_start_desktop_stt_warm_up", lambda profile: seen.append(profile) or True)

    resp = client.post("/api/audio/warm-up?profile=worker")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "scheduled": True}
    assert seen == ["worker"]


def test_scheduler_runs_the_load_on_a_daemon_thread(monkeypatch):
    """Outside the test process the load goes to a named daemon thread; the
    request never waits on it."""
    from robo_cli import web_server

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    started = []

    class _Thread:
        def __init__(self, target=None, daemon=None, name=None):
            started.append((target, daemon, name))

        def start(self):
            pass

    monkeypatch.setattr(web_server.threading, "Thread", _Thread)
    assert web_server._start_desktop_stt_warm_up(None) is True
    assert len(started) == 1
    target, daemon, name = started[0]
    assert daemon is True
    assert name == "desktop-stt-warmup"
    assert callable(target)


def test_scheduler_never_loads_inside_the_test_process():
    from robo_cli import web_server

    assert web_server._start_desktop_stt_warm_up(None) is False
