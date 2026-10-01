"""Self-hosted OIDC login against a real (local) identity provider.

The provider tests in ``test_self_hosted_provider.py`` replace the JWKS client
with a fake. These run the real chain instead — httpx discovery and token POST,
PyJWT's ``PyJWKClient`` fetching the key set over HTTP, RS256 verification —
against a throwaway IdP on 127.0.0.1, so a PyJWT upgrade that changes how keys
are fetched or tokens are parsed shows up here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from plugins.dashboard_auth.self_hosted import SelfHostedOIDCProvider
from robo_cli.dashboard_auth import InvalidCodeError, ProviderError

_CLIENT_ID = "robo-dashboard"
_REDIRECT = "https://robo.example/auth/callback"


def _b64(data: bytes, *, pad: bool = False) -> str:
    out = base64.urlsafe_b64encode(data).decode()
    return out if pad else out.rstrip("=")


def _jwk(key: rsa.RSAPrivateKey, kid: str) -> dict:
    pub = key.public_key().public_numbers()
    return {
        "kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256",
        "n": _b64(pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big")),
        "e": _b64(pub.e.to_bytes((pub.e.bit_length() + 7) // 8, "big")),
    }


def _sign(header: dict, claims: dict, key: rsa.RSAPrivateKey, *, pad: bool = False) -> str:
    h = _b64(json.dumps(header).encode(), pad=pad)
    p = _b64(json.dumps(claims).encode(), pad=pad)
    sig = key.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{h}.{p}.{_b64(sig, pad=pad)}"


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def idp(signing_key):
    state: dict = {"codes": {}, "id_token": None}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # keep test output quiet
            pass

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = urllib.parse.urlparse(self.path).path
            if path == "/.well-known/openid-configuration":
                return self._json(200, {
                    "issuer": base,
                    "authorization_endpoint": f"{base}/authorize",
                    "token_endpoint": f"{base}/token",
                    "jwks_uri": f"{base}/jwks",
                })
            if path == "/jwks":
                return self._json(200, {"keys": [_jwk(signing_key, "k1")]})
            return self._json(404, {})

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}
            if urllib.parse.urlparse(self.path).path != "/token":
                return self._json(404, {})
            if form.get("grant_type") == "authorization_code":
                challenge = state["codes"].pop(form.get("code"), None)
                verifier = form.get("code_verifier", "")
                if challenge is None or _b64(hashlib.sha256(verifier.encode()).digest()) != challenge:
                    return self._json(400, {"error": "invalid_grant"})
            elif form.get("grant_type") != "refresh_token":
                return self._json(400, {"error": "unsupported_grant_type"})
            return self._json(200, {"access_token": "opaque", "id_token": state["id_token"],
                                    "token_type": "Bearer", "refresh_token": "rt-1"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield base, state
    finally:
        server.shutdown()
        server.server_close()


def _claims(issuer: str, **overrides) -> dict:
    now = int(time.time())
    claims = {"iss": issuer, "aud": _CLIENT_ID, "sub": "usr_abc", "iat": now, "exp": now + 600,
              "email": "alice@example.com", "name": "Alice Example"}
    claims.update(overrides)
    return claims


def test_login_verifies_the_id_token_through_the_real_jwks_fetch(idp, signing_key):
    base, state = idp
    provider = SelfHostedOIDCProvider(issuer=base, client_id=_CLIENT_ID)
    start = provider.start_login(redirect_uri=_REDIRECT)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(start.redirect_url).query)
    pkce = dict(part.split("=", 1) for part in start.cookie_payload["robo_session_pkce"].split(";"))
    state["codes"]["code-1"] = query["code_challenge"][0]
    state["id_token"] = _sign({"alg": "RS256", "typ": "JWT", "kid": "k1"}, _claims(base), signing_key)

    session = provider.complete_login(code="code-1", state=query["state"][0],
                                      code_verifier=pkce["verifier"], redirect_uri=_REDIRECT)

    assert session.user_id == "usr_abc"
    assert session.email == "alice@example.com"
    assert provider.verify_session(access_token=session.access_token).user_id == "usr_abc"
    assert provider.refresh_session(refresh_token="rt-1").user_id == "usr_abc"


def test_padded_id_token_is_accepted(idp, signing_key):
    """Some IdPs (AWS ALB) sign tokens whose segments keep their '=' padding.
    PyJWT 2.14.0 and 2.15.0 rejected them; they must keep verifying."""
    base, _ = idp
    provider = SelfHostedOIDCProvider(issuer=base, client_id=_CLIENT_ID)
    token = _sign({"alg": "RS256", "typ": "JWT", "kid": "k1"}, _claims(base), signing_key, pad=True)
    assert "=" in token

    session = provider.verify_session(access_token=token)

    assert session is not None and session.user_id == "usr_abc"


def test_hs256_token_keyed_with_the_public_key_is_rejected(idp, signing_key):
    """Algorithm confusion: an HMAC token whose secret is the IdP's public key."""
    base, _ = idp
    provider = SelfHostedOIDCProvider(issuer=base, client_id=_CLIENT_ID)
    public_pem = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    h = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
    p = _b64(json.dumps(_claims(base, sub="attacker")).encode())
    forged = f"{h}.{p}.{_b64(hmac.new(public_pem, f'{h}.{p}'.encode(), hashlib.sha256).digest())}"

    with pytest.raises((ProviderError, InvalidCodeError)):
        provider._verify_id_token(forged)


def test_token_signed_by_another_key_is_rejected(idp):
    base, _ = idp
    provider = SelfHostedOIDCProvider(issuer=base, client_id=_CLIENT_ID)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _sign({"alg": "RS256", "typ": "JWT", "kid": "k1"}, _claims(base), other)

    with pytest.raises(ProviderError):
        provider._verify_id_token(token)
