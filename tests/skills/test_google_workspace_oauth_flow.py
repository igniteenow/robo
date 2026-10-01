"""Google Workspace sign-in against a local OAuth server.

Runs the skill's real setup.py steps (store the client secret, print the
authorization URL, exchange the code, check and refresh the token) through
google-auth-oauthlib, requests-oauthlib and oauthlib, so an upgrade of any of
them that changes the PKCE, scope or token handling fails here instead of on a
user's machine. Skipped when the Google libraries are not installed.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("google_auth_oauthlib.flow")
google_credentials = pytest.importorskip("google.oauth2.credentials")

SETUP_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills/productivity/google-workspace/scripts/setup.py"
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


@pytest.fixture()
def oauth_server():
    state: dict = {"codes": {}, "refreshes": 0}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}
            if form.get("grant_type") == "authorization_code":
                entry = state["codes"].pop(form.get("code"), None)
                verifier = form.get("code_verifier", "")
                if entry is None or _b64(hashlib.sha256(verifier.encode()).digest()) != entry["challenge"]:
                    return self._json(400, {"error": "invalid_grant"})
                return self._json(200, {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600,
                                        "scope": entry["granted"], "token_type": "Bearer"})
            if form.get("grant_type") == "refresh_token" and form.get("refresh_token") == "rt-1":
                state["refreshes"] += 1
                return self._json(200, {"access_token": "at-2", "expires_in": 3600, "token_type": "Bearer"})
            return self._json(400, {"error": "invalid_grant"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", state
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def setup_module(monkeypatch):
    spec = importlib.util.spec_from_file_location("google_workspace_setup_oauth_flow", SETUP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_ensure_deps", lambda: None)
    return module


def _quiet(fn, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn(*args)
    return result, out.getvalue()


def test_sign_in_with_partial_scopes_then_refresh(setup_module, oauth_server, tmp_path, monkeypatch):
    base, server_state = oauth_server
    # The local server is plain http on loopback; oauthlib only allows that
    # with this switch. google-auth refreshes against its own endpoint constant.
    monkeypatch.setenv("OAUTHLIB_INSECURE_TRANSPORT", "1")
    monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)
    monkeypatch.setattr(google_credentials, "_GOOGLE_OAUTH2_TOKEN_ENDPOINT", f"{base}/token")

    secret = tmp_path / "client_secret.json"
    secret.write_text(json.dumps({"installed": {
        "client_id": "cid.apps.googleusercontent.com", "client_secret": "secret",
        "auth_uri": f"{base}/auth", "token_uri": f"{base}/token", "redirect_uris": ["http://localhost"],
    }}), encoding="utf-8")
    _quiet(setup_module.store_client_secret, str(secret))

    _, printed = _quiet(setup_module.get_auth_url)
    auth_url = next(line for line in printed.splitlines() if line.startswith(f"{base}/auth"))
    query = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
    assert query["code_challenge_method"] == ["S256"]

    # The user unticks some permissions on the consent screen.
    granted = setup_module.SCOPES[:2]
    server_state["codes"]["code-1"] = {"challenge": query["code_challenge"][0], "granted": " ".join(granted)}
    callback = "http://localhost:1/?" + urllib.parse.urlencode(
        {"state": query["state"][0], "code": "code-1", "scope": " ".join(granted)})
    _quiet(setup_module.exchange_auth_code, callback)

    token = json.loads(setup_module.TOKEN_PATH.read_text(encoding="utf-8"))
    assert token["token"] == "at-1"
    assert token["refresh_token"] == "rt-1"
    assert token["scopes"] == granted

    ok, _ = _quiet(setup_module.check_auth)
    assert ok is True

    token["expiry"] = "2000-01-01T00:00:00Z"
    setup_module.TOKEN_PATH.write_text(json.dumps(token), encoding="utf-8")
    ok, printed = _quiet(setup_module.check_auth)
    assert ok is True, printed
    assert server_state["refreshes"] == 1
    assert json.loads(setup_module.TOKEN_PATH.read_text(encoding="utf-8"))["token"] == "at-2"
