"""Robo finds the Chrome that agent-browser itself launches.

agent-browser 0.26 (the pinned version) downloads Chrome for Testing into
~/.agent-browser/browsers/chrome-<version>/ and launches it from there, or
from the standard Chrome install folders. Robo only looked on PATH and in
Playwright's cache, so after "Run setup" reported "Chromium installed" the
browser tool stayed hidden and doctor said "not installed".
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.browser_tool as bt

# These tests stand in for Windows/macOS on a POSIX host (they patch
# sys.platform); Linux CI runs them. Real Windows is checked by hand.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="simulates Windows on a POSIX host"
)


def _file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


@pytest.fixture
def clean_machine(tmp_path, monkeypatch):
    """No browser anywhere: empty PATH, empty home, no overrides."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.delenv("AGENT_BROWSER_EXECUTABLE_PATH", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    bt._cached_chromium_installed = None
    yield SimpleNamespace(home=home, localappdata=tmp_path / "localappdata")
    bt._cached_chromium_installed = None


def _browsers_dir(home: Path) -> Path:
    return home / ".agent-browser" / "browsers"


class TestAgentBrowserDownload:
    def test_nothing_installed(self, clean_machine):
        assert bt._chromium_installed() is False

    @pytest.mark.parametrize(
        "platform, layout",
        [
            ("linux", "chrome-linux64/chrome"),
            ("linux", "chrome"),
            ("win32", "chrome-win64/chrome.exe"),
            ("win32", "chrome.exe"),
            (
                "darwin",
                "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
            ),
        ],
    )
    def test_found_in_agent_browser_download_dir(self, clean_machine, monkeypatch, platform, layout):
        monkeypatch.setattr(bt.sys, "platform", platform)
        _file(_browsers_dir(clean_machine.home) / "chrome-147.0.7727.57" / layout)

        assert bt._chromium_installed() is True

    def test_empty_version_folder_does_not_count(self, clean_machine, monkeypatch):
        monkeypatch.setattr(bt.sys, "platform", "win32")
        (_browsers_dir(clean_machine.home) / "chrome-147.0.7727.57").mkdir(parents=True)

        assert bt._chromium_installed() is False

    def test_other_platform_binary_does_not_count(self, clean_machine, monkeypatch):
        monkeypatch.setattr(bt.sys, "platform", "win32")
        _file(_browsers_dir(clean_machine.home) / "chrome-147.0.7727.57" / "chrome-linux64" / "chrome")

        assert bt._chromium_installed() is False


class TestInstalledChrome:
    @pytest.mark.parametrize(
        "relative",
        [
            ("Google", "Chrome", "Application", "chrome.exe"),
            ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        ],
    )
    def test_windows_per_user_install(self, clean_machine, monkeypatch, relative):
        monkeypatch.setattr(bt.sys, "platform", "win32")
        _file(clean_machine.localappdata.joinpath(*relative))

        assert bt._chromium_installed() is True

    def test_windows_program_files_paths_are_checked(self, clean_machine, monkeypatch):
        monkeypatch.setattr(bt.sys, "platform", "win32")

        paths = bt._system_chrome_install_paths()

        assert r"C:\Program Files\Google\Chrome\Application\chrome.exe" in paths
        assert r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" in paths

    def test_linux_adds_no_fixed_paths(self, monkeypatch):
        monkeypatch.setattr(bt.sys, "platform", "linux")

        assert bt._system_chrome_install_paths() == []


class TestPostSetupReportsWhatRoboCanSee:
    @pytest.fixture
    def run_setup(self, tmp_path, monkeypatch):
        import types

        import robo_cli.tools_config as tools_config
        import robo_constants

        project = tmp_path / "project"
        (project / "node_modules" / "agent-browser").mkdir(parents=True)
        monkeypatch.setattr(tools_config, "PROJECT_ROOT", project)
        monkeypatch.setattr(robo_constants, "find_node_executable", lambda cmd: f"/managed/{cmd}")
        monkeypatch.setattr(bt, "_running_in_docker", lambda: False)
        monkeypatch.setattr(
            "subprocess.run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr="")
        )
        messages = []
        monkeypatch.setattr(tools_config, "_print_success", lambda m: messages.append(("ok", m)))
        monkeypatch.setattr(tools_config, "_print_warning", lambda m: messages.append(("warn", m)))
        monkeypatch.setattr(tools_config, "_print_info", lambda m: messages.append(("info", m)))

        def run(found_after_install: bool):
            checks = iter([False, found_after_install])
            monkeypatch.setattr(bt, "_chromium_installed", lambda: next(checks))
            tools_config._run_post_setup("agent_browser")
            return messages

        return run

    def test_success_when_the_browser_is_found(self, run_setup):
        messages = run_setup(found_after_install=True)

        assert ("ok", "    Chromium installed") in messages

    def test_warns_when_the_download_is_not_found(self, run_setup):
        messages = run_setup(found_after_install=False)

        assert ("ok", "    Chromium installed") not in messages
        assert any(kind == "warn" and "cannot find it" in text for kind, text in messages)
