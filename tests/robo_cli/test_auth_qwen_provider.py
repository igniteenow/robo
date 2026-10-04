"""Tests for Qwen OAuth provider authentication (robo_cli/auth.py).

Covers: _qwen_cli_auth_path, _read_qwen_cli_tokens, _save_qwen_cli_tokens,
_qwen_access_token_is_expiring, _refresh_qwen_cli_tokens,
resolve_qwen_runtime_credentials, get_qwen_auth_status.
"""

import json
import stat
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from robo_cli.auth import (
    AuthError,
    DEFAULT_QWEN_BASE_URL,
    QWEN_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
    _qwen_cli_auth_path,
    _read_qwen_cli_tokens,
    _save_qwen_cli_tokens,
    _qwen_access_token_is_expiring,
    _refresh_qwen_cli_tokens,
    resolve_qwen_runtime_credentials,
    get_qwen_auth_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_qwen_tokens(
    access_token="test-access-token",
    refresh_token="test-refresh-token",
    expiry_date=None,
    **extra,
):
    """Create a minimal Qwen CLI OAuth credential dict."""
    if expiry_date is None:
        # 1 hour from now in milliseconds
        expiry_date = int((time.time() + 3600) * 1000)
    data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expiry_date": expiry_date,
        "resource_url": "portal.qwen.ai",
    }
    data.update(extra)
    return data


def _write_qwen_creds(tmp_path, tokens=None):
    """Write tokens to the Qwen CLI credentials file and return the path."""
    qwen_dir = tmp_path / ".qwen"
    qwen_dir.mkdir(parents=True, exist_ok=True)
    creds_path = qwen_dir / "oauth_creds.json"
    if tokens is None:
        tokens = _make_qwen_tokens()
    creds_path.write_text(json.dumps(tokens), encoding="utf-8")
    return creds_path


@pytest.fixture()
def qwen_env(tmp_path, monkeypatch):
    """Redirect _qwen_cli_auth_path to tmp_path/.qwen/oauth_creds.json."""
    creds_path = tmp_path / ".qwen" / "oauth_creds.json"
    monkeypatch.setattr(
        "robo_cli.auth._qwen_cli_auth_path", lambda: creds_path
    )
    return tmp_path


# ---------------------------------------------------------------------------
# _qwen_cli_auth_path
# ---------------------------------------------------------------------------

def test_qwen_cli_auth_path_returns_expected_location():
    path = _qwen_cli_auth_path()
    assert path == Path.home() / ".qwen" / "oauth_creds.json"


# ---------------------------------------------------------------------------
# _read_qwen_cli_tokens
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# _save_qwen_cli_tokens
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# _qwen_access_token_is_expiring
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# _refresh_qwen_cli_tokens
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# resolve_qwen_runtime_credentials
# ---------------------------------------------------------------------------

def test_resolve_qwen_runtime_credentials_fresh_token(qwen_env):
    tokens = _make_qwen_tokens(access_token="fresh-at")
    _write_qwen_creds(qwen_env, tokens)

    creds = resolve_qwen_runtime_credentials(refresh_if_expiring=False)
    assert creds["provider"] == "qwen-oauth"
    assert creds["api_key"] == "fresh-at"
    assert creds["base_url"] == DEFAULT_QWEN_BASE_URL
    assert creds["source"] == "qwen-cli"


def test_resolve_qwen_runtime_credentials_missing_access_token(qwen_env):
    tokens = _make_qwen_tokens(access_token="")
    _write_qwen_creds(qwen_env, tokens)

    with pytest.raises(AuthError) as exc:
        resolve_qwen_runtime_credentials(refresh_if_expiring=False)
    assert exc.value.code == "qwen_access_token_missing"


# ---------------------------------------------------------------------------
# get_qwen_auth_status
# ---------------------------------------------------------------------------

def test_get_qwen_auth_status_logged_in(qwen_env):
    tokens = _make_qwen_tokens(access_token="status-at")
    _write_qwen_creds(qwen_env, tokens)

    status = get_qwen_auth_status()
    assert status["logged_in"] is True
    assert status["api_key"] == "status-at"


def test_get_qwen_auth_status_refreshes_expired_token(qwen_env):
    expired_ms = int((time.time() - 3600) * 1000)
    tokens = _make_qwen_tokens(access_token="old-at", expiry_date=expired_ms)
    _write_qwen_creds(qwen_env, tokens)

    refreshed = _make_qwen_tokens(access_token="refreshed-at")

    with patch(
        "robo_cli.auth._refresh_qwen_cli_tokens", return_value=refreshed
    ) as mock_refresh:
        status = get_qwen_auth_status()

    mock_refresh.assert_called_once()
    assert status["logged_in"] is True
    assert status["api_key"] == "refreshed-at"


