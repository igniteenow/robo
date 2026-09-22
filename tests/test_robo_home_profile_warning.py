"""Tests for get_robo_home() profile-mode fallback warning.

Regression test for a previously reported bug.

When ROBO_HOME is unset but an active_profile file indicates a non-default
profile is active, get_robo_home() should:
  1. STILL return ~/.robo (raising would brick 30+ module-level callers)
  2. Emit a loud one-shot warning to stderr so operators can diagnose
     cross-profile data contamination after the fact.

The warning goes to stderr directly (not through logging) because this
function is called at module-import time from 30+ sites, often before the
logging subsystem has been configured.
"""

from pathlib import Path

import pytest


@pytest.fixture
def fresh_constants(monkeypatch, tmp_path):
    """Import robo_constants fresh and reset the one-shot warn flag."""
    import importlib
    import robo_constants
    importlib.reload(robo_constants)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("ROBO_HOME", raising=False)
    return robo_constants


class TestGetRoboHomeProfileWarning:
    def test_classic_mode_no_active_profile_no_warning(
        self, fresh_constants, tmp_path, capsys
    ):
        """Classic mode: no active_profile file → silent, returns ~/.robo."""
        result = fresh_constants.get_robo_home()
        assert result == tmp_path / ".robo"
        assert "ROBO_HOME fallback" not in capsys.readouterr().err


    def test_named_profile_unset_home_warns_once(
        self, fresh_constants, tmp_path, capsys
    ):
        """active_profile=coder + ROBO_HOME unset → warn loudly, still return fallback."""
        robo_dir = tmp_path / ".robo"
        robo_dir.mkdir()
        (robo_dir / "active_profile").write_text("coder\n")

        result = fresh_constants.get_robo_home()

        # 1. Still returns the fallback — no import-time crash
        assert result == tmp_path / ".robo"
        # 2. Stderr got the warning exactly once
        err = capsys.readouterr().err
        assert err.count("ROBO_HOME fallback") == 1
        assert "'coder'" in err
        assert "#18594" in err

        # 3. One-shot: second and third calls don't re-warn
        fresh_constants.get_robo_home()
        fresh_constants.get_robo_home()
        err2 = capsys.readouterr().err
        assert "ROBO_HOME fallback" not in err2

    def test_robo_home_set_suppresses_warning(
        self, fresh_constants, tmp_path, capsys, monkeypatch
    ):
        """Even if active_profile is 'coder', setting ROBO_HOME suppresses warning."""
        profile_dir = tmp_path / ".robo" / "profiles" / "coder"
        profile_dir.mkdir(parents=True)
        (tmp_path / ".robo" / "active_profile").write_text("coder\n")
        monkeypatch.setenv("ROBO_HOME", str(profile_dir))

        result = fresh_constants.get_robo_home()

        assert result == profile_dir
        assert "ROBO_HOME fallback" not in capsys.readouterr().err

    def test_unreadable_active_profile_no_crash(
        self, fresh_constants, tmp_path, capsys
    ):
        """active_profile that can't be decoded → fall through silently."""
        robo_dir = tmp_path / ".robo"
        robo_dir.mkdir()
        # Write bytes that aren't valid utf-8
        (robo_dir / "active_profile").write_bytes(b"\xff\xfe\x00\x00")

        result = fresh_constants.get_robo_home()

        assert result == tmp_path / ".robo"
        # Shouldn't crash; shouldn't warn either (can't tell what profile was intended)
        assert "ROBO_HOME fallback" not in capsys.readouterr().err

