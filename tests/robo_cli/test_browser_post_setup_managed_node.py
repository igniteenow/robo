"""`robo tools` browser post-setup ("Run setup") on a Robo-managed Node.

npm/npx resolved from <ROBO_HOME>/node run package scripts that call `node`
by name, so the children need Robo's Node dir on PATH. The Chromium install
passes --with-deps only off Windows: it installs Linux system libraries.
"""

import os
import sys
import types

import pytest

import robo_cli.tools_config as tools_config

# These tests stand in for Windows on a POSIX host (they patch sys.platform
# and use POSIX file modes and shell shims); Linux CI runs them. On a real
# Windows machine the same behavior is checked by hand.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="simulates Windows on a POSIX host"
)


@pytest.fixture
def managed_node_dir(tmp_path, monkeypatch):
    from robo_constants import iter_robo_node_dirs

    monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo-home"))
    directory = iter_robo_node_dirs()[0]
    directory.mkdir(parents=True)
    return directory


@pytest.fixture
def post_setup_calls(tmp_path, monkeypatch, managed_node_dir):
    import robo_constants
    import tools.browser_tool as browser_tool

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(tools_config, "PROJECT_ROOT", project)
    monkeypatch.setattr(
        robo_constants, "find_node_executable", lambda cmd: f"/managed/{cmd}"
    )
    monkeypatch.setattr(browser_tool, "_chromium_installed", lambda: False)
    monkeypatch.setattr(browser_tool, "_running_in_docker", lambda: False)
    monkeypatch.setenv("PATH", "/usr/bin")

    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append((list(cmd), kwargs.get("env")))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    return calls


def _path_entries(env) -> list[str]:
    assert env is not None, "child must get an explicit env with Robo's Node on PATH"
    return env["PATH"].split(os.pathsep)


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_npm_install_runs_with_robo_node_on_path(post_setup_calls, managed_node_dir, monkeypatch, platform):
    monkeypatch.setattr(tools_config.sys, "platform", platform)

    tools_config._run_post_setup("agent_browser")

    npm_cmd, npm_env = post_setup_calls[0]
    assert npm_cmd == ["/managed/npm", "install", "--silent", "--workspaces=false"]
    assert str(managed_node_dir) in _path_entries(npm_env)
    assert "/usr/bin" in _path_entries(npm_env)


def test_windows_chromium_install_has_no_with_deps(post_setup_calls, managed_node_dir, monkeypatch):
    monkeypatch.setattr(tools_config.sys, "platform", "win32")

    tools_config._run_post_setup("agent_browser")

    chromium_cmd, chromium_env = post_setup_calls[-1]
    assert chromium_cmd == ["/managed/npx", "-y", "agent-browser", "install"]
    assert str(managed_node_dir) in _path_entries(chromium_env)


def test_linux_chromium_install_keeps_with_deps(post_setup_calls, managed_node_dir, monkeypatch):
    monkeypatch.setattr(tools_config.sys, "platform", "linux")

    tools_config._run_post_setup("agent_browser")

    chromium_cmd, chromium_env = post_setup_calls[-1]
    assert chromium_cmd == ["/managed/npx", "-y", "agent-browser", "install", "--with-deps"]
    assert str(managed_node_dir) in _path_entries(chromium_env)


def test_cloud_browser_provider_skips_chromium(post_setup_calls, monkeypatch):
    monkeypatch.setattr(tools_config.sys, "platform", "win32")

    tools_config._run_post_setup("browserbase")

    assert [cmd for cmd, _env in post_setup_calls] == [
        ["/managed/npm", "install", "--silent", "--workspaces=false"]
    ]
