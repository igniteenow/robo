"""``robo snapshot`` — the terminal route to quick state snapshots.

``/snapshot restore`` is blocked inside the TUI and the desktop app (it
rewrites config/state on disk under a live agent), so the terminal needs its
own way to restore. ``robo snapshot`` and the ``/snapshot`` slash command
share one implementation (``robo_cli.backup.snapshot_command``); these tests
drive the real parser, handler and snapshot files under a temp ROBO_HOME.
"""

from __future__ import annotations

import argparse

import pytest

from robo_cli import main as m
from robo_cli.subcommands.snapshot import build_snapshot_parser


@pytest.fixture
def robo_home(tmp_path, monkeypatch):
    home = tmp_path / ".robo"
    home.mkdir()
    monkeypatch.setenv("ROBO_HOME", str(home))
    (home / "config.yaml").write_text("model: original\n", encoding="utf-8")
    return home


def _run(argv):
    parser = argparse.ArgumentParser(prog="robo")
    subparsers = parser.add_subparsers(dest="command")
    build_snapshot_parser(subparsers, cmd_snapshot=m.cmd_snapshot)
    args = parser.parse_args(argv)
    args.func(args)


def test_create_list_restore_prune_round_trip(robo_home, capsys):
    _run(["snapshot", "create", "before", "the", "change"])
    out = capsys.readouterr().out
    assert "Snapshot created:" in out

    _run(["snapshot"])  # default action is list
    out = capsys.readouterr().out
    assert "before the change" in out

    (robo_home / "config.yaml").write_text("model: changed\n", encoding="utf-8")
    _run(["snapshot", "restore", "1"])
    out = capsys.readouterr().out
    assert "Restored state from:" in out
    assert (robo_home / "config.yaml").read_text(encoding="utf-8") == "model: original\n"

    _run(["snapshot", "prune", "0"])
    out = capsys.readouterr().out
    assert "Pruned 1 old snapshot(s)" in out


def test_restore_by_the_id_of_a_labelled_snapshot(robo_home, capsys):
    from robo_cli.backup import list_quick_snapshots

    _run(["snapshot", "create", "before", "edit"])
    snap_id = list_quick_snapshots()[0]["id"]
    assert " " in snap_id  # the label is part of the id
    capsys.readouterr()

    (robo_home / "config.yaml").write_text("model: changed\n", encoding="utf-8")
    _run(["snapshot", "restore", snap_id])  # one quoted shell argument
    assert f"Restored state from: {snap_id}" in capsys.readouterr().out
    assert (robo_home / "config.yaml").read_text(encoding="utf-8") == "model: original\n"


def test_usage_hints_name_the_terminal_command(robo_home, capsys):
    _run(["snapshot", "list"])
    assert "robo snapshot create [label]" in capsys.readouterr().out

    _run(["snapshot", "restore"])
    assert "Usage: robo snapshot restore <snapshot-id>" in capsys.readouterr().out


def test_unknown_action_is_rejected_by_the_parser(robo_home):
    with pytest.raises(SystemExit):
        _run(["snapshot", "explode"])


def test_restore_of_a_missing_snapshot_changes_nothing(robo_home, capsys):
    _run(["snapshot", "restore", "20990101-000000"])
    assert "Snapshot not found" in capsys.readouterr().out
    assert (robo_home / "config.yaml").read_text(encoding="utf-8") == "model: original\n"


def test_slash_command_keeps_its_own_wording(robo_home, capsys):
    from robo_cli.cli_commands_mixin import CLICommandsMixin

    CLICommandsMixin._handle_snapshot_command(object(), "/snapshot")
    assert "Create one: /snapshot create [label]" in capsys.readouterr().out

    CLICommandsMixin._handle_snapshot_command(object(), "/snapshot create from slash")
    assert "Snapshot created:" in capsys.readouterr().out

    _run(["snapshot", "list"])
    assert "from slash" in capsys.readouterr().out


def test_quick_backup_points_at_the_terminal_restore(robo_home, capsys):
    from robo_cli.backup import run_quick_backup

    run_quick_backup(argparse.Namespace(label=None))
    out = capsys.readouterr().out
    assert "Restore with: robo snapshot restore " in out


def test_snapshot_is_a_known_builtin_subcommand():
    # Plugin discovery is skipped for built-ins; a missing entry would only
    # cost time, an entry without a parser would break plugin commands.
    assert "snapshot" in m._BUILTIN_SUBCOMMANDS


def test_session_names_containing_snapshot_still_resume():
    # `robo -c Nightly snapshot prune` resumes the session with that name; it
    # must not turn into `robo snapshot prune`.
    assert m._coalesce_session_name_args(["-c", "Nightly", "snapshot", "prune"]) == [
        "-c",
        "Nightly snapshot prune",
    ]
