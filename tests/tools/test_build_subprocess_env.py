"""Tests for tools.environments.local.build_subprocess_env — the single
factory for child-process environments (profile-home + secret-scrub owner).
"""

import os
import subprocess
import sys

import pytest

from tools.environments.local import build_subprocess_env


# ---------------------------------------------------------------------------
# Unit: scrub path delegates to _sanitize_subprocess_env semantics
# ---------------------------------------------------------------------------

def test_scrub_on_strips_provider_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    env = build_subprocess_env()
    assert "ANTHROPIC_API_KEY" not in env


def test_scrub_on_strips_dynamic_internal_secret(monkeypatch):
    monkeypatch.setenv("AUXILIARY_VISION_API_KEY", "sk-aux")
    monkeypatch.setenv("GATEWAY_RELAY_FOO_TOKEN", "tok")
    env = build_subprocess_env()
    assert "AUXILIARY_VISION_API_KEY" not in env
    assert "GATEWAY_RELAY_FOO_TOKEN" not in env


def test_scrub_on_forwards_extra_like_sanitize_extra_env(monkeypatch):
    env = build_subprocess_env(extra={"MY_HARMLESS_VAR": "1"})
    assert env.get("MY_HARMLESS_VAR") == "1"
    # extra still goes through the blocklist on the scrub path
    env2 = build_subprocess_env(extra={"ANTHROPIC_API_KEY": "sk"})
    assert "ANTHROPIC_API_KEY" not in env2


# ---------------------------------------------------------------------------
# Unit: no-scrub path preserves content exactly
# ---------------------------------------------------------------------------


def test_no_scrub_inherit_profile_home_bridges_context_override(tmp_path):
    from robo_constants import set_robo_home_override, reset_robo_home_override

    token = set_robo_home_override(str(tmp_path))
    try:
        env = build_subprocess_env(
            {"PATH": "/bin"}, scrub_secrets=False, inherit_profile_home=True
        )
    finally:
        reset_robo_home_override(token)
    assert env["ROBO_HOME"] == str(tmp_path)


# ---------------------------------------------------------------------------
# E2E: real subprocess sees the factory's contract
# ---------------------------------------------------------------------------

def test_e2e_child_sees_robo_home_and_no_planted_secret(tmp_path, monkeypatch):
    """A real child spawned with a factory-built env must see ROBO_HOME
    propagated and (with scrub on) a planted provider-style key absent."""
    robo_home = tmp_path / "robo-home"
    robo_home.mkdir()
    monkeypatch.setenv("ROBO_HOME", str(robo_home))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-FAKE-planted")
    monkeypatch.setenv("AUXILIARY_FAKE_API_KEY", "sk-FAKE-aux")

    env = build_subprocess_env()  # scrub on (default)

    code = (
        "import os, json; "
        "print(json.dumps({'home': os.environ.get('ROBO_HOME'), "
        "'k1': 'ANTHROPIC_API_KEY' in os.environ, "
        "'k2': 'AUXILIARY_FAKE_API_KEY' in os.environ}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        env=env, capture_output=True, text=True, timeout=60, check=True,
    )
    import json

    result = json.loads(out.stdout)
    assert result["home"] == str(robo_home)
    assert result["k1"] is False
    assert result["k2"] is False


def test_e2e_no_scrub_child_keeps_planted_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-FAKE-planted")
    env = build_subprocess_env(scrub_secrets=False, inherit_profile_home=False)
    out = subprocess.run(
        [sys.executable, "-c",
         "import os; print(os.environ.get('ANTHROPIC_API_KEY', ''))"],
        env=env, capture_output=True, text=True, timeout=60, check=True,
    )
    assert out.stdout.strip() == "sk-FAKE-planted"
