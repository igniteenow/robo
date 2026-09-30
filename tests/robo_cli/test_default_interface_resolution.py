"""Tests for which interface a chat launch gets.

Every interactive launch opens the terminal app (the Ink TUI): plain
``robo``, ``robo chat``, ``robo --cli`` and a leftover
``display.interface: cli`` all land there. What stays headless:

    --cli with -q/--image   one answer, no UI (kanban workers run this)
    (no TTY)                pipes, cron and scripts — never the TUI
    --tui                   forces the TUI, even without a TTY

The no-TTY gate exists because the TUI's no-TTY bail-out exits 0 without
doing the work: a kanban worker then dies with "protocol violation" on
every attempt.

These tests pin that at every layer that makes the decision:

  * ``_resolve_use_tui(args)``  — the args-aware resolver used by
    ``cmd_chat`` and the Termux fast-TUI path.
  * ``_wants_tui_early(argv)``  — the dependency-free early resolver used by
    mouse-residue suppression and the Termux fast paths, before argparse and
    ``robo_cli.config`` are importable.
  * ``cmd_chat``                — ``robo --cli`` really reaches the TUI
    launcher, and ``robo --cli chat -q`` really reaches the one-shot path.
  * the argument parser   — both ``--cli`` and ``--tui`` parse at the top
    level and under the ``chat`` subcommand and are relaunch-inherited.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from robo_cli import main as m


@pytest.fixture(autouse=True, params=[None, "1"], ids=["no-ROBO_TUI", "ROBO_TUI=1"])
def ambient_tui_env(request, monkeypatch):
    """Run every test with and without ``ROBO_TUI=1``.

    The ``robo`` launcher (robo_runtime/bootstrap.py) sets ``ROBO_TUI=1`` on
    every launch — kanban workers included, after the dispatcher drops it —
    so the decisions below must hold with it set, not only in a clean env.
    """
    if request.param is None:
        monkeypatch.delenv("ROBO_TUI", raising=False)
    else:
        monkeypatch.setenv("ROBO_TUI", request.param)
    return request.param


def _args(**kw):
    kw.setdefault("cli", False)
    kw.setdefault("tui", False)
    return SimpleNamespace(**kw)


def _fake_tty(monkeypatch, interactive: bool):
    """Pin stdin/stdout TTY-ness — pytest's capture is never a real TTY."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: interactive, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: interactive, raising=False)


def _parse(argv):
    from robo_cli._parser import build_top_level_parser

    parser, _subparsers, _chat = build_top_level_parser()
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# _resolve_use_tui — args-aware resolver
# ---------------------------------------------------------------------------
class TestResolveUseTui:
    def test_interactive_cli_flag_opens_the_tui(self, monkeypatch):
        _fake_tty(monkeypatch, True)
        assert m._resolve_use_tui(_parse(["--cli"])) is True
        assert m._resolve_use_tui(_parse(["chat", "--cli"])) is True

    def test_bare_launch_opens_the_tui(self, monkeypatch):
        _fake_tty(monkeypatch, True)
        assert m._resolve_use_tui(_parse([])) is True
        assert m._resolve_use_tui(_parse(["chat"])) is True

    def test_config_interface_cli_is_not_consulted(self, monkeypatch):
        import robo_cli.config as cfg

        def _must_not_load():
            raise AssertionError("the launch decision must not depend on config")

        monkeypatch.setattr(cfg, "load_config", _must_not_load)
        _fake_tty(monkeypatch, True)
        assert m._resolve_use_tui(_args()) is True

    @pytest.mark.parametrize(
        "argv",
        [
            ["--cli", "chat", "-q", "hi"],
            ["--cli", "chat", "--query", "hi"],
            ["chat", "--cli", "-q", "hi"],
            ["--cli", "--accept-hooks", "--skills", "x", "chat", "-q", "hi"],
        ],
    )
    def test_cli_flag_with_a_question_stays_headless_in_a_terminal(self, monkeypatch, argv):
        _fake_tty(monkeypatch, True)
        assert m._resolve_use_tui(_parse(argv)) is False

    def test_cli_flag_with_an_image_stays_headless(self, monkeypatch):
        _fake_tty(monkeypatch, True)
        assert m._resolve_use_tui(_args(cli=True, image="cat.png")) is False

    def test_question_without_cli_flag_keeps_its_tui_behaviour(self, monkeypatch):
        # `robo chat -q` in a terminal hands the question to the TUI, as before.
        _fake_tty(monkeypatch, True)
        assert m._resolve_use_tui(_parse(["chat", "-q", "hi"])) is True

    # ── the no-TTY gate: nothing ambient ever boots the TUI headless ────────

    @pytest.mark.parametrize(
        "argv", [[], ["--cli"], ["--cli", "--tui"], ["chat", "-q", "hi"], ["--cli", "chat", "-q", "hi"]]
    )
    def test_no_tty_stays_headless(self, monkeypatch, argv):
        _fake_tty(monkeypatch, False)
        assert m._resolve_use_tui(_parse(argv)) is False

    def test_cli_flag_with_an_empty_question_stays_headless(self, monkeypatch):
        _fake_tty(monkeypatch, True)
        assert m._resolve_use_tui(_parse(["--cli", "chat", "-q", ""])) is False

    def test_env_var_does_not_beat_the_tty_gate(self, monkeypatch):
        _fake_tty(monkeypatch, False)
        monkeypatch.setenv("ROBO_TUI", "1")
        assert m._resolve_use_tui(_args()) is False
        assert m._resolve_use_tui(_args(cli=True)) is False

    def test_explicit_tui_flag_without_tty_still_reaches_the_tui(self, monkeypatch):
        _fake_tty(monkeypatch, False)
        assert m._resolve_use_tui(_args(tui=True)) is True


