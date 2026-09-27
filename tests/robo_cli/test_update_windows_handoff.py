"""Windows: a terminal `robo update` finishes in a new window.

`robo update` typed in a terminal runs under the venv's robo.exe launcher.
The dependency step reinstalls Robo, which must replace robo.exe, and Windows
refuses while the launcher runs. So the update restarts itself from the venv's
python in a new console window and the launcher exits.

On a real machine the launcher is not the direct parent of the running
interpreter: robo.exe starts the venv's python.exe, which is a redirector that
starts the real interpreter. The fakes below model that chain.

Everything Windows-specific is driven through fakes, so these run on any OS.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from robo_cli import main as cli_main
from robo_cli import update_cmd

pytestmark = pytest.mark.real_windows_update_helpers

NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)


class _FakeProc:
    def __init__(self, pid: int, exe: str = "", parent: "_FakeProc | None" = None):
        self.pid = pid
        self._exe = exe
        self._parent = parent

    def exe(self) -> str:
        return self._exe

    def parents(self) -> list["_FakeProc"]:
        chain = []
        proc = self._parent
        while proc is not None:
            chain.append(proc)
            proc = proc._parent
        return chain


class _GoneProc(_FakeProc):
    """An ancestor whose executable can no longer be read (exited, or access denied)."""

    def exe(self) -> str:
        raise PermissionError("access denied")


def _fake_psutil(procs: dict[int, _FakeProc], waited: list | None = None):
    def process(pid: int):
        if pid not in procs:
            raise ProcessLookupError(pid)
        return procs[pid]

    def wait_procs(items, timeout=None):
        if waited is not None:
            waited.append(([p.pid for p in items], timeout))
        return items, []

    return types.SimpleNamespace(Process=process, wait_procs=wait_procs)


def _scripts_dir(tmp_path: Path) -> Path:
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "robo.exe").write_bytes(b"")
    (scripts / "python.exe").write_bytes(b"")
    return scripts


def _terminal_chain(scripts: Path, *, via_tui: bool = False) -> _FakeProc:
    """shell → robo.exe → venv python.exe (redirector) → real interpreter (this process).

    ``via_tui`` puts the TUI's own robo.exe chain above it, as `/update` does.
    """
    top = _FakeProc(10, r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    if via_tui:
        tui_launcher = _FakeProc(20, str(scripts / "robo.exe"), parent=top)
        tui_redirector = _FakeProc(21, str(scripts / "python.exe"), parent=tui_launcher)
        top = _FakeProc(22, r"C:\Python312\python.exe", parent=tui_redirector)
    launcher = _FakeProc(100, str(scripts / "robo.exe"), parent=top)
    redirector = _FakeProc(101, str(scripts / "python.exe"), parent=launcher)
    return _FakeProc(os.getpid(), r"C:\Python312\python.exe", parent=redirector)


# ---------------------------------------------------------------------------
# Detecting the launcher
# ---------------------------------------------------------------------------


@patch.object(cli_main, "_is_windows", return_value=True)
def test_launcher_two_levels_up_is_detected(_win, tmp_path, monkeypatch):
    scripts = _scripts_dir(tmp_path)
    me = _terminal_chain(scripts)
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil({os.getpid(): me}))

    assert update_cmd._launchers_running_this_update(scripts) == [100]


@patch.object(cli_main, "_is_windows", return_value=True)
def test_update_from_the_tui_finds_both_launchers(_win, tmp_path, monkeypatch):
    scripts = _scripts_dir(tmp_path)
    me = _terminal_chain(scripts, via_tui=True)
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil({os.getpid(): me}))

    assert update_cmd._launchers_running_this_update(scripts) == [100, 20]


@patch.object(cli_main, "_is_windows", return_value=True)
def test_unreadable_ancestor_does_not_hide_the_launcher(_win, tmp_path, monkeypatch):
    scripts = _scripts_dir(tmp_path)
    launcher = _FakeProc(100, str(scripts / "robo.exe"))
    hidden = _GoneProc(101, parent=launcher)
    me = _FakeProc(os.getpid(), r"C:\Python312\python.exe", parent=hidden)
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil({os.getpid(): me}))

    assert update_cmd._launchers_running_this_update(scripts) == [100]


@patch.object(cli_main, "_is_windows", return_value=True)
def test_update_started_from_python_is_not_handed_off(_win, tmp_path, monkeypatch):
    scripts = _scripts_dir(tmp_path)
    shell = _FakeProc(10, r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    redirector = _FakeProc(101, str(scripts / "python.exe"), parent=shell)
    me = _FakeProc(os.getpid(), r"C:\Python312\python.exe", parent=redirector)
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil({os.getpid(): me}))

    assert update_cmd._launchers_running_this_update(scripts) == []


@patch.object(cli_main, "_is_windows", return_value=True)
def test_another_installs_launcher_is_not_ours(_win, tmp_path, monkeypatch):
    scripts = _scripts_dir(tmp_path)
    other = tmp_path / "other-install" / ".venv" / "Scripts" / "robo.exe"
    launcher = _FakeProc(100, str(other))
    me = _FakeProc(os.getpid(), r"C:\Python312\python.exe", parent=launcher)
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil({os.getpid(): me}))

    assert update_cmd._launchers_running_this_update(scripts) == []


@patch.object(cli_main, "_is_windows", return_value=False)
def test_no_hand_off_off_windows(_win, tmp_path):
    assert update_cmd._launchers_running_this_update(_scripts_dir(tmp_path)) == []


# ---------------------------------------------------------------------------
# Handing off
# ---------------------------------------------------------------------------


def test_hand_off_restarts_the_update_from_python_in_a_new_console(capsys):
    with patch.object(update_cmd.subprocess, "Popen") as popen:
        assert update_cmd._hand_off_update_to_new_window(["update", "--yes"], [100, 20]) is True

    popen.assert_called_once()
    cmd = popen.call_args.args[0]
    kwargs = popen.call_args.kwargs
    assert cmd == [sys.executable, "-m", "robo_cli.main", "update", "--yes"]
    assert kwargs["env"][update_cmd.UPDATE_HANDOFF_ENV] == f"100,20,{os.getpid()}"
    assert kwargs["creationflags"] == NEW_CONSOLE | BREAKAWAY
    assert "new window" in capsys.readouterr().out


def test_hand_off_without_job_breakaway_still_opens_the_window():
    # A launcher whose job object forbids breakaway makes CreateProcess fail
    # with access denied; the window still opens, just inside that job.
    with patch.object(update_cmd.subprocess, "Popen", side_effect=[OSError("denied"), object()]) as popen:
        assert update_cmd._hand_off_update_to_new_window(["update"], [100]) is True

    flags = [call.kwargs["creationflags"] for call in popen.call_args_list]
    assert flags == [NEW_CONSOLE | BREAKAWAY, NEW_CONSOLE]


def test_failed_hand_off_lets_the_update_run_here(capsys):
    with patch.object(update_cmd.subprocess, "Popen", side_effect=OSError("denied")):
        assert update_cmd._hand_off_update_to_new_window(["update"], [100]) is False

    assert "new window" not in capsys.readouterr().out


def test_handed_off_update_waits_for_the_launcher_to_exit(monkeypatch):
    waited: list = []
    live = {100: _FakeProc(100), 200: _FakeProc(200)}
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil(live, waited))

    # 300 already exited; "x" is not a PID. Neither may stop the wait.
    update_cmd._wait_for_handoff_launcher("100,200,300,x", timeout=5)

    assert waited == [([100, 200], 5)]


# ---------------------------------------------------------------------------
# cmd_update wiring
# ---------------------------------------------------------------------------


class _Tty:
    def isatty(self) -> bool:
        return True


class _TtyOut:
    def __init__(self):
        self.text = ""

    def write(self, text):
        self.text += text
        return len(text)

    def flush(self):
        pass

    def isatty(self) -> bool:
        return True


def test_terminal_update_under_the_launcher_hands_off_and_stops(monkeypatch):
    monkeypatch.delenv(update_cmd.UPDATE_HANDOFF_ENV, raising=False)
    monkeypatch.setattr(cli_main.sys, "stdin", _Tty())
    with patch.object(update_cmd, "_launchers_running_this_update", return_value=[100]), patch.object(
        update_cmd, "_hand_off_update_to_new_window", return_value=True
    ) as hand_off, patch.object(cli_main, "_cmd_update_impl") as impl:
        cli_main.cmd_update(SimpleNamespace())

    hand_off.assert_called_once()
    assert hand_off.call_args.args[1] == [100]
    impl.assert_not_called()


def test_terminal_update_without_a_launcher_runs_here(monkeypatch):
    monkeypatch.delenv(update_cmd.UPDATE_HANDOFF_ENV, raising=False)
    monkeypatch.setattr(cli_main.sys, "stdin", _Tty())
    with patch.object(update_cmd, "_launchers_running_this_update", return_value=[]), patch.object(
        update_cmd, "_hand_off_update_to_new_window"
    ) as hand_off, patch.object(cli_main, "_cmd_update_impl") as impl:
        cli_main.cmd_update(SimpleNamespace())

    hand_off.assert_not_called()
    impl.assert_called_once()


def test_handed_off_update_runs_once_the_launcher_is_gone(monkeypatch):
    monkeypatch.setenv(update_cmd.UPDATE_HANDOFF_ENV, "100,200")
    monkeypatch.setattr(cli_main.sys, "stdin", _Tty())
    monkeypatch.setattr(cli_main.sys, "stdout", _TtyOut())
    registered = []
    monkeypatch.setattr("atexit.register", lambda fn, *a, **k: registered.append(fn))
    with patch.object(update_cmd, "_wait_for_handoff_launcher") as wait, patch.object(
        update_cmd, "_hand_off_update_to_new_window"
    ) as hand_off, patch.object(cli_main, "_cmd_update_impl") as impl:
        cli_main.cmd_update(SimpleNamespace())

    wait.assert_called_once_with("100,200")
    hand_off.assert_not_called()  # never hands off twice
    impl.assert_called_once()
    assert update_cmd._pause_before_window_closes in registered
    assert update_cmd.UPDATE_HANDOFF_ENV not in os.environ


class _Pipe:
    def write(self, text):
        return len(text)

    def flush(self):
        pass

    def isatty(self) -> bool:
        return False


@pytest.mark.parametrize(
    ("stdin", "stdout"),
    [(_Pipe(), _Pipe()), (None, _Pipe()), (_Tty(), _Pipe())],  # Windows calls NUL a terminal
    ids=["pipes", "no-stdin", "nul-stdin"],
)
def test_an_update_read_through_a_pipe_waits_but_never_pauses(monkeypatch, stdin, stdout):
    """The desktop's update window reads the output; there is no console to hold open."""
    monkeypatch.setenv(update_cmd.UPDATE_HANDOFF_ENV, "4242")
    monkeypatch.setattr(cli_main.sys, "stdin", stdin)
    monkeypatch.setattr(cli_main.sys, "stdout", stdout)
    registered = []
    monkeypatch.setattr("atexit.register", lambda fn, *a, **k: registered.append(fn))
    # The reopen is stubbed: the real one runs `robo desktop`, which would
    # build and launch the actual desktop app from inside the test run.
    with patch.object(update_cmd, "_wait_for_handoff_launcher") as wait, patch.object(
        update_cmd, "_hand_off_update_to_new_window"
    ) as hand_off, patch.object(cli_main, "_cmd_update_impl") as impl, patch.object(
        update_cmd, "_reopen_desktop_after_update"
    ) as reopen:
        cli_main.cmd_update(SimpleNamespace(reopen_desktop="packaged"))

    wait.assert_called_once_with("4242")
    hand_off.assert_not_called()
    impl.assert_called_once()
    reopen.assert_called_once_with("packaged", succeeded=True)
    assert update_cmd._pause_before_window_closes not in registered


