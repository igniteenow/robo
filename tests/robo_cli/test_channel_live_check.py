"""Channels page Test button checks the bot token with the platform itself.

No real network: httpx.AsyncClient is swapped for one on a MockTransport.
"""

from __future__ import annotations

import httpx
import pytest

from robo_cli import web_server

TOKEN = "123456789:AAH-valid_looking-token_value_abcdefghijk"
_REAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture
def client(_isolate_robo_home):
    from starlette.testclient import TestClient

    c = TestClient(web_server.app)
    c.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    r = c.put(
        "/api/messaging/platforms/telegram",
        json={"env": {"TELEGRAM_BOT_TOKEN": TOKEN}, "enabled": True},
    )
    assert r.status_code == 200, r.text
    return c


def _mock_httpx(monkeypatch, handler):
    class _Client(_REAL_ASYNC_CLIENT):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def test_rejected_token_is_reported(client, monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    _mock_httpx(monkeypatch, handler)
    body = client.post("/api/messaging/platforms/telegram/test").json()
    assert body["ok"] is False
    assert "rejected" in body["message"]
    assert seen["url"].endswith("/getMe")


def test_working_token_with_gateway_down_says_what_to_do(client, monkeypatch):
    _mock_httpx(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"ok": True, "result": {"username": "robo_test_bot"}}
        ),
    )
    body = client.post("/api/messaging/platforms/telegram/test").json()
    assert body["ok"] is False  # not connected yet
    assert "@robo_test_bot" in body["message"]
    assert "gateway" in body["message"].lower()


def test_unreachable_platform_falls_back_to_setup_status(client, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    _mock_httpx(monkeypatch, handler)
    body = client.post("/api/messaging/platforms/telegram/test").json()
    assert body["ok"] is False
    assert "Gateway is not running" in body["message"]


@pytest.mark.asyncio
async def test_slack_auth_test_shapes(monkeypatch):
    _mock_httpx(
        monkeypatch,
        lambda request: httpx.Response(200, json={"ok": False, "error": "invalid_auth"}),
    )
    bad = await web_server._live_channel_credential_check("slack", {"SLACK_BOT_TOKEN": "xoxb-1"})
    assert bad == {"ok": False, "message": "Slack rejected the bot token (invalid_auth)."}
    _mock_httpx(
        monkeypatch,
        lambda request: httpx.Response(200, json={"ok": True, "user": "robo", "team": "acme"}),
    )
    good = await web_server._live_channel_credential_check("slack", {"SLACK_BOT_TOKEN": "xoxb-1"})
    assert good["ok"] is True and "acme" in good["message"]
    assert await web_server._live_channel_credential_check("matrix", {}) is None
