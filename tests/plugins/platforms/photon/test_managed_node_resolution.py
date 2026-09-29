"""Photon sidecar with Robo's own Node (<ROBO_HOME>/node, not on PATH).

node/npm are looked up on PATH first, then in Robo's Node dir; npm children
get Robo's Node dir appended to PATH. PHOTON_NODE_BIN keeps its meaning: when
set, only that binary counts.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

from plugins.platforms.photon import adapter as adapter_mod
from plugins.platforms.photon import cli as cli_mod

# These tests stand in for Windows on a POSIX host (they patch sys.platform
# and use POSIX file modes and shell shims); Linux CI runs them. On a real
# Windows machine the same behavior is checked by hand.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="simulates Windows on a POSIX host"
)


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def no_node_on_path(tmp_path, monkeypatch):
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("PHOTON_NODE_BIN", raising=False)
    return empty


@pytest.fixture
def managed_node(monkeypatch):
    import robo_constants

    monkeypatch.setattr(
        robo_constants, "find_robo_node_file", lambda cmd: f"/robo-home/node/{cmd}"
    )


class TestResolveNodeTool:
    def test_path_hit_wins(self, no_node_on_path, managed_node):
        on_path = _exe(no_node_on_path / "npm")

        assert adapter_mod._resolve_node_tool("npm") == str(on_path)

    def test_falls_back_to_robo_node(self, no_node_on_path, managed_node):
        assert adapter_mod._resolve_node_tool("npm") == "/robo-home/node/npm"
        assert adapter_mod._resolve_node_tool("node") == "/robo-home/node/node"

    def test_none_when_node_is_nowhere(self, no_node_on_path, monkeypatch):
        import robo_constants

        monkeypatch.setattr(robo_constants, "find_robo_node_file", lambda cmd: None)

        assert adapter_mod._resolve_node_tool("npm") is None


    def test_real_robo_node_file_is_found_without_running_anything(
        self, tmp_path, no_node_on_path, monkeypatch
    ):
        """check_requirements() runs on status probes: no process, no repair."""
        import robo_constants

        monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo-home"))
        npm = _exe(robo_constants.iter_robo_node_dirs()[0] / "npm")

        def boom(*_a, **_k):
            raise AssertionError("must not start a process or heal Node")

        monkeypatch.setattr(robo_constants, "node_tool_runnable", boom)
        monkeypatch.setattr(robo_constants, "heal_robo_managed_node", boom)
        monkeypatch.setattr("subprocess.run", boom)
        monkeypatch.setattr("subprocess.Popen", boom)

        assert adapter_mod._resolve_node_tool("npm") == str(npm)


class TestNodeBinOverride:
    def test_override_to_missing_binary_is_not_replaced(self, no_node_on_path, managed_node, monkeypatch):
        monkeypatch.setenv("PHOTON_NODE_BIN", "node-that-does-not-exist")

        assert adapter_mod._node_bin_for_sidecar() is None

    def test_override_to_existing_binary(self, tmp_path, no_node_on_path, managed_node, monkeypatch):
        custom = _exe(tmp_path / "custom" / "node")
        monkeypatch.setenv("PHOTON_NODE_BIN", str(custom))

        assert adapter_mod._node_bin_for_sidecar() == str(custom)

    def test_no_override_uses_robo_node(self, no_node_on_path, managed_node):
        assert adapter_mod._node_bin_for_sidecar() == "/robo-home/node/node"


def test_check_requirements_accepts_robo_node(tmp_path, no_node_on_path, managed_node, monkeypatch):
    monkeypatch.setattr(adapter_mod, "HTTPX_AVAILABLE", True)
    monkeypatch.setattr(adapter_mod, "_SIDECAR_DIR", tmp_path)
    (tmp_path / "node_modules" / "spectrum-ts").mkdir(parents=True)

    assert adapter_mod.check_requirements() is True


def test_check_requirements_still_false_without_any_node(tmp_path, no_node_on_path, monkeypatch):
    import robo_constants

    monkeypatch.setattr(robo_constants, "find_robo_node_file", lambda cmd: None)
    monkeypatch.setattr(adapter_mod, "HTTPX_AVAILABLE", True)
    monkeypatch.setattr(adapter_mod, "_SIDECAR_DIR", tmp_path)
    (tmp_path / "node_modules" / "spectrum-ts").mkdir(parents=True)

    assert adapter_mod.check_requirements() is False


def test_node_tool_env_appends_robo_node_dir(tmp_path, monkeypatch):
    from robo_constants import iter_robo_node_dirs

    monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo-home"))
    node_dir = iter_robo_node_dirs()[0]
    node_dir.mkdir(parents=True)

    env = adapter_mod._node_tool_env({"PATH": "/usr/bin", "KEEP": "1"})

    entries = env["PATH"].split(os.pathsep)
    assert entries[0] == "/usr/bin"
    assert str(node_dir) in entries[1:]
    assert env["KEEP"] == "1"


def test_install_sidecar_uses_robo_npm_with_robo_node_on_path(
    tmp_path, no_node_on_path, managed_node, monkeypatch
):
    from robo_constants import iter_robo_node_dirs

    monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo-home"))
    node_dir = iter_robo_node_dirs()[0]
    node_dir.mkdir(parents=True)
    monkeypatch.setattr(cli_mod, "_NPM_ERROR_LOG", tmp_path / ".photon-npm-error.log")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((list(cmd), kwargs.get("env")))
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)

    assert cli_mod._install_sidecar() == 0
    assert calls[0][0] == ["/robo-home/node/npm", "ci"]
    assert str(node_dir) in calls[0][1]["PATH"].split(os.pathsep)


def test_install_sidecar_without_npm_still_returns_1(tmp_path, no_node_on_path, monkeypatch):
    import robo_constants

    monkeypatch.setattr(robo_constants, "find_robo_node_file", lambda cmd: None)
    monkeypatch.setattr(cli_mod, "_NPM_ERROR_LOG", tmp_path / ".photon-npm-error.log")

    def fail_run(*_a, **_k):
        raise AssertionError("must not run npm when there is none")

    monkeypatch.setattr(cli_mod.subprocess, "run", fail_run)

    assert cli_mod._install_sidecar() == 1