# ---------------------------------------------------------------------------
# Desktop "Update now": the app starts the update detached and quits
# ---------------------------------------------------------------------------


def test_desktop_update_opens_its_own_window_and_waits_for_the_app(monkeypatch):
    monkeypatch.setenv(update_cmd.UPDATE_HANDOFF_ENV, "4242")
    monkeypatch.setattr(
        cli_main.sys, "argv", ["main.py", "update", "--yes", "--new-window", "--reopen-desktop", "packaged"]
    )
    with patch.object(cli_main, "_is_windows", return_value=True), patch.object(
        update_cmd, "_hand_off_update_to_new_window", return_value=True
    ) as hand_off, patch.object(cli_main, "_cmd_update_impl") as impl:
        cli_main.cmd_update(SimpleNamespace(new_window=True, reopen_desktop="packaged"))

    hand_off.assert_called_once_with(["update", "--yes", "--reopen-desktop", "packaged"], [4242])
    impl.assert_not_called()


def test_desktop_update_without_a_window_still_waits_for_the_app(monkeypatch):
    monkeypatch.setenv(update_cmd.UPDATE_HANDOFF_ENV, "4242")
    monkeypatch.setattr(cli_main.sys, "argv", ["main.py", "update", "--new-window"])
    monkeypatch.setattr("atexit.register", lambda fn, *a, **k: None)
    with patch.object(cli_main, "_is_windows", return_value=True), patch.object(
        update_cmd, "_hand_off_update_to_new_window", return_value=False
    ), patch.object(update_cmd, "_wait_for_handoff_launcher") as wait, patch.object(
        cli_main, "_cmd_update_impl"
    ) as impl:
        cli_main.cmd_update(SimpleNamespace(new_window=True))

    wait.assert_called_once_with("4242")
    impl.assert_called_once()


