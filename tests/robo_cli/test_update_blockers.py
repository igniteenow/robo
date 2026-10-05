"""``robo update`` offers to close what holds the install open (Windows).

Before: the update stopped with a list of process ids and told the user to
close things and try again. Now it names what is open, asks once, closes it
(the desktop app first, and reopens it afterwards) and carries on.

The process-stopping primitives are replaced by recorders throughout, so these
run the same on every platform and never stop a real process.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from robo_cli import main as cli_main
from robo_cli import update_blockers as ub
from robo_cli import update_cmd

DESKTOP = (11460, "python.exe", r"C:\robo\.venv\Scripts\python.exe -m robo_cli.main serve -p default")
WORKER = (5420, "python.exe", r"C:\robo\.robo-runtime\python\cpython-3.13\python.exe -m robo_cli.main serve")
PTY = (8388, "OpenConsole.exe", r"C:\robo\.venv\Lib\site-packages\winpty\OpenConsole.exe --headless")
CHAT = (4242, "robo.exe", r"C:\robo\.venv\Scripts\robo.exe")
DASH = (777, "python.exe", r"C:\robo\.venv\Scripts\python.exe -m robo_cli.main dashboard --port 9119")


class _Tty:
    """A stand-in for sys.stdin / sys.stdout that is, or is not, a terminal."""

    def __init__(self, tty: bool = True):
        self._tty = tty
        self.text = ""

    def isatty(self) -> bool:
        return self._tty

    def write(self, text: str) -> int:
        self.text += text
        return len(text)

    def flush(self) -> None:
        pass


class _World:
    """A fake process table: what is alive, who started whom, what was stopped."""

    def __init__(self, holders, *, desktop=None, parents=None, respawns=None, unstoppable=()):
        self.alive = {int(h[0]): h for h in holders}
        self.desktop = dict(desktop or {})  # pid -> mode
        self.parents = dict(parents or {})  # pid -> [ancestor pids] | None
        self.respawns = dict(respawns or {})  # stopped pid -> holder that comes back while the app lives
        self.unstoppable = set(unstoppable)
        self.calls: list[tuple] = []

    def redetect(self):
        return list(self.alive.values())

    def desktop_processes(self, _roots):
        return dict(self.desktop)

    def ancestor_pids(self, pid):
        return self.parents.get(int(pid), [])

    def kill_tree(self, pid):
        self.calls.append(("kill", int(pid)))
        if pid in self.unstoppable:
            return
        gone = {int(pid)} | {p for p, chain in self.parents.items() if chain and int(pid) in chain}
        for p in gone:
            self.alive.pop(p, None)
        if self.desktop and int(pid) in self.respawns:  # the app is still up: its backend returns
            back = self.respawns[int(pid)]
            self.alive[int(back[0])] = back

    def close_desktop(self, pids, **_kw):
        self.calls.append(("close-desktop", tuple(sorted(pids))))
        app = set(self.desktop)
        self.desktop.clear()
        for p, chain in list(self.parents.items()):
            if chain and app & set(chain):
                self.alive.pop(p, None)


@pytest.fixture
def world(monkeypatch):
    def install(w: _World, *, inside=False):
        monkeypatch.setattr(ub, "_desktop_roots", lambda _root: {"c:\\robo\\apps\\desktop\\release": "packaged"})
        monkeypatch.setattr(ub, "_desktop_processes", w.desktop_processes)
        monkeypatch.setattr(ub, "_ancestor_pids", w.ancestor_pids)
        monkeypatch.setattr(ub, "_inside_robo", lambda *_a: inside)
        monkeypatch.setattr(ub, "_kill_tree", w.kill_tree)
        monkeypatch.setattr(ub, "_close_desktop_app", w.close_desktop)
        return w

    return install


def _offer(w, args, *, answers=(), tty=True, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Tty(tty))
    monkeypatch.setattr(sys, "stdout", _Tty(tty))
    said: list[str] = []
    asked: list[str] = []
    replies = iter(answers)

    def input_fn(prompt):
        asked.append(prompt)
        reply = next(replies)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    outcome = ub.offer_to_close(
        w.redetect(),
        args,
        redetect=w.redetect,
        project_root="C:\\robo",
        venv_dir="C:\\robo\\.venv",
        out=said.append,
        input_fn=input_fn,
        sleep=lambda _s: None,
    )
    return outcome, "\n".join(said), asked


# ---------------------------------------------------------------------------
# What is in the way, in words
# ---------------------------------------------------------------------------


def test_the_desktop_app_and_everything_under_it_is_one_line():
    plan = ub.make_plan(
        [DESKTOP, WORKER, PTY, CHAT],
        desktop={900: "packaged", 901: "packaged"},
        ancestors_of={11460: [900], 5420: [11460, 900], 8388: [5420, 11460, 900], 4242: [1]}.get,
    )

    assert plan.desktop_pids == [900, 901]
    assert plan.desktop_mode == "packaged"
    assert plan.others == [CHAT]
    assert len(plan.lines) == 2
    assert "desktop app" in plan.lines[0] and "reopens" in plan.lines[0]
    assert "terminal session" in plan.lines[1] and "4242" in plan.lines[1]


def test_a_launcher_and_its_worker_are_listed_once():
    plan = ub.make_plan([DASH, WORKER, PTY], desktop={}, ancestors_of={5420: [777], 8388: [5420, 777]}.get)

    assert plan.desktop_pids == []
    assert plan.others == [DASH]
    assert plan.lines == [ub.describe_holder(DASH)]


def test_a_desktop_app_that_owns_none_of_the_holders_is_left_alone():
    plan = ub.make_plan([CHAT], desktop={900: "source"}, ancestors_of=lambda _pid: [1])

    assert plan.desktop_pids == []
    assert plan.desktop_mode is None


@pytest.mark.parametrize(
    ("holder", "words"),
    [
        (DASH, "dashboard"),
        (CHAT, "terminal session"),
        (PTY, "terminal opened by Robo"),
        ((9, "pythonw.exe", "pythonw.exe -m robo_cli.main gateway run"), "messaging gateway"),
        ((10, "node.exe", "node.exe server.js"), "another program"),
    ],
)
def test_each_holder_is_named_the_way_a_person_would_name_it(holder, words):
    line = ub.describe_holder(holder)

    assert words in line
    assert f"PID {holder[0]}" in line


# ---------------------------------------------------------------------------
# Asking, and closing on a yes
# ---------------------------------------------------------------------------


def test_enter_closes_the_app_first_then_the_rest_and_asks_only_once(world, monkeypatch):
    w = world(
        _World(
            [DESKTOP, WORKER, PTY, CHAT],
            desktop={900: "packaged"},
            parents={11460: [900], 5420: [11460, 900], 8388: [5420, 11460, 900], 4242: [1]},
        )
    )

    outcome, said, asked = _offer(w, SimpleNamespace(yes=False), answers=[""], monkeypatch=monkeypatch)

    assert asked == ["Close them and continue the update? [Y/n] "]
    assert w.calls == [("close-desktop", (900,)), ("kill", 4242)]
    assert outcome.remaining == []
    assert outcome.reopen_desktop == "packaged"
    assert outcome.closed_others is True
    assert "the Robo desktop app" in said and "terminal session (PID 4242)" in said
    assert "Nothing else is using this install" in said
    # The backend's own pids are the app's business, not the user's.
    assert "11460" not in said and "5420" not in said


@pytest.mark.parametrize("answer", ["n", "no", "N", "later", EOFError(), KeyboardInterrupt()])
def test_anything_but_yes_closes_nothing(world, monkeypatch, answer):
    w = world(_World([DASH, CHAT]))

    outcome, _said, asked = _offer(w, SimpleNamespace(yes=False), answers=[answer], monkeypatch=monkeypatch)

    assert len(asked) == 1
    assert w.calls == []
    assert outcome.declined is True
    assert outcome.remaining == [DASH, CHAT]
    assert outcome.reopen_desktop is None


def test_yes_flag_answers_for_the_user(world, monkeypatch):
    w = world(_World([DASH]))

    outcome, said, asked = _offer(w, SimpleNamespace(yes=True), tty=False, monkeypatch=monkeypatch)

    assert asked == []
    assert w.calls == [("kill", 777)]
    assert outcome.remaining == []
    assert "--yes" in said


def test_nobody_to_ask_and_no_yes_flag_touches_nothing(world, monkeypatch):
    w = world(_World([DASH, CHAT]))

    outcome, said, asked = _offer(w, SimpleNamespace(yes=False), tty=False, monkeypatch=monkeypatch)

    assert (asked, said, w.calls) == ([], "", [])
    assert outcome.asked is False and outcome.declined is False
    assert outcome.remaining == [DASH, CHAT]
    assert ub.can_offer(SimpleNamespace(yes=False)) is False
    assert ub.can_offer(SimpleNamespace(yes=True)) is True


def test_an_update_started_inside_robo_never_closes_what_it_runs_in(world, monkeypatch):
    w = world(_World([DESKTOP], desktop={900: "packaged"}, parents={11460: [900]}), inside=True)

    outcome, said, asked = _offer(w, SimpleNamespace(yes=True), monkeypatch=monkeypatch)

    assert (asked, said, w.calls) == ([], "", [])
    assert outcome.inside_robo is True
    assert outcome.remaining == [DESKTOP]


def test_a_backend_that_comes_back_gets_its_app_closed(world, monkeypatch):
    """The process tree could not be read, so the backend looked like a lone
    dashboard. Stopping it only makes the desktop app start a new one: the
    second look closes the app itself, and the app is reopened afterwards."""
    reborn = (12000, "python.exe", DESKTOP[2])
    w = world(
        _World(
            [DESKTOP],
            desktop={900: "source"},
            parents={11460: None, 12000: [900]},
            respawns={11460: reborn},
        )
    )

    outcome, _said, _asked = _offer(w, SimpleNamespace(yes=True), monkeypatch=monkeypatch)

    assert w.calls == [("kill", 11460), ("close-desktop", (900,))]
    assert outcome.remaining == []
    assert outcome.reopen_desktop == "source"


def test_what_cannot_be_stopped_is_reported_back_after_a_few_tries(world, monkeypatch):
    w = world(_World([DASH, CHAT], unstoppable={777}))

    outcome, said, _asked = _offer(w, SimpleNamespace(yes=False), answers=["y"], monkeypatch=monkeypatch)

    assert outcome.remaining == [DASH]
    assert w.calls.count(("kill", 777)) == ub.CLOSE_ROUNDS
    assert "Nothing else is using this install" not in said


def test_a_failure_inside_falls_back_to_the_plain_refusal(world, monkeypatch):
    w = world(_World([DASH]))
    monkeypatch.setattr(ub, "_desktop_roots", lambda _root: (_ for _ in ()).throw(RuntimeError("boom")))

    outcome, _said, _asked = _offer(w, SimpleNamespace(yes=True), monkeypatch=monkeypatch)

    assert outcome.remaining == [DASH]
    assert w.calls == []


# ---------------------------------------------------------------------------
# Never close the window the update itself runs in
# ---------------------------------------------------------------------------

_ROOT = os.path.join(os.sep, "robo")
_VENV = os.path.join(_ROOT, ".venv")
_RELEASE = os.path.join(_ROOT, "apps", "desktop", "release")
_VENV_PYTHON = (os.path.join(_VENV, "Scripts", "python.exe"), "python.exe -m robo_cli.main update")
_SHIM = (os.path.join(_VENV, "Scripts", "robo.exe"), "robo.exe update")
_SHELL = (os.path.join(os.sep, "windows", "system32", "windowspowershell", "powershell.exe"), "powershell.exe")
_EXPLORER = (os.path.join(os.sep, "windows", "explorer.exe"), "explorer.exe")
_BASE = os.path.join(_ROOT, ".robo-runtime", "python", "python.exe")
_UPDATE_WINDOW = (
    os.path.join(_ROOT, ".robo-runtime", "python", "pythonw.exe"),
    "pythonw.exe -i -s " + os.path.join(_ROOT, "robo_cli", "update_window.py") + " --reopen packaged",
)


@pytest.mark.parametrize(
    ("ancestors", "inside", "why"),
    [
        ([], False, "handed off to its own window: the launcher is gone"),
        ([_VENV_PYTHON, _SHIM, _SHELL, _EXPLORER], False, "robo update typed into PowerShell"),
        ([_VENV_PYTHON, _SHELL], False, "python -m robo_cli.main update typed into PowerShell"),
        ([_VENV_PYTHON, _UPDATE_WINDOW], False, "the desktop's own update window"),
        (
            [_VENV_PYTHON, _SHIM, _SHELL, (_BASE, "python.exe -m robo_cli.main serve"), (os.path.join(_RELEASE, "win-unpacked", "robo.exe"), "robo.exe")],
            True,
            "typed into the desktop app's terminal",
        ),
        (
            [_VENV_PYTHON, _SHIM, _SHELL, (os.path.join(os.sep, "robo-node", "node.exe"), "node.exe entry.js"), (_BASE, "python.exe -m robo_cli.main")],
            True,
            "run from a chat's shell",
        ),
        ([_VENV_PYTHON, _SHIM, _SHELL, (os.path.join(_RELEASE, "win-unpacked", "robo.exe"), "")], True, "under the app, command lines unreadable"),
        ([_VENV_PYTHON, _SHIM, _SHELL, _SHIM], True, "a second robo.exe further up is a session, not the launcher"),
    ],
)
def test_an_update_knows_when_it_runs_inside_robo(ancestors, inside, why):
    assert ub.nested_in_robo(ancestors, _VENV, [_RELEASE]) is inside, why


def test_the_process_primitives_do_nothing_off_windows():
    """The platform check alone must keep them from touching anything.

    conftest swaps the two stoppers for no-ops in every test, so the real ones
    are taken from a second, private copy of the module.
    """
    if sys.platform == "win32":
        pytest.skip("this is the guard for every other platform")
    import importlib.util

    spec = importlib.util.spec_from_file_location("update_blockers_real", ub.__file__)
    real = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = real
    try:
        spec.loader.exec_module(real)
        with patch("subprocess.run") as run, patch("gateway.status.terminate_pid") as terminate:
            real._kill_tree(1)
            real._close_desktop_app([1, 2], sleep=lambda _s: None)
        run.assert_not_called()
        terminate.assert_not_called()
        assert real._desktop_processes({"x": "packaged"}) == {}
        assert real._ancestor_pids(1) is None
        assert real._inside_robo("x", ["y"]) is False
    finally:
        sys.modules.pop(spec.name, None)


# ---------------------------------------------------------------------------
# robo update: the two guards
# ---------------------------------------------------------------------------


def _update_args(**overrides):
    defaults = dict(gateway=False, check=False, no_backup=True, backup=False, yes=False, branch=None, force=False, force_venv=False)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _run_update_to_the_guards(args, *, holders, concurrent=(), still_running=(), outcome=None, offered=None):
    """Drive ``_cmd_update_impl`` through the two Windows guards only.

    The first statement after them is ``PROJECT_ROOT / ".git"``; a
    ``PROJECT_ROOT`` whose ``/`` raises marks "past the guards".
    """

    class _PastGuards(Exception):
        pass

    class _Root:
        def __truediv__(self, _other):
            raise _PastGuards

    # What the robo.exe scan finds: before anything is closed, then afterwards.
    shim_scans = [list(concurrent), list(still_running)]

    def fake_offer(found, _args, **_kw):
        if offered is not None:
            offered.append(list(found))
        return outcome if outcome is not None else ub.CloseOutcome(remaining=list(found))

    with patch.object(cli_main, "_is_windows", return_value=True), patch.object(
        cli_main, "_venv_scripts_dir", return_value=Path("scripts")
    ), patch.object(cli_main, "_detect_concurrent_robo_instances", side_effect=shim_scans), patch.object(
        cli_main, "_run_pre_update_backup"
    ), patch.object(cli_main, "_pause_windows_gateways_for_update", return_value=None), patch.object(
        cli_main, "_resume_windows_gateways_after_update"
    ) as resume, patch.object(cli_main, "_detect_venv_python_processes", return_value=list(holders)), patch.object(
        ub, "offer_to_close", side_effect=fake_offer
    ), patch.object(cli_main, "PROJECT_ROOT", _Root()):
        try:
            cli_main._cmd_update_impl(args, gateway_mode=False)
        except _PastGuards:
            return "past", resume
        except SystemExit as exc:
            return f"exit_{exc.code}", resume
    return "returned", resume


def test_update_goes_on_once_everything_is_closed_and_remembers_the_app(capsys):
    args = _update_args()
    offered: list = []

    result, resume = _run_update_to_the_guards(
        args,
        holders=[DESKTOP, CHAT],
        outcome=ub.CloseOutcome(remaining=[], asked=True, reopen_desktop="packaged", closed_others=True),
        offered=offered,
    )

    assert result == "past", capsys.readouterr().out
    assert offered == [[DESKTOP, CHAT]]
    assert args.reopen_desktop == "packaged"
    assert args.reopen_desktop_closed_here is True
    assert args.closed_for_update is True
    resume.assert_not_called()


def test_a_no_cancels_the_update_without_the_wall_of_pids(capsys):
    result, resume = _run_update_to_the_guards(
        _update_args(),
        holders=[CHAT],
        outcome=ub.CloseOutcome(remaining=[CHAT], asked=True, declined=True),
    )

    out = capsys.readouterr().out
    assert result == "exit_2"
    assert "Update cancelled: nothing was closed." in out
    assert "PID 4242" not in out
    resume.assert_called_once()


def test_what_is_left_after_closing_is_still_refused(capsys):
    result, _resume = _run_update_to_the_guards(
        _update_args(yes=True), holders=[DASH], outcome=ub.CloseOutcome(remaining=[DASH], asked=True)
    )

    out = capsys.readouterr().out
    assert result == "exit_2"
    assert "Some of them could not be closed." in out
    assert "PID 777" in out
    assert "robo update --yes" not in out


def test_without_anyone_to_ask_the_refusal_says_how_to_let_robo_close_them(capsys):
    result, _resume = _run_update_to_the_guards(_update_args(), holders=[DASH])

    out = capsys.readouterr().out
    assert result == "exit_2"
    assert "PID 777" in out
    assert "robo update --yes" in out


def test_inside_robo_the_refusal_says_where_to_run_the_update_instead(capsys):
    result, _resume = _run_update_to_the_guards(
        _update_args(yes=True), holders=[DESKTOP], outcome=ub.CloseOutcome(remaining=[DESKTOP], inside_robo=True)
    )

    out = capsys.readouterr().out
    assert result == "exit_2"
    assert "started from inside Robo" in out
    assert "robo update --yes" not in out


def test_the_app_the_desktop_itself_asked_to_reopen_is_not_overridden():
    args = _update_args(yes=True, reopen_desktop="source")

    _run_update_to_the_guards(
        args, holders=[DESKTOP], outcome=ub.CloseOutcome(remaining=[], asked=True, reopen_desktop="packaged")
    )

    assert args.reopen_desktop == "source"
    assert not getattr(args, "reopen_desktop_closed_here", False)


@pytest.mark.parametrize(
    ("args", "tty", "expected"),
    [
        (dict(), True, "past"),  # someone can answer: one question further down covers these too
        (dict(yes=True), False, "past"),
        (dict(), False, "exit_2"),  # nobody to ask: stop here, as before
        (dict(yes=True, force_venv=True), False, "exit_2"),  # the venv guard is off: nothing would close them
    ],
)
def test_another_robo_exe_no_longer_ends_the_update_when_it_can_be_closed(monkeypatch, args, tty, expected):
    monkeypatch.setattr(sys, "stdin", _Tty(tty))
    monkeypatch.setattr(sys, "stdout", _Tty(tty))

    result, _resume = _run_update_to_the_guards(
        _update_args(**args),
        holders=[] if expected == "exit_2" else [CHAT],
        concurrent=[(4242, "robo.exe")],
        outcome=ub.CloseOutcome(remaining=[], asked=True, closed_others=True),
    )

    assert result == expected
    out = sys.stdout.text
    if expected == "exit_2":
        assert "Another robo.exe is running" in out
        # The hint is only given where it would work.
        assert ("robo update --yes" in out) is (not args.get("yes"))


def test_a_robo_exe_that_survives_the_closing_still_stops_the_update(monkeypatch):
    """The first check was left to the question further down. Whatever that
    did, a robo.exe still running afterwards locks the launcher the update
    replaces: the first check has the last word."""
    monkeypatch.setattr(sys, "stdin", _Tty())
    monkeypatch.setattr(sys, "stdout", _Tty())

    result, resume = _run_update_to_the_guards(
        _update_args(),
        holders=[CHAT],
        concurrent=[(4242, "robo.exe")],
        still_running=[(4242, "robo.exe")],
        outcome=ub.CloseOutcome(remaining=[], asked=True, closed_others=True),
    )

    assert result == "exit_2"
    assert "Another robo.exe is running" in sys.stdout.text
    resume.assert_called_once()


# ---------------------------------------------------------------------------
# After the update: put the app back
# ---------------------------------------------------------------------------


def _closed_here(**extra):
    def impl(args, gateway_mode=False):
        args.reopen_desktop = "packaged"
        args.reopen_desktop_closed_here = True
        for key, value in extra.items():
            setattr(args, key, value)

    return impl


def test_the_app_this_update_closed_is_reopened_in_the_users_own_terminal(monkeypatch):
    monkeypatch.delenv(update_cmd.UPDATE_HANDOFF_ENV, raising=False)
    monkeypatch.setattr(cli_main.sys, "stdin", None)
    with patch.object(cli_main, "_cmd_update_impl", side_effect=_closed_here()), patch.object(
        update_cmd, "_reopen_desktop_after_update"
    ) as reopen:
        cli_main.cmd_update(SimpleNamespace())

    reopen.assert_called_once_with("packaged", succeeded=True, owns_window=False)


def test_in_the_updates_own_window_the_window_closes_after_reopening(monkeypatch):
    monkeypatch.setenv(update_cmd.UPDATE_HANDOFF_ENV, "4242")
    monkeypatch.setattr(cli_main.sys, "stdin", None)
    with patch.object(cli_main, "_cmd_update_impl", side_effect=_closed_here()), patch.object(
        update_cmd, "_wait_for_handoff_launcher"
    ), patch.object(update_cmd, "_reopen_desktop_after_update") as reopen:
        cli_main.cmd_update(SimpleNamespace())

    reopen.assert_called_once_with("packaged", succeeded=True, owns_window=True)


def test_a_failed_update_says_the_app_was_not_reopened(monkeypatch):
    monkeypatch.delenv(update_cmd.UPDATE_HANDOFF_ENV, raising=False)
    monkeypatch.setattr(cli_main.sys, "stdin", None)

    def impl(args, gateway_mode=False):
        _closed_here()(args)
        raise SystemExit(1)

    with patch.object(cli_main, "_cmd_update_impl", side_effect=impl), patch.object(
        update_cmd, "_reopen_desktop_after_update"
    ) as reopen:
        with pytest.raises(SystemExit):
            cli_main.cmd_update(SimpleNamespace())

    reopen.assert_called_once_with("packaged", succeeded=False, owns_window=False)


def test_other_windows_the_update_closed_are_named_as_staying_closed(monkeypatch, capsys):
    monkeypatch.delenv(update_cmd.UPDATE_HANDOFF_ENV, raising=False)
    monkeypatch.setattr(cli_main.sys, "stdin", None)

    def impl(args, gateway_mode=False):
        args.closed_for_update = True

    with patch.object(cli_main, "_cmd_update_impl", side_effect=impl), patch.object(
        update_cmd, "_reopen_desktop_after_update"
    ) as reopen:
        cli_main.cmd_update(SimpleNamespace())

    assert "closed for this update stay closed" in capsys.readouterr().out
    reopen.assert_not_called()


def test_the_users_own_terminal_is_not_told_it_will_close(monkeypatch, capsys):
    monkeypatch.setattr(update_cmd.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(update_cmd._time, "sleep", lambda _s: (_ for _ in ()).throw(AssertionError("must not wait")))
    monkeypatch.setattr(update_cmd.sys, "stdout", _Tty())

    update_cmd._reopen_desktop_after_update("packaged", succeeded=True, owns_window=False)

    assert "This window closes" not in update_cmd.sys.stdout.text
    assert "Reopening Robo" in update_cmd.sys.stdout.text

