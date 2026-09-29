import json

import pytest

from robo_cli import web_server


class FakeBridge:
    def __init__(self):
        self.alive = True

    def read(self, timeout):
        return b""        # idle forever

    def write(self, data):
        pass

    def resize(self, cols, rows):
        pass

    def close(self):
        self.alive = False


@pytest.fixture
def pty_keepalive_harness(monkeypatch):
    spawned = []

    def fake_spawn(argv, cwd=None, env=None):
        b = FakeBridge()
        spawned.append(argv)
        return b

    monkeypatch.setattr(web_server.PtyBridge, "spawn", staticmethod(fake_spawn))
    monkeypatch.setattr(web_server, "_ws_auth_reason", lambda ws: (None, "test"))
    monkeypatch.setattr(web_server, "_ws_host_origin_reason", lambda ws: None)
    monkeypatch.setattr(web_server, "_ws_client_reason", lambda ws: None)

    async def fake_argv(**kw):
        resume = "child" if kw.get("resume") == "parent" else kw.get("resume")
        env = {"ROBO_TUI_RESUME": resume} if resume else {}
        return (["x", resume or "fresh"], "/tmp", env)

    monkeypatch.setattr(web_server, "_resolve_chat_argv_async", fake_argv)

    try:
        yield spawned
    finally:
        web_server.PTY_REGISTRY._sessions.clear()


@pytest.mark.asyncio
async def test_attach_token_reuses_same_session(pty_keepalive_harness):
    """Two connects with the same ?attach= token hit one spawned bridge."""
    from starlette.testclient import TestClient

    client = TestClient(web_server.app)
    with client.websocket_connect("/api/pty?attach=TOK1") as ws1:
        ws1.send_bytes(b"hi")
    with client.websocket_connect("/api/pty?attach=TOK1") as ws2:
        ws2.send_bytes(b"again")
    assert len(pty_keepalive_harness) == 1                # reattached, did not respawn


@pytest.mark.asyncio
async def test_attach_token_reuses_same_resume(pty_keepalive_harness):
    from starlette.testclient import TestClient

    client = TestClient(web_server.app)
    with client.websocket_connect("/api/pty?attach=TOK1&resume=same") as ws1:
        ws1.send_bytes(b"hi")
    with client.websocket_connect("/api/pty?attach=TOK1&resume=same") as ws2:
        ws2.send_bytes(b"again")
    assert pty_keepalive_harness == [["x", "same"]]




@pytest.mark.asyncio
async def test_attach_token_reuses_canonical_resume(pty_keepalive_harness):
    from starlette.testclient import TestClient

    client = TestClient(web_server.app)
    with client.websocket_connect("/api/pty?attach=TOK1&resume=parent") as ws1:
        ws1.send_bytes(b"hi")
    with client.websocket_connect("/api/pty?attach=TOK1&resume=child") as ws2:
        ws2.send_bytes(b"again")
    assert pty_keepalive_harness == [["x", "child"]]




@pytest.mark.asyncio
async def test_attach_token_reuses_default_chat_after_active_session_fallback(
    pty_keepalive_harness, tmp_path, monkeypatch
):
    from starlette.testclient import TestClient

    active_session_file = tmp_path / "active-session.json"
    monkeypatch.setattr(
        web_server,
        "_active_session_file_for_channel",
        lambda app, channel: active_session_file,
    )

    client = TestClient(web_server.app)
    with client.websocket_connect("/api/pty?attach=TOK1&channel=CHAT") as ws1:
        ws1.send_bytes(b"hi")

    active_session_file.write_text(json.dumps({"session_id": "existing"}))

    with client.websocket_connect("/api/pty?attach=TOK1&channel=CHAT") as ws2:
        ws2.send_bytes(b"again")

    assert pty_keepalive_harness == [["x", "fresh"]]


@pytest.mark.asyncio
async def test_chat_reopened_mid_setup_stays_live(monkeypatch):
    """Opening an old chat: the page connects with its id, then jumps to the
    chat's latest continuation and reconnects while the first connection is
    still being set up. Both map to one PTY. The first (abandoned) one used
    to finish last and supersede the live one — the chat on screen froze
    (no scrolling, no keys) on every other chat opened."""
    import asyncio
    import socket

    import uvicorn
    import websockets

    written = []
    spawned = []

    class Bridge(FakeBridge):
        def write(self, data):
            written.append(bytes(data))

    def fake_spawn(argv, cwd=None, env=None):
        spawned.append(argv)
        return Bridge()

    async def fake_argv(**kw):
        if kw.get("resume") == "parent":
            await asyncio.sleep(0.6)          # the first connection is slow
        return (["x", "child"], "/tmp", {"ROBO_TUI_RESUME": "child"})

    monkeypatch.setattr(web_server.PtyBridge, "spawn", staticmethod(fake_spawn))
    monkeypatch.setattr(web_server, "_ws_auth_reason", lambda ws: (None, "test"))
    monkeypatch.setattr(web_server, "_ws_host_origin_reason", lambda ws: None)
    monkeypatch.setattr(web_server, "_ws_client_reason", lambda ws: None)
    monkeypatch.setattr(web_server, "_resolve_chat_argv_async", fake_argv)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(web_server.app, log_level="warning", lifespan="off"))
    serve = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        base = f"ws://127.0.0.1:{port}/api/pty?attach=TOK"
        first = await websockets.connect(base + "&resume=parent")
        await asyncio.sleep(0.1)
        live = await websockets.connect(base + "&resume=child")
        # The page closes its abandoned connection; the server only notices later.
        await asyncio.sleep(1.0)              # the slow first connection finishes setup

        assert len(spawned) == 1              # one agent for one chat
        await live.send(b"\x1b[<64;10;5M")    # a wheel step reaches the TUI
        await asyncio.sleep(0.2)
        assert b"\x1b[<64;10;5M" in b"".join(written)
        assert live.close_code is None        # still the chat's live viewer
        with pytest.raises(websockets.ConnectionClosed) as closed:
            await asyncio.wait_for(first.recv(), 2)
        assert closed.value.rcvd.code == 4409
        await live.close()
    finally:
        server.should_exit = True
        await serve
        web_server.PTY_REGISTRY._sessions.clear()
        web_server.PTY_REGISTRY._key_locks.clear()
