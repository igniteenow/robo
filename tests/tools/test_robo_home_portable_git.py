"""PortableGit under a custom ROBO_HOME.

scripts/install.ps1 installs PortableGit into $RoboHome\\git. With a custom
ROBO_HOME that folder is not under %LOCALAPPDATA%\\robo, which is the only
place the terminal tool and the startup PATH fix-up used to look.
"""

import os
import sys
from pathlib import Path

import pytest

# These tests stand in for Windows on a POSIX host (they patch sys.platform
# and use POSIX file modes and shell shims); Linux CI runs them. On a real
# Windows machine the same behavior is checked by hand.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="simulates Windows on a POSIX host"
)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


class TestFindBash:
    @pytest.fixture
    def windows_local(self, tmp_path, monkeypatch):
        from tools.environments import local as local_mod

        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        monkeypatch.setattr(local_mod, "_bash_starts", lambda candidate: True)
        monkeypatch.setattr(local_mod.shutil, "which", lambda name, *a, **k: None)
        monkeypatch.delenv("ROBO_GIT_BASH_PATH", raising=False)
        monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
        monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
        return local_mod

    def test_custom_robo_home_git_is_used(self, windows_local, tmp_path, monkeypatch):
        home = tmp_path / "D" / "RoboData"
        bash = _touch(home / "git" / "bin" / "bash.exe")
        monkeypatch.setenv("ROBO_HOME", str(home))

        assert windows_local._find_bash() == str(bash)

    def test_custom_robo_home_git_comes_before_localappdata_git(self, windows_local, tmp_path, monkeypatch):
        home = tmp_path / "D" / "RoboData"
        bash = _touch(home / "git" / "bin" / "bash.exe")
        _touch(tmp_path / "lad" / "robo" / "git" / "bin" / "bash.exe")
        monkeypatch.setenv("ROBO_HOME", str(home))

        assert windows_local._find_bash() == str(bash)

    def test_localappdata_git_still_found_without_robo_home_git(self, windows_local, tmp_path, monkeypatch):
        monkeypatch.setenv("ROBO_HOME", str(tmp_path / "home-without-git"))
        bash = _touch(tmp_path / "lad" / "robo" / "git" / "bin" / "bash.exe")

        assert windows_local._find_bash() == str(bash)

    def test_mingit_layout_under_robo_home(self, windows_local, tmp_path, monkeypatch):
        home = tmp_path / "RoboData"
        bash = _touch(home / "git" / "usr" / "bin" / "bash.exe")
        monkeypatch.setenv("ROBO_HOME", str(home))

        assert windows_local._find_bash() == str(bash)


class TestStartupPathFixup:
    @pytest.fixture
    def windows_stdio(self, tmp_path, monkeypatch):
        from robo_cli import stdio

        monkeypatch.setattr(stdio, "is_windows", lambda: True)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
        monkeypatch.setenv("PATH", "/existing")
        return stdio

    def test_robo_home_git_dirs_are_prepended(self, windows_stdio, tmp_path, monkeypatch):
        home = tmp_path / "RoboData"
        for sub in ("cmd", "bin"):
            (home / "git" / sub).mkdir(parents=True)
        monkeypatch.setenv("ROBO_HOME", str(home))

        windows_stdio._augment_path_with_known_tools()

        assert os.environ["PATH"].split(os.pathsep) == [
            str(home / "git" / "cmd"),
            str(home / "git" / "bin"),
            "/existing",
        ]

    def test_default_home_is_not_added_twice(self, windows_stdio, tmp_path, monkeypatch):
        home = tmp_path / "lad" / "robo"
        (home / "git" / "cmd").mkdir(parents=True)
        monkeypatch.setenv("ROBO_HOME", str(home))

        windows_stdio._augment_path_with_known_tools()

        entries = os.environ["PATH"].split(os.pathsep)
        assert entries.count(str(home / "git" / "cmd")) == 1
        assert entries[-1] == "/existing"

    def test_no_git_folders_leaves_path_alone(self, windows_stdio, tmp_path, monkeypatch):
        monkeypatch.setenv("ROBO_HOME", str(tmp_path / "RoboData"))

        windows_stdio._augment_path_with_known_tools()

        assert os.environ["PATH"] == "/existing"
