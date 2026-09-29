"""TUI launch on a Windows machine whose only Node is Robo's own.

The Windows installer keeps Node in <ROBO_HOME>\\node. A terminal opened
before the install has no Node on PATH, so the TUI must use the managed Node
instead of running the POSIX bash bootstrap, and --dev must run the tsx .cmd
shim (the extensionless shim next to it cannot be executed on Windows).
"""

import sys
import types
from pathlib import Path

import pytest

# These tests stand in for Windows on a POSIX host (they patch sys.platform
# and use POSIX file modes and shell shims); Linux CI runs them. On a real
# Windows machine the same behavior is checked by hand.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="simulates Windows on a POSIX host"
)


@pytest.fixture
def main_mod():
    import robo_cli.main as m

    return m


def _record_runs(main_mod, monkeypatch) -> list:
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(main_mod.subprocess, "run", fake_run)
    return calls


def _no_node_on_path(main_mod, monkeypatch) -> None:
    monkeypatch.delenv("ROBO_SKIP_NODE_BOOTSTRAP", raising=False)
    monkeypatch.setattr(main_mod.shutil, "which", lambda name, *a, **k: None)


class TestEnsureTuiNode:
    def test_windows_uses_managed_node_without_bash_bootstrap(self, main_mod, monkeypatch):
        import robo_constants

        _no_node_on_path(main_mod, monkeypatch)
        monkeypatch.setattr(main_mod.sys, "platform", "win32")
        monkeypatch.setattr(
            robo_constants, "find_node_executable", lambda cmd: rf"C:\robo\node\{cmd}.exe"
        )
        calls = _record_runs(main_mod, monkeypatch)

        main_mod._ensure_tui_node()

        assert calls == []

    def test_windows_without_any_node_still_tries_the_bootstrap(self, main_mod, monkeypatch):
        import robo_constants

        _no_node_on_path(main_mod, monkeypatch)
        monkeypatch.setenv("PATH", "")
        monkeypatch.setattr(main_mod.sys, "platform", "win32")
        monkeypatch.setattr(robo_constants, "find_node_executable", lambda cmd: None)
        calls = _record_runs(main_mod, monkeypatch)

        main_mod._ensure_tui_node()

        assert len(calls) == 1
        assert calls[0][0] == "bash"

    def test_posix_behaviour_is_unchanged(self, main_mod, monkeypatch):
        """Off Windows the bootstrap still runs when node is not on PATH,
        even if a managed Node exists (it is what puts it on PATH)."""
        import robo_constants

        _no_node_on_path(main_mod, monkeypatch)
        monkeypatch.setenv("PATH", "")
        monkeypatch.setattr(main_mod.sys, "platform", "linux")
        monkeypatch.setattr(robo_constants, "find_node_executable", lambda cmd: f"/x/{cmd}")
        calls = _record_runs(main_mod, monkeypatch)

        main_mod._ensure_tui_node()

        assert len(calls) == 1
        assert calls[0][0] == "bash"


def _dev_tui(tmp_path: Path) -> Path:
    tui_dir = tmp_path / "ui-tui"
    (tui_dir / "src").mkdir(parents=True)
    (tui_dir / "src" / "entry.tsx").write_text("export {}", encoding="utf-8")
    (tui_dir / "packages" / "robo-ink").mkdir(parents=True)
    bin_dir = tui_dir / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "tsx").write_text("#!/bin/sh\n", encoding="utf-8")
    (bin_dir / "tsx.cmd").write_text("@echo off\n", encoding="utf-8")
    return tui_dir


def _prepare_dev_launch(main_mod, monkeypatch) -> None:
    import robo_constants

    monkeypatch.delenv("ROBO_TUI_DIR", raising=False)
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.setattr(main_mod, "_ensure_tui_node", lambda: None)
    monkeypatch.setattr(main_mod, "_ensure_tui_workspace", lambda _d: None)
    monkeypatch.setattr(main_mod, "_tui_need_npm_install", lambda _root: False)
    monkeypatch.setattr(main_mod, "_is_termux_startup_environment", lambda: False)
    monkeypatch.setattr(robo_constants, "find_node_executable", lambda cmd: f"/bin/{cmd}")
    _record_runs(main_mod, monkeypatch)


class TestDevLaunch:
    def test_windows_runs_the_tsx_cmd_shim(self, tmp_path, main_mod, monkeypatch):
        tui_dir = _dev_tui(tmp_path)
        _prepare_dev_launch(main_mod, monkeypatch)
        monkeypatch.setattr(main_mod.sys, "platform", "win32")

        argv, cwd = main_mod._make_tui_argv(tui_dir, tui_dev=True)

        assert argv == [str(tui_dir / "node_modules" / ".bin" / "tsx.cmd"), "src/entry.tsx"]
        assert cwd == tui_dir

    def test_posix_runs_the_plain_tsx_shim(self, tmp_path, main_mod, monkeypatch):
        tui_dir = _dev_tui(tmp_path)
        _prepare_dev_launch(main_mod, monkeypatch)
        monkeypatch.setattr(main_mod.sys, "platform", "linux")

        argv, _cwd = main_mod._make_tui_argv(tui_dir, tui_dev=True)

        assert argv == [str(tui_dir / "node_modules" / ".bin" / "tsx"), "src/entry.tsx"]
