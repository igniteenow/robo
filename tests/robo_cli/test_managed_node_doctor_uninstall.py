"""`robo doctor` npm audit with Robo's own Node, and the uninstaller's console setup."""

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
    path.chmod(0o755)
    return path


class TestNpmForAudit:
    @pytest.fixture
    def doctor(self, tmp_path, monkeypatch):
        from robo_cli import doctor

        monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo-home"))
        monkeypatch.setattr(doctor, "_safe_which", lambda cmd: None)
        return doctor

    def test_npm_on_path_wins(self, doctor, monkeypatch):
        monkeypatch.setattr(doctor, "_safe_which", lambda cmd: "/usr/bin/npm")

        assert doctor._npm_for_audit() == "/usr/bin/npm"

    def test_windows_finds_npm_cmd_in_robo_node(self, doctor, tmp_path, monkeypatch):
        monkeypatch.setattr(doctor.sys, "platform", "win32")
        node_dir = tmp_path / "robo-home" / "node"
        _touch(node_dir / "npm")  # extensionless POSIX shim: not runnable on Windows
        npm_cmd = _touch(node_dir / "npm.cmd")

        assert doctor._npm_for_audit() == str(npm_cmd)

    def test_posix_finds_npm_in_robo_node_bin(self, doctor, tmp_path, monkeypatch):
        monkeypatch.setattr(doctor.sys, "platform", "linux")
        npm = _touch(tmp_path / "robo-home" / "node" / "bin" / "npm")

        assert doctor._npm_for_audit() == str(npm)

    def test_none_when_there_is_no_npm(self, doctor):
        assert doctor._npm_for_audit() is None

    def test_never_downloads_or_runs_anything(self, doctor, tmp_path, monkeypatch):
        def boom(*_a, **_k):
            raise AssertionError("doctor's npm lookup must be a file check only")

        monkeypatch.setattr(doctor.subprocess, "run", boom)
        _touch(tmp_path / "robo-home" / "node" / "bin" / "npm")

        assert doctor._npm_for_audit() is not None


class TestUninstallConsole:
    def test_main_turns_on_vt_before_printing(self, monkeypatch):
        from robo_cli import stdio, uninstall

        order = []
        monkeypatch.setattr(stdio, "enable_windows_vt_mode", lambda: order.append("vt") or True)
        monkeypatch.setattr(uninstall, "run_gui_uninstall", lambda args: order.append("gui"))

        assert uninstall.main(["--mode", "gui"]) == 0
        assert order == ["vt", "gui"]

    def test_vt_failure_does_not_block_the_uninstall(self, monkeypatch):
        from robo_cli import stdio, uninstall

        def broken():
            raise OSError("no console")

        ran = []
        monkeypatch.setattr(stdio, "enable_windows_vt_mode", broken)
        monkeypatch.setattr(uninstall, "run_gui_uninstall", lambda args: ran.append(args))

        assert uninstall.main(["--mode", "gui"]) == 0
        assert len(ran) == 1