def test_model_flow_qwen_oauth_stale_token_shows_reauth_guidance(qwen_env, monkeypatch, capsys):
    from robo_cli.main import _model_flow_qwen_oauth

    expired_ms = int((time.time() - 3600) * 1000)
    tokens = _make_qwen_tokens(access_token="dead-at", expiry_date=expired_ms)
    _write_qwen_creds(qwen_env, tokens)

    monkeypatch.setattr(
        "robo_cli.auth._refresh_qwen_cli_tokens",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AuthError(
                "Qwen refresh rejected.",
                provider="qwen-oauth",
                code="qwen_refresh_failed",
            )
        ),
    )

    prompt_called = {"value": False}
    update_called = {"value": False}

    monkeypatch.setattr(
        "robo_cli.auth._prompt_model_selection",
        lambda *args, **kwargs: prompt_called.__setitem__("value", True),
    )
    monkeypatch.setattr(
        "robo_cli.auth._update_config_for_provider",
        lambda *args, **kwargs: update_called.__setitem__("value", True),
    )

    _model_flow_qwen_oauth({}, current_model="qwen3-coder-plus")

    out = capsys.readouterr().out
    # Qwen discontinued the sign-in, so the flow must not send the user to a
    # command that no longer exists; it names what to pick instead.
    assert "qwen auth" not in out
    assert "Qwen Cloud" in out
    assert "Qwen refresh rejected" in out
    assert prompt_called["value"] is False
    assert update_called["value"] is False


# ---------------------------------------------------------------------------
# Qwen discontinued its OAuth sign-in (2026-04-15)
# ---------------------------------------------------------------------------

def test_missing_qwen_login_explains_the_discontinued_sign_in(qwen_env):
    """No Qwen login on this computer: the error says the sign-in is gone and
    what to use instead, and never names the removed `qwen auth` command."""
    from robo_cli.auth import QWEN_OAUTH_ENDED_HINT

    with pytest.raises(AuthError) as exc_info:
        _read_qwen_cli_tokens()

    message = str(exc_info.value)
    assert exc_info.value.code == "qwen_auth_missing"
    assert QWEN_OAUTH_ENDED_HINT in message
    assert "2026-04-15" in message
    assert "Qwen Cloud" in message
    assert "qwen auth" not in message


def test_no_qwen_error_points_at_the_removed_command(qwen_env):
    """Every Qwen OAuth dead end (missing refresh token, rejected refresh,
    missing access token) carries the same guidance."""
    from robo_cli.auth import QWEN_OAUTH_ENDED_HINT

    with pytest.raises(AuthError) as no_refresh:
        _refresh_qwen_cli_tokens(_make_qwen_tokens(refresh_token=""))
    assert QWEN_OAUTH_ENDED_HINT in str(no_refresh.value)

    rejected = MagicMock(status_code=400, text="invalid_grant")
    with patch("robo_cli.auth.httpx.post", return_value=rejected):
        with pytest.raises(AuthError) as refused:
            _refresh_qwen_cli_tokens(_make_qwen_tokens())
    assert QWEN_OAUTH_ENDED_HINT in str(refused.value)
    assert "invalid_grant" in str(refused.value)

    _write_qwen_creds(qwen_env, _make_qwen_tokens(access_token=""))
    with pytest.raises(AuthError) as no_access:
        resolve_qwen_runtime_credentials(refresh_if_expiring=False)
    assert QWEN_OAUTH_ENDED_HINT in str(no_access.value)

    for exc in (no_refresh, refused, no_access):
        assert "qwen auth" not in str(exc.value)


def test_model_flow_without_a_qwen_login_says_what_to_pick(qwen_env, capsys):
    from robo_cli.main import _model_flow_qwen_oauth

    _model_flow_qwen_oauth({}, current_model="")

    out = capsys.readouterr().out
    assert "No working Qwen OAuth login" in out
    assert "Qwen Cloud" in out
    assert "qwen auth" not in out
    # The guidance is printed once, not once per line that mentions it.
    assert out.count("2026-04-15") == 1


def test_auth_add_qwen_without_a_login_exits_cleanly(qwen_env, tmp_path, monkeypatch, capsys):
    """`robo auth add qwen-oauth` with no Qwen login used to end in a Python
    traceback. It now prints the reason and exits 1."""
    monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo"))
    (tmp_path / "robo").mkdir()

    from types import SimpleNamespace

    from robo_cli.auth_commands import auth_command

    args = SimpleNamespace(auth_action="add", provider="qwen-oauth", auth_type=None, api_key=None, label=None)

    with pytest.raises(SystemExit) as exit_info:
        auth_command(args)

    assert exit_info.value.code == 1
    # Raised without a chained cause, so nothing prints a traceback.
    assert exit_info.value.__cause__ is None
    captured = capsys.readouterr()
    assert captured.err.startswith("\u2717 No Qwen login was found on this computer")
    assert "Qwen Cloud" in captured.err
    assert "Traceback" not in captured.err + captured.out


def test_auth_command_still_passes_other_errors_through(monkeypatch):
    """Only an expected sign-in failure is turned into a clean exit; a real
    bug must still surface as itself."""
    from types import SimpleNamespace

    from robo_cli import auth_commands

    def _boom(_args):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(auth_commands, "auth_list_command", _boom)

    with pytest.raises(RuntimeError, match="unexpected"):
        auth_commands.auth_command(SimpleNamespace(auth_action="list"))
