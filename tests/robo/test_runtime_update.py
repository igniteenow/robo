"""`robo update` reaches the real updater.

The `robo` launcher used to answer `update` itself, with a note about release
packages that don't exist, and exit. An installed Robo could never update,
while the TUI kept telling people to run `robo update`.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import robo_runtime.cli as runtime_cli


def _run(monkeypatch, tmp_path: Path, argv: list[str]) -> list[list[str]]:
    """Run the launcher with *argv*; return the argv each hand-off saw."""
    seen: list[list[str]] = []
    core = types.ModuleType("robo_cli.main")
    core.main = lambda: seen.append(list(sys.argv[1:]))
    monkeypatch.setitem(sys.modules, "robo_cli.main", core)
    monkeypatch.setattr(runtime_cli, "activate_robo_home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["robo", *argv])
    # The launcher fills these in with setdefault; pin them so nothing leaks.
    for name, value in (
        ("ROBO_CLI_NAME", "robo"),
        ("ROBO_PRODUCT_NAME", "Robo"),
        ("ROBO_DESKTOP_APP_NAME", "Robo"),
        ("ROBO_WAKE_PHRASE_DISPLAY", "Hey Roh Boh"),
        ("ROBO_BIN", "robo"),
    ):
        monkeypatch.setenv(name, value)
    runtime_cli.main()
    return seen


def test_robo_update_runs_the_updater(monkeypatch, tmp_path, capsys):
    assert _run(monkeypatch, tmp_path, ["update"]) == [["update"]]
    assert "release package" not in capsys.readouterr().out


def test_robo_update_passes_its_flags_through(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, ["update", "--check"]) == [["update", "--check"]]


def test_robo_version_is_still_answered_by_the_launcher(monkeypatch, tmp_path, capsys):
    assert _run(monkeypatch, tmp_path, ["--version"]) == []
    assert capsys.readouterr().out.startswith("Robo ")
