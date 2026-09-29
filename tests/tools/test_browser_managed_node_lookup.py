"""Browser tools on a machine whose Node is Robo's own (<ROBO_HOME>/node).

The Windows installer puts agent-browser and npx there without adding the
folder to PATH, so presence checks and the npx fallback must look there too,
and install hints must not tell Windows users to pass --with-deps (an
apt-based Linux flag).
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.browser_tool as bt

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
def isolated_lookup(tmp_path, monkeypatch):
    """PATH with nothing on it, no system bin dirs, a temp ROBO_HOME."""
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    home = tmp_path / "robo-home"
    monkeypatch.setenv("ROBO_HOME", str(home))
    monkeypatch.setattr(bt, "_SANE_PATH_DIRS", ())
    monkeypatch.setattr(bt, "_discover_homebrew_node_dirs", lambda: ())
    return SimpleNamespace(home=home, path_dir=empty)


def _repo_has_local_agent_browser() -> bool:
    local_bin = Path(bt.__file__).parent.parent / "node_modules" / ".bin"
    return any((local_bin / name).exists() for name in ("agent-browser", "agent-browser.cmd"))


class TestAgentBrowserInstalled:
    @pytest.mark.parametrize("node_subdir", ["node", os.path.join("node", "bin")])
    def test_found_in_robo_node_dir_not_on_path(self, isolated_lookup, node_subdir):
        _exe(isolated_lookup.home / node_subdir / "agent-browser")

        assert bt.agent_browser_installed() is True

    def test_found_on_path(self, isolated_lookup):
        _exe(isolated_lookup.path_dir / "agent-browser")

        assert bt.agent_browser_installed() is True

    def test_missing_everywhere(self, isolated_lookup):
        if _repo_has_local_agent_browser():
            pytest.skip("this checkout has node_modules/.bin/agent-browser")

        assert bt.agent_browser_installed() is False

    def test_never_starts_a_process(self, isolated_lookup, monkeypatch):
        _exe(isolated_lookup.home / "node" / "agent-browser")

        def boom(*_a, **_k):
            raise AssertionError("presence check must not run anything")

        monkeypatch.setattr(bt.subprocess, "run", boom)
        monkeypatch.setattr(bt.subprocess, "Popen", boom)

        assert bt.agent_browser_installed() is True


class TestLocalBrowserRunnable:
    def test_setup_status_sees_managed_agent_browser(self, isolated_lookup):
        from robo_cli.igniteenow_subscription import _local_browser_runnable

        _exe(isolated_lookup.home / "node" / "agent-browser")

        assert _local_browser_runnable() is True

    def test_setup_status_reports_missing(self, isolated_lookup):
        from robo_cli.igniteenow_subscription import _local_browser_runnable

        if _repo_has_local_agent_browser():
            pytest.skip("this checkout has node_modules/.bin/agent-browser")

        assert _local_browser_runnable() is False


class TestNpxCommand:
    def test_prefers_npx_on_path(self, isolated_lookup):
        on_path = _exe(isolated_lookup.path_dir / "npx")
        _exe(isolated_lookup.home / "node" / "bin" / "npx")

        assert bt._npx_command() == str(on_path)

    def test_falls_back_to_robo_node_dir(self, isolated_lookup):
        managed = _exe(isolated_lookup.home / "node" / "bin" / "npx")

        assert bt._npx_command() == str(managed)

    def test_bare_name_when_npx_is_nowhere(self, isolated_lookup):
        assert bt._npx_command() == "npx"


class TestInstallHints:
    def test_windows_hints_have_no_with_deps(self, monkeypatch):
        monkeypatch.setattr(bt.sys, "platform", "win32")
        monkeypatch.setattr(bt, "_is_termux_environment", lambda: False)

        assert bt._deps_flag_hint() == ""
        assert "--with-deps" not in bt._chromium_install_hint()
        assert "--with-deps" not in bt._browser_install_hint()
        assert bt._chromium_install_hint() == (
            "npx agent-browser install (or: npx playwright install chromium)"
        )

    def test_linux_hints_are_unchanged(self, monkeypatch):
        monkeypatch.setattr(bt.sys, "platform", "linux")
        monkeypatch.setattr(bt, "_is_termux_environment", lambda: False)

        assert bt._chromium_install_hint() == (
            "npx agent-browser install --with-deps "
            "(or: npx playwright install --with-deps chromium)"
        )
        assert bt._browser_install_hint() == (
            "npm install -g agent-browser && agent-browser install --with-deps"
        )


class TestChromiumAutoInstallEnv:
    @pytest.fixture(autouse=True)
    def _reset_state(self):
        bt._chromium_autoinstall_attempted = False
        bt._cached_chromium_installed = None
        yield
        bt._chromium_autoinstall_attempted = False
        bt._cached_chromium_installed = None

    def test_install_child_gets_robo_node_dir_on_path(self, isolated_lookup, monkeypatch):
        node_dir = isolated_lookup.home / "node"
        _exe(node_dir / "agent-browser")
        monkeypatch.setattr(bt, "_running_in_docker", lambda: False)
        monkeypatch.setattr("tools.lazy_deps._allow_lazy_installs", lambda: True)
        monkeypatch.setattr(bt, "_find_agent_browser", lambda: str(node_dir / "agent-browser"))
        monkeypatch.setattr(bt, "_build_browser_env", lambda: {"PATH": "/usr/bin"})
        monkeypatch.setattr(bt, "_chromium_installed", lambda: True)
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(bt.subprocess, "run", fake_run)

        assert bt._maybe_autoinstall_chromium() is True
        entries = captured["env"]["PATH"].split(os.pathsep)
        assert str(node_dir) in entries
        assert entries[-1] == "/usr/bin"