# ---------------------------------------------------------------------------
# _wants_tui_early — dependency-free early resolver
# ---------------------------------------------------------------------------
class TestWantsTuiEarly:
    @pytest.mark.parametrize("argv", [[], ["--cli"], ["chat", "--cli"], ["--cli", "-c"], ["-c"]])
    def test_interactive_launches_are_the_tui(self, monkeypatch, argv):
        _fake_tty(monkeypatch, True)
        assert m._wants_tui_early(argv) is True

    def test_config_interface_cli_does_not_matter(self, tmp_path, monkeypatch):
        (tmp_path / "config.yaml").write_text("display:\n  interface: cli\n")
        monkeypatch.setenv("ROBO_HOME", str(tmp_path))
        _fake_tty(monkeypatch, True)
        assert m._wants_tui_early([]) is True

    @pytest.mark.parametrize(
        "argv",
        [
            ["--cli", "chat", "-q", "hi"],
            ["--cli", "chat", "--query=hi"],
            ["--cli", "chat", "-qhi"],
            ["--cli", "chat", "--image", "cat.png"],
            ["--cli", "-z", "hi"],
        ],
    )
    def test_cli_flag_with_a_question_stays_headless(self, monkeypatch, argv):
        _fake_tty(monkeypatch, True)
        assert m._wants_tui_early(argv) is False

    @pytest.mark.parametrize(
        "argv", [["--cli"], ["--cli", "--tui"], ["--cli", "chat", "-q", "hi"]]
    )
    def test_cli_flag_without_tty_stays_headless(self, monkeypatch, argv):
        _fake_tty(monkeypatch, False)
        assert m._wants_tui_early(argv) is False

    @pytest.mark.parametrize("argv", [[], ["chat", "-q", "hi"]])
    def test_without_cli_flag_the_no_tty_answer_is_unchanged(
        self, monkeypatch, ambient_tui_env, argv
    ):
        # As before this change: ROBO_TUI=1 answers early (only mouse-residue
        # suppression and Termux routing read this), else the TTY decides.
        _fake_tty(monkeypatch, False)
        assert m._wants_tui_early(argv) is (ambient_tui_env == "1")

    def test_explicit_tui_wins_without_tty(self, monkeypatch):
        _fake_tty(monkeypatch, False)
        assert m._wants_tui_early(["--tui"]) is True