@pytest.mark.parametrize(
    ("outcome", "succeeded"),
    [(None, True), (SystemExit(0), True), (SystemExit(2), False), (SystemExit(1), False)],
)
def test_the_app_is_reopened_only_after_a_finished_update(monkeypatch, outcome, succeeded):
    monkeypatch.delenv(update_cmd.UPDATE_HANDOFF_ENV, raising=False)
    monkeypatch.setattr(cli_main.sys, "stdin", None)
    with patch.object(cli_main, "_cmd_update_impl", side_effect=outcome), patch.object(
        update_cmd, "_reopen_desktop_after_update"
    ) as reopen:
        if isinstance(outcome, SystemExit):
            with pytest.raises(SystemExit):
                cli_main.cmd_update(SimpleNamespace(reopen_desktop="source"))
        else:
            cli_main.cmd_update(SimpleNamespace(reopen_desktop="source"))

    reopen.assert_called_once_with("source", succeeded=succeeded)


def test_a_plain_update_never_reopens_the_app(monkeypatch):
    monkeypatch.delenv(update_cmd.UPDATE_HANDOFF_ENV, raising=False)
    monkeypatch.setattr(cli_main.sys, "stdin", None)
    with patch.object(cli_main, "_cmd_update_impl"), patch.object(update_cmd, "_reopen_desktop_after_update") as reopen:
        cli_main.cmd_update(SimpleNamespace())

    reopen.assert_not_called()


