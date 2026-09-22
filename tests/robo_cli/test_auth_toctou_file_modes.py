"""Regression tests for TOCTOU-safe credential file writers in ``robo_cli.auth``.

Background
==========
The three writers below used to create a temp file via ``Path.write_text`` /
``Path.open('w')`` and only ``chmod``'d it to ``0o600`` afterward. Between
create and chmod the file existed at the process umask (typically ``0o644``),
briefly exposing OAuth tokens to other local users on multi-user hosts. The
fix switches them to ``os.open(O_EXCL, mode=0o600)`` + ``os.fdopen`` +
``fsync`` so the file is atomic at ``0o600`` on creation. Mirrors the fixes
shipped for ``agent/google_oauth.py`` (#19673) and ``tools/mcp_oauth.py``
(#21148).

These tests stay green only while the token file and its parent directory
end up at ``0o600`` / ``0o700`` after every write. POSIX-only — the mode-bit
enforcement does not exist on Windows.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from unittest.mock import patch

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="POSIX mode bits not enforced on Windows",
)


# ---------------------------------------------------------------------------
# _save_auth_store  (~/.robo/auth.json — every native OAuth provider)
# ---------------------------------------------------------------------------


def test_save_auth_store_writes_0o600_with_0o700_parent(tmp_path, monkeypatch):
    """``_save_auth_store`` must land ``auth.json`` at 0o600 and parent at 0o700."""
    monkeypatch.setenv("ROBO_HOME", str(tmp_path))
    old_umask = os.umask(0o022)  # make the race observable if it regresses
    try:
        from robo_cli import auth as auth_mod

        auth_store = {
            "version": auth_mod.AUTH_STORE_VERSION,
            "providers": {"openai-codex": {"tokens": {"access_token": "secret-x"}}},
            "active_provider": "openai-codex",
        }
        auth_path = auth_mod._save_auth_store(auth_store)
    finally:
        os.umask(old_umask)

    mode = stat.S_IMODE(auth_path.stat().st_mode)
    parent_mode = stat.S_IMODE(auth_path.parent.stat().st_mode)

    assert mode == 0o600, (
        f"auth.json mode 0o{mode:o} != 0o600 — TOCTOU race regressed"
    )
    assert parent_mode == 0o700, (
        f"auth.json parent dir mode 0o{parent_mode:o} != 0o700 — siblings can traverse"
    )

    # Content survived the rewrite
    data = json.loads(auth_path.read_text())
    assert data["providers"]["openai-codex"]["tokens"]["access_token"] == "secret-x"


# ---------------------------------------------------------------------------
# _save_qwen_cli_tokens  (Qwen CLI OAuth tokens)
# ---------------------------------------------------------------------------


def test_save_qwen_cli_tokens_writes_0o600_with_0o700_parent(tmp_path, monkeypatch):
    """``_save_qwen_cli_tokens`` must land the token file at 0o600 and parent at 0o700."""
    monkeypatch.setenv("ROBO_HOME", str(tmp_path))
    # The Qwen CLI auth path lives under $HOME/.qwen by default — isolate it.
    monkeypatch.setenv("HOME", str(tmp_path))
    old_umask = os.umask(0o022)
    try:
        from robo_cli import auth as auth_mod

        tokens = {
            "access_token": "qwen-secret",
            "refresh_token": "qwen-refresh",
            "token_type": "Bearer",
            "expiry_date": 123,
        }
        auth_path = auth_mod._save_qwen_cli_tokens(tokens)
    finally:
        os.umask(old_umask)

    mode = stat.S_IMODE(auth_path.stat().st_mode)
    parent_mode = stat.S_IMODE(auth_path.parent.stat().st_mode)

    assert mode == 0o600, (
        f"Qwen token file mode 0o{mode:o} != 0o600 — TOCTOU race regressed"
    )
    assert parent_mode == 0o700, (
        f"Qwen token parent dir mode 0o{parent_mode:o} != 0o700"
    )

    data = json.loads(auth_path.read_text())
    assert data["access_token"] == "qwen-secret"


def test_save_auth_store_uses_os_open_with_0o600_mode(tmp_path, monkeypatch):
    """Regression: the writer must call ``os.open`` with an explicit restricted
    mode so the file is created at 0o600 atomically — closing the TOCTOU
    window the previous ``Path.open('w')`` left open (fd inherited process
    umask and was briefly 0o644 before post-write chmod)."""
    monkeypatch.setenv("ROBO_HOME", str(tmp_path))

    observed_opens: list[tuple[str, int, int]] = []
    real_os_open = os.open

    def spying_os_open(path, flags, mode=0o777, *args, **kwargs):
        observed_opens.append((str(path), flags, mode))
        return real_os_open(path, flags, mode, *args, **kwargs)

    with patch.object(os, "open", spying_os_open):
        from robo_cli import auth as auth_mod

        auth_mod._save_auth_store(
            {"version": auth_mod.AUTH_STORE_VERSION, "providers": {}}
        )

    auth_tmp_opens = [
        (p, fl, m) for (p, fl, m) in observed_opens if "auth.json.tmp" in p
    ]
    assert auth_tmp_opens, (
        f"os.open was never called for the auth.json temp file; "
        f"observed={observed_opens!r}"
    )
    for path, flags, mode in auth_tmp_opens:
        assert flags & os.O_CREAT, f"auth.json temp open missing O_CREAT: path={path}"
        assert flags & os.O_EXCL, (
            f"auth.json temp open missing O_EXCL — TOCTOU-safe pattern regressed: "
            f"path={path}, flags={flags}"
        )
        # Must be exactly S_IRUSR | S_IWUSR (0o600) — no group/other bits.
        expected = stat.S_IRUSR | stat.S_IWUSR
        assert mode == expected, (
            f"auth.json temp open mode 0o{mode:o} != 0o{expected:o} — "
            f"umask would apply and potentially expose tokens"
        )