# ---------------------------------------------------------------------------
# The real kanban worker command line stays headless even from a terminal
# ---------------------------------------------------------------------------
def test_kanban_worker_argv_never_opens_the_tui(tmp_path, monkeypatch):
    from robo_cli import kanban_db as kb

    home = tmp_path / ".robo"
    home.mkdir()
    monkeypatch.setenv("ROBO_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    conn = kb.connect()
    try:
        tid = kb.create_task(conn, title="t", assignee="elias")
        task = kb.get_task(conn, tid)
    finally:
        conn.close()

    monkeypatch.setattr(kb, "_resolve_robo_argv", lambda: ["robo"])
    captured = {}

    class _FakeProc:
        pid = 4245

    def _fake_popen(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        return _FakeProc()

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    kb._default_spawn(task, str(workspace))

    argv = captured["cmd"][1:]
    # `-p <profile>` is consumed by _apply_profile_override before argparse.
    i = argv.index("-p")
    parse_argv = argv[:i] + argv[i + 2:]

    # The launcher re-adds ROBO_TUI=1 after the dispatcher drops it, and the
    # worker's stdio might even be a terminal: still no TUI.
    monkeypatch.setenv("ROBO_TUI", "1")
    for interactive in (False, True):
        _fake_tty(monkeypatch, interactive)
        assert m._wants_tui_early(argv) is False
        assert m._resolve_use_tui(_parse(parse_argv)) is False


# ---------------------------------------------------------------------------
# cmd_chat — where the launch actually goes
# ---------------------------------------------------------------------------
class _Launched(Exception):
    pass


@pytest.fixture
def chat_env(monkeypatch):
    """cmd_chat with the slow/side-effecting startup steps stubbed out."""
    calls = {}
    monkeypatch.setattr(m, "_has_any_provider_configured", lambda: True)
    monkeypatch.setattr(m, "_termux_should_prefetch_update_check", lambda: False)
    monkeypatch.setattr(m, "_sync_bundled_skills_for_startup", lambda: None)
    monkeypatch.setattr(m, "_pin_kanban_board_env", lambda: None)

    def _fake_launch_tui(*args, **kwargs):
        calls["tui"] = kwargs
        raise _Launched("tui")

    def _fake_cli_main(**kwargs):
        calls["cli"] = kwargs
        raise _Launched("cli")

    monkeypatch.setattr(m, "_launch_tui", _fake_launch_tui)
    monkeypatch.setitem(sys.modules, "cli", types.SimpleNamespace(main=_fake_cli_main))
    return calls


def test_robo_cli_launches_the_tui_and_nothing_is_printed(chat_env, monkeypatch, capsys):
    _fake_tty(monkeypatch, True)
    with pytest.raises(_Launched, match="tui"):
        m.cmd_chat(_parse(["--cli"]))
    assert "tui" in chat_env and "cli" not in chat_env
    out, err = capsys.readouterr()
    assert out == "" and err == ""


def test_robo_cli_with_a_question_answers_once_without_a_ui(chat_env, monkeypatch):
    _fake_tty(monkeypatch, True)
    with pytest.raises(_Launched, match="cli"):
        m.cmd_chat(_parse(["--cli", "chat", "-q", "hello"]))
    assert "tui" not in chat_env
    assert chat_env["cli"]["query"] == "hello"


# ---------------------------------------------------------------------------
# argument parser — flags exist at both levels and are relaunch-inherited
# ---------------------------------------------------------------------------
class TestParserFlags:
    def test_top_level_cli_flag(self):
        args = _parse(["--cli"])
        assert args.cli is True and args.tui is False

    def test_chat_subcommand_cli_flag_with_query(self):
        args = _parse(["chat", "--cli", "-q", "hi"])
        assert args.cli is True and args.query == "hi"

    def test_chat_subcommand_tui_flag(self):
        args = _parse(["chat", "--tui"])
        assert args.tui is True

    def test_cli_and_tui_are_relaunch_inherited(self):
        from robo_cli.relaunch import _INHERITED_FLAGS_TABLE

        inherited = {flag for flag, _takes_value in _INHERITED_FLAGS_TABLE}
        assert "--cli" in inherited
        assert "--tui" in inherited


# ---------------------------------------------------------------------------
# config default — Robo ships the modern TUI as its default interface (the
# runtime bootstrap seeds the same value into a fresh ~/.robo/config.yaml)
# ---------------------------------------------------------------------------
def test_default_config_interface_is_tui():
    from robo_cli.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["display"]["interface"] == "tui"