class TestReopenDesktop:
    @pytest.fixture
    def unregistered(self, monkeypatch):
        calls = []
        monkeypatch.setattr("atexit.unregister", lambda fn: calls.append(fn))
        return calls

    @pytest.fixture
    def slept(self, monkeypatch):
        calls = []
        monkeypatch.setattr(update_cmd._time, "sleep", lambda seconds: calls.append(seconds))
        return calls

    @pytest.mark.parametrize(("mode", "extra"), [("packaged", []), ("source", ["--source"])])
    def test_reopens_the_app_the_way_it_was_running(self, unregistered, slept, mode, extra):
        with patch.object(update_cmd.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            update_cmd._reopen_desktop_after_update(mode, succeeded=True)

        assert run.call_args.args[0] == [sys.executable, "-m", "robo_cli.main", "desktop", *extra]
        assert unregistered == [update_cmd._pause_before_window_closes]

    def test_a_console_says_it_closes_and_waits_so_it_can_be_read(self, unregistered, slept, monkeypatch):
        console = _TtyOut()
        monkeypatch.setattr(update_cmd.sys, "stdout", console)
        with patch.object(update_cmd.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            update_cmd._reopen_desktop_after_update("packaged", succeeded=True)

        assert "closes in" in console.text
        assert slept == [update_cmd.REOPEN_WINDOW_CLOSE_SECONDS]

    def test_the_update_window_is_not_kept_waiting(self, unregistered, slept, capsys):
        with patch.object(update_cmd.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            update_cmd._reopen_desktop_after_update("packaged", succeeded=True)

        assert slept == []
        assert "closes in" not in capsys.readouterr().out

    def test_a_failed_update_leaves_the_window_open_with_a_hint(self, unregistered, capsys):
        with patch.object(update_cmd.subprocess, "run") as run:
            update_cmd._reopen_desktop_after_update("packaged", succeeded=False)

        run.assert_not_called()
        assert unregistered == []
        assert "robo desktop" in capsys.readouterr().out

    def test_if_the_app_will_not_start_the_window_stays_open(self, unregistered, capsys):
        with patch.object(update_cmd.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            update_cmd._reopen_desktop_after_update("packaged", succeeded=True)

        assert unregistered == []
        assert "Couldn't reopen Robo" in capsys.readouterr().out


def test_the_desktop_flags_parse_but_stay_out_of_help():
    import argparse

    from robo_cli.subcommands.update import build_update_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    build_update_parser(subparsers, cmd_update=lambda _args: None)

    args = parser.parse_args(["update", "--yes", "--new-window", "--reopen-desktop", "source"])

    assert args.new_window is True and args.reopen_desktop == "source"
    help_text = subparsers.choices["update"].format_help()
    assert "--new-window" not in help_text and "--reopen-desktop" not in help_text
    with pytest.raises(SystemExit):
        parser.parse_args(["update", "--reopen-desktop", "somewhere"])


def test_a_fork_update_nobody_can_answer_does_not_record_a_no(monkeypatch, tmp_path):
    """The window has no terminal: skip the upstream question, don't save a "no" for the user."""
    monkeypatch.setattr(update_cmd, "_has_upstream_remote", lambda *_a: False)
    monkeypatch.setattr(update_cmd, "_should_skip_upstream_prompt", lambda: False)
    marked = []
    monkeypatch.setattr(update_cmd, "_mark_skip_upstream_prompt", lambda: marked.append(True))
    monkeypatch.setattr(update_cmd.sys, "stdin", _Pipe())
    monkeypatch.setattr("builtins.input", lambda *_a: pytest.fail("asked a question nobody can answer"))
    with patch.object(update_cmd.subprocess, "run") as run:
        update_cmd._sync_with_upstream_if_needed(["git"], tmp_path)

    assert marked == []
    run.assert_not_called()


def test_a_fork_update_in_a_terminal_still_asks(monkeypatch, tmp_path):
    monkeypatch.setattr(update_cmd, "_has_upstream_remote", lambda *_a: False)
    monkeypatch.setattr(update_cmd, "_should_skip_upstream_prompt", lambda: False)
    marked = []
    monkeypatch.setattr(update_cmd, "_mark_skip_upstream_prompt", lambda: marked.append(True))
    monkeypatch.setattr(update_cmd.sys, "stdin", _Tty())
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "n")
    update_cmd._sync_with_upstream_if_needed(["git"], tmp_path)

    assert len(asked) == 1
    assert marked == [True]
