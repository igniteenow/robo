"""Regression tests for the config.yaml → env var bridge in gateway/run.py.

Guards against the 60-vs-500 bug where a stale `.env ROBO_MAX_ITERATIONS=60`
entry silently shadowed `agent.max_turns: 500` in config.yaml because the
bridge used `if X not in os.environ` guards. After PR#18413 the bridge
treats config.yaml as authoritative and unconditionally overwrites .env
values for `agent.*`, `display.*`, `timezone`, and `security.*` keys.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_gateway_import(robo_home: Path, initial_env: dict[str, str]) -> dict[str, str]:
    """Import gateway.run in a clean subprocess and return the post-import env.

    The bridge runs at module-import time, so simply importing is enough
    to exercise it. Running in a subprocess isolates the test from other
    import side effects and makes the "what ends up in os.environ" check
    deterministic.
    """
    script = textwrap.dedent(
        f"""
        import os, sys
        sys.path.insert(0, {str(PROJECT_ROOT)!r})

        try:
            from gateway import run  # noqa: F401  — module import triggers bridge
        except Exception as exc:
            print(f"IMPORT_ERROR:{{type(exc).__name__}}:{{exc}}", file=sys.stderr)
            sys.exit(2)

        for k in (
            "ROBO_MAX_ITERATIONS",
            "ROBO_AGENT_TIMEOUT",
            "ROBO_AGENT_TIMEOUT_WARNING",
            "ROBO_SESSION_STALL_TIMEOUT",
            "ROBO_GATEWAY_BUSY_INPUT_MODE",
            "ROBO_GATEWAY_BUSY_TEXT_MODE",
            "ROBO_GATEWAY_PLATFORM_CONNECT_TIMEOUT",
            "ROBO_TIMEZONE",
            "ROBO_HUMAN_DELAY_MODE",
            "ROBO_HUMAN_DELAY_MIN_MS",
            "ROBO_HUMAN_DELAY_MAX_MS",
        ):
            v = os.environ.get(k)
            if v is not None:
                print(f"{{k}}={{v}}")
        """
    )
    env = dict(initial_env)
    env["ROBO_HOME"] = str(robo_home)
    # Keep PATH / PYTHONPATH so venv imports resolve. On Windows the child
    # also needs the system variables: without SYSTEMROOT, Winsock cannot
    # initialise and ``import socket`` (pulled in by asyncio during the
    # gateway import) dies with ``WinError 10106`` before the bridge runs;
    # tempfile / Path.home() want TEMP and USERPROFILE. None of these can
    # shadow a ROBO_* variable the assertions look at.
    passthrough = ["PATH", "PYTHONPATH", "VIRTUAL_ENV", "HOME"]
    if sys.platform == "win32":
        passthrough += [
            "SYSTEMROOT",
            "SYSTEMDRIVE",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "HOMEDRIVE",
            "HOMEPATH",
            "LOCALAPPDATA",
            "APPDATA",
            "PROGRAMDATA",
        ]
    for k in passthrough:
        if k in os.environ and k not in env:
            env[k] = os.environ[k]

    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        pytest.fail(
            f"gateway.run import failed (rc={result.returncode})\n"
            f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
        )
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def _write_config(home: Path, agent_cfg: dict | None = None, display_cfg: dict | None = None,
                  timezone: str | None = None, gateway_cfg: dict | None = None,
                  human_delay_cfg: dict | None = None) -> None:
    import yaml
    cfg: dict = {}
    if agent_cfg:
        cfg["agent"] = agent_cfg
    if display_cfg:
        cfg["display"] = display_cfg
    if gateway_cfg:
        cfg["gateway"] = gateway_cfg
    if timezone:
        cfg["timezone"] = timezone
    if human_delay_cfg:
        cfg["human_delay"] = human_delay_cfg
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))


def _write_env(home: Path, entries: dict[str, str]) -> None:
    lines = [f"{k}={v}\n" for k, v in entries.items()]
    (home / ".env").write_text("".join(lines))


@pytest.fixture
def robo_home(tmp_path: Path) -> Path:
    home = tmp_path / ".robo"
    home.mkdir()
    return home


def test_config_gateway_timeout_wins_over_stale_env(robo_home: Path) -> None:
    """Every agent.* bridge key must be config-authoritative, not .env-authoritative."""
    _write_config(robo_home, agent_cfg={
        "gateway_timeout": 1800,
        "gateway_timeout_warning": 900,
        "session_stall_timeout": 300,
    })
    _write_env(robo_home, {
        "ROBO_AGENT_TIMEOUT": "60",
        "ROBO_AGENT_TIMEOUT_WARNING": "30",
        "ROBO_SESSION_STALL_TIMEOUT": "15",
    })

    env = _run_gateway_import(robo_home, initial_env={})

    assert env.get("ROBO_AGENT_TIMEOUT") == "1800"
    assert env.get("ROBO_AGENT_TIMEOUT_WARNING") == "900"
    assert env.get("ROBO_SESSION_STALL_TIMEOUT") == "300"


def test_config_platform_connect_timeout_supplies_env_when_unset(robo_home: Path) -> None:
    """config.yaml:gateway.platform_connect_timeout supplies the env var when
    it isn't already set (#19776 — config surface for the Discord connect
    timeout, replacing the undocumented env-var-only workaround)."""
    _write_config(robo_home, gateway_cfg={"platform_connect_timeout": 90})

    env = _run_gateway_import(robo_home, initial_env={})

    assert env.get("ROBO_GATEWAY_PLATFORM_CONNECT_TIMEOUT") == "90"


def test_env_platform_connect_timeout_wins_over_config(robo_home: Path) -> None:
    """Unlike the agent.*/display.*/timezone bridges (config-authoritative),
    ROBO_GATEWAY_PLATFORM_CONNECT_TIMEOUT is the manual-override escape hatch:
    an explicitly-set env var WINS over config.yaml. This divergence is
    intentional (#19776) — the env var is the operator's emergency knob."""
    _write_config(robo_home, gateway_cfg={"platform_connect_timeout": 90})

    env = _run_gateway_import(
        robo_home,
        initial_env={"ROBO_GATEWAY_PLATFORM_CONNECT_TIMEOUT": "120"},
    )

    assert env.get("ROBO_GATEWAY_PLATFORM_CONNECT_TIMEOUT") == "120"


def test_config_human_delay_is_bridged_and_wins_over_stale_env(robo_home: Path) -> None:
    """``human_delay`` shipped in config defaults, the docs and the dashboard
    settings, but only the ROBO_HUMAN_DELAY_* env vars were ever read — the
    documented block was a knob wired to nothing. It is bridged now, and like
    every other config.yaml section it is authoritative over a stale .env."""
    _write_config(robo_home, human_delay_cfg={"mode": "custom", "min_ms": 300, "max_ms": 900})
    _write_env(robo_home, {"ROBO_HUMAN_DELAY_MODE": "off", "ROBO_HUMAN_DELAY_MIN_MS": "800"})

    out = _run_gateway_import(robo_home, {})

    assert out.get("ROBO_HUMAN_DELAY_MODE") == "custom"
    assert out.get("ROBO_HUMAN_DELAY_MIN_MS") == "300"
    assert out.get("ROBO_HUMAN_DELAY_MAX_MS") == "900"


def test_human_delay_env_survives_without_a_config_block(robo_home: Path) -> None:
    """No ``human_delay`` block in config.yaml → the env vars stay as set."""
    _write_config(robo_home, timezone="UTC")
    _write_env(robo_home, {"ROBO_HUMAN_DELAY_MODE": "natural"})

    out = _run_gateway_import(robo_home, {})

    assert out.get("ROBO_HUMAN_DELAY_MODE") == "natural"
