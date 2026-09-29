"""resolve_cli_command() and with_robo_node_path(append=True).

Both exist for machines whose only Node is the one Robo installed in
<ROBO_HOME>/node, which is not on every process's PATH.
"""

import os
import sys
from pathlib import Path

import pytest

from robo_constants import (
    find_robo_node_file,
    iter_robo_node_dirs,
    resolve_cli_command,
    with_robo_node_path,
)

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
def managed_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo-home"))
    directory = iter_robo_node_dirs()[0]
    directory.mkdir(parents=True)
    return directory


class TestResolveCliCommand:
    def test_path_hit_wins_over_managed_dir(self, tmp_path, managed_dir, monkeypatch):
        on_path = _exe(tmp_path / "path-bin" / "codex")
        _exe(managed_dir / "codex")
        monkeypatch.setenv("PATH", str(on_path.parent))

        assert resolve_cli_command("codex") == str(on_path)

    def test_windows_falls_back_to_robo_node_dir(self, tmp_path, monkeypatch):
        """npm i -g on Robo's Node puts copilot.cmd in <ROBO_HOME>\\node."""
        import robo_constants

        monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo-home"))
        monkeypatch.setattr(robo_constants.sys, "platform", "win32")
        node_dir = iter_robo_node_dirs()[0]
        shim = node_dir / "copilot.cmd"
        shim.parent.mkdir(parents=True)
        shim.write_text("@echo off\n", encoding="utf-8")
        searched = []

        def fake_which(cmd, mode=os.F_OK | os.X_OK, path=None):
            # Stand-in for Windows' PATHEXT lookup: nothing on PATH, and
            # "copilot" matches copilot.cmd in a directory we are handed.
            searched.append(path)
            if path is None:
                return None
            for directory in path.split(os.pathsep):
                candidate = Path(directory) / f"{cmd}.cmd"
                if candidate.is_file():
                    return str(candidate)
            return None

        monkeypatch.setattr(robo_constants.shutil, "which", fake_which)

        assert resolve_cli_command("copilot") == str(shim)
        assert searched[0] is None  # PATH was tried first
        assert str(node_dir) in searched[1].split(os.pathsep)

    def test_posix_does_not_look_outside_path(self, tmp_path, managed_dir, monkeypatch):
        """A POSIX npm shim needs node on PATH, so only PATH counts there."""
        _exe(managed_dir / "copilot")
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))

        assert resolve_cli_command("copilot") == "copilot"

    def test_unknown_command_is_returned_unchanged(self, tmp_path, managed_dir, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))

        assert resolve_cli_command("no-such-cli-xyz") == "no-such-cli-xyz"

    @pytest.mark.parametrize("command", ["/opt/tools/codex", "./codex", "bin/codex"])
    def test_command_with_a_directory_part_is_left_alone(self, command, managed_dir):
        _exe(managed_dir / "codex")

        assert resolve_cli_command(command) == command

    def test_empty_command_is_left_alone(self):
        assert resolve_cli_command("") == ""


class TestWithRoboNodePath:
    @staticmethod
    def _managed() -> list[str]:
        # Creating node/bin also creates node/, so both managed shapes exist.
        return [str(d) for d in iter_robo_node_dirs() if d.is_dir()]

    def test_default_prepends_managed_dirs(self, managed_dir):
        env = with_robo_node_path({"PATH": os.pathsep.join(["/a", "/b"])})

        assert env["PATH"].split(os.pathsep) == [*self._managed(), "/a", "/b"]

    def test_append_keeps_existing_order_and_adds_managed_last(self, managed_dir):
        env = with_robo_node_path({"PATH": os.pathsep.join(["/a", "/b"])}, append=True)

        assert env["PATH"].split(os.pathsep) == ["/a", "/b", *self._managed()]

    def test_append_does_not_duplicate_entries_already_on_path(self, managed_dir):
        original = os.pathsep.join([*self._managed(), "/a"])

        env = with_robo_node_path({"PATH": original}, append=True)

        assert env["PATH"] == original

    def test_missing_managed_dir_leaves_path_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ROBO_HOME", str(tmp_path / "no-node-here"))
        original = os.pathsep.join(["/a", "/b"])

        assert with_robo_node_path({"PATH": original}, append=True)["PATH"] == original
        assert with_robo_node_path({"PATH": original})["PATH"] == original

    def test_input_env_is_not_mutated_and_other_keys_survive(self, managed_dir):
        source = {"PATH": "/a", "KEEP": "1"}

        env = with_robo_node_path(source, append=True)

        assert source == {"PATH": "/a", "KEEP": "1"}
        assert env["KEEP"] == "1"


class TestFindRoboNodeFile:
    def test_windows_returns_only_launchable_forms(self, tmp_path, monkeypatch):
        import robo_constants

        monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo-home"))
        monkeypatch.setattr(robo_constants.sys, "platform", "win32")
        node_dir = iter_robo_node_dirs()[0]
        node_dir.mkdir(parents=True)
        (node_dir / "npm").write_text("#!/bin/sh\n", encoding="utf-8")
        assert find_robo_node_file("npm") is None

        npm_cmd = node_dir / "npm.cmd"
        npm_cmd.write_text("@echo off\n", encoding="utf-8")
        assert find_robo_node_file("npm") == str(npm_cmd)

    def test_posix_needs_the_executable_bit(self, managed_dir):
        npm = managed_dir / "npm"
        npm.write_text("#!/bin/sh\n", encoding="utf-8")
        npm.chmod(0o644)
        assert find_robo_node_file("npm") is None

        npm.chmod(0o755)
        assert find_robo_node_file("npm") == str(npm)

    def test_missing_tree(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ROBO_HOME", str(tmp_path / "nothing-here"))

        assert find_robo_node_file("node") is None
