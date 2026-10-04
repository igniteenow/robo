"""A late Ctrl+C must not spoil a clean exit.

Seen in the field (Windows): quitting the terminal app with Ctrl+C pressed
twice ended in a Python traceback (``KeyboardInterrupt`` inside the goodbye
summary's ``git rev-parse``), followed by cmd.exe's "Terminate batch job
(Y/N)?" from the ``robo.cmd`` launcher. The first press closes the app; the
second lands in the ``robo`` command while it prints the summary and tidies up.
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path

import pytest

from robo_cli import ctrl_c
from robo_cli.ctrl_c import ENABLE_PROCESSED_INPUT, _silence_console_ctrl_c, ignore_ctrl_c

_STDIN = -10
# ENABLE_PROCESSED_INPUT | ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT | quick edit bits
_COOKED = 0x01F7


@pytest.fixture(autouse=True)
def _restore_sigint():
    """Whatever a test does to SIGINT, put it back."""
    before = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGINT, before)


class _FakeConsole:
    """Stands in for the Windows console input mode calls."""

    def __init__(self, mode, *, settable=True):
        self.mode = mode
        self.settable = settable
        self.calls = []

    def get_mode(self, std_id):
        assert std_id == _STDIN
        return self.mode

    def set_mode(self, std_id, mode):
        assert std_id == _STDIN
        self.calls.append(("set", mode))
        if not self.settable:
            return False
        self.mode = mode
        return True

    def flush_input(self, std_id):
        assert std_id == _STDIN
        self.calls.append(("flush", None))
        return True


# ---------------------------------------------------------------------------
# ignore_ctrl_c: the signal
# ---------------------------------------------------------------------------

def test_ctrl_c_is_ignored_until_restored():
    # A test runner started in the background inherits SIGINT as "ignored",
    # so start from the interpreter's own handler and put things back after.
    inherited = signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        handler = signal.getsignal(signal.SIGINT)

        restore = ignore_ctrl_c()
        assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
        # A real interrupt now does nothing at all (no KeyboardInterrupt).
        signal.raise_signal(signal.SIGINT)

        restore()
        assert signal.getsignal(signal.SIGINT) is handler
        with pytest.raises(KeyboardInterrupt):
            signal.raise_signal(signal.SIGINT)
    finally:
        signal.signal(signal.SIGINT, inherited)


def test_restore_is_safe_to_call_twice():
    handler = signal.getsignal(signal.SIGINT)

    restore = ignore_ctrl_c()
    restore()
    # Someone else changes the handler afterwards; a second restore() must not
    # put the old one back over it.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    restore()

    assert signal.getsignal(signal.SIGINT) is signal.SIG_DFL
    signal.signal(signal.SIGINT, handler)


def test_never_raises_when_the_handler_cannot_be_changed(monkeypatch):
    """Off the main thread ``signal.signal`` raises ValueError; the caller
    still gets a working (empty) restore instead of a crash on the way out."""

    def _refuse(*_args):
        raise ValueError("signal only works in main thread of the main interpreter")

    with monkeypatch.context() as patched:
        patched.setattr(ctrl_c.signal, "signal", _refuse)

        restore = ignore_ctrl_c()
        restore()


# ---------------------------------------------------------------------------
# The Windows console half (runs everywhere: the console calls are injected)
# ---------------------------------------------------------------------------

def test_console_stops_turning_ctrl_c_into_an_interrupt():
    console = _FakeConsole(_COOKED)

    undo = _silence_console_ctrl_c(console.get_mode, console.set_mode, console.flush_input)

    assert console.mode == _COOKED & ~ENABLE_PROCESSED_INPUT
    # Every other mode bit is left exactly as it was.
    assert console.mode | ENABLE_PROCESSED_INPUT == _COOKED

    undo()
    assert console.mode == _COOKED
    # The Ctrl+C keystrokes typed meanwhile are dropped before the mode comes
    # back, so the shell is not handed them as input.
    assert console.calls == [
        ("set", _COOKED & ~ENABLE_PROCESSED_INPUT),
        ("flush", None),
        ("set", _COOKED),
    ]


def test_console_left_alone_when_stdin_is_not_a_console():
    console = _FakeConsole(None)

    undo = _silence_console_ctrl_c(console.get_mode, console.set_mode, console.flush_input)
    undo()

    assert console.calls == []


def test_console_left_alone_when_ctrl_c_is_already_off():
    raw = _COOKED & ~ENABLE_PROCESSED_INPUT
    console = _FakeConsole(raw)

    undo = _silence_console_ctrl_c(console.get_mode, console.set_mode, console.flush_input)
    undo()

    # Nothing changed, so nothing is "restored" (and no input is thrown away).
    assert console.calls == []
    assert console.mode == raw


def test_console_undo_is_empty_when_the_mode_cannot_be_set():
    console = _FakeConsole(_COOKED, settable=False)

    undo = _silence_console_ctrl_c(console.get_mode, console.set_mode, console.flush_input)
    undo()

    assert console.calls == [("set", _COOKED & ~ENABLE_PROCESSED_INPUT)]
    assert console.mode == _COOKED


def test_windows_console_is_silenced_and_restored(monkeypatch):
    console = _FakeConsole(_COOKED)
    monkeypatch.setattr(ctrl_c.sys, "platform", "win32")
    monkeypatch.setattr(
        ctrl_c,
        "_silence_windows_console",
        lambda: _silence_console_ctrl_c(console.get_mode, console.set_mode, console.flush_input),
    )

    restore = ignore_ctrl_c()
    assert console.mode == _COOKED & ~ENABLE_PROCESSED_INPUT
    restore()
    assert console.mode == _COOKED


def test_a_console_failure_still_leaves_the_signal_restorable(monkeypatch):
    handler = signal.getsignal(signal.SIGINT)

    def _boom():
        raise OSError("no console")

    monkeypatch.setattr(ctrl_c.sys, "platform", "win32")
    monkeypatch.setattr(ctrl_c, "_silence_windows_console", _boom)

    restore = ignore_ctrl_c()
    assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
    restore()
    assert signal.getsignal(signal.SIGINT) is handler


# ---------------------------------------------------------------------------
# The terminal app's exit path
# ---------------------------------------------------------------------------

@pytest.fixture
def main_mod(monkeypatch):
    import robo_cli.main as mod

    monkeypatch.setattr(mod, "_has_any_provider_configured", lambda: True)
    monkeypatch.setattr(mod, "_oneshot_cleanup_done", False)
    monkeypatch.setattr(mod, "_make_tui_argv", lambda tui_dir, tui_dev: (["node", "dist/entry.js"], Path(".")))
    # Keep the real process's exit hooks out of the test run, and turn the
    # launcher's final os._exit into a SystemExit the test can catch.
    registered = []
    events = []
    import atexit

    monkeypatch.setattr(atexit, "register", lambda fn, *a, **k: registered.append(fn) or fn)
    monkeypatch.setattr(mod.logging, "shutdown", lambda: events.append("logs closed"))
    monkeypatch.setattr(mod, "_print_tui_goodbye", lambda: events.append("goodbye"))

    def _exit(code):
        events.append(("os._exit", code, signal.getsignal(signal.SIGINT)))
        raise SystemExit(code)

    monkeypatch.setattr(mod.os, "_exit", _exit)
    mod._test_atexit_registered = registered
    mod._test_events = events
    yield mod
    del mod._test_atexit_registered
    del mod._test_events


@pytest.mark.parametrize("tui_exit_code", [0, 130])
def test_second_ctrl_c_during_the_goodbye_is_swallowed(monkeypatch, main_mod, tui_exit_code):
    """The regression itself: Ctrl+C arrives while the exit summary is being
    put together. The summary finishes, and the command exits with the app's
    own status instead of dying on KeyboardInterrupt."""
    handler = signal.getsignal(signal.SIGINT)
    seen = {}

    monkeypatch.setattr(main_mod.subprocess, "call", lambda argv, cwd=None, env=None: tui_exit_code)

    def _summary(session_id, active_session_file=None):
        seen["handler_during_summary"] = signal.getsignal(signal.SIGINT)
        signal.raise_signal(signal.SIGINT)  # the second press
        seen["summary_finished"] = True

    monkeypatch.setattr(main_mod, "_print_tui_exit_summary", _summary)

    with pytest.raises(SystemExit) as exit_info:
        main_mod._launch_tui()

    assert exit_info.value.code == tui_exit_code
    assert seen == {"handler_during_summary": signal.SIG_IGN, "summary_finished": True}
    # The logs are closed while Ctrl+C is still off; it is handed back as the
    # very last step, and the process leaves at once (no interpreter shutdown
    # with Ctrl+C on, which is where cmd.exe's "Terminate batch job (Y/N)?"
    # came from).
    assert main_mod._test_events == ["goodbye", "logs closed", ("os._exit", tui_exit_code, handler)]
    assert signal.getsignal(signal.SIGINT) is handler
    assert main_mod._test_atexit_registered == []


def test_goodbye_is_printed_after_the_summary(monkeypatch, main_mod, capsys):
    monkeypatch.setattr(main_mod.subprocess, "call", lambda argv, cwd=None, env=None: 0)
    monkeypatch.setattr(main_mod, "_print_tui_exit_summary", lambda *a, **k: print("summary"))
    monkeypatch.setattr(main_mod, "_print_tui_goodbye", lambda: print("goodbye line"))

    with pytest.raises(SystemExit):
        main_mod._launch_tui()

    assert capsys.readouterr().out.splitlines() == ["summary", "goodbye line"]


def test_goodbye_uses_the_active_skin_and_thanks_the_user(monkeypatch, capsys):
    import robo_cli.main as mod
    from robo_cli import skin_engine

    # Activating a skin is process-global; put the previous one back afterwards.
    monkeypatch.setattr(skin_engine, "_active_skin", skin_engine._active_skin)
    monkeypatch.setattr(skin_engine, "_active_skin_name", skin_engine._active_skin_name)
    monkeypatch.setattr("robo_cli.config.load_config", lambda: {"display": {"skin": "ember"}})

    mod._print_tui_goodbye()

    out = capsys.readouterr().out
    assert out.startswith("\n")
    assert "Embers banked. Robo standing by." in out
    assert "Thank you for using Ignitee Now." in out


def test_goodbye_still_prints_when_the_config_cannot_be_read(monkeypatch, capsys):
    import robo_cli.main as mod

    def _broken():
        raise RuntimeError("no config")

    monkeypatch.setattr("robo_cli.config.load_config", _broken)

    mod._print_tui_goodbye()

    assert "Thank you for using Ignitee Now." in capsys.readouterr().out


def test_update_relaunch_keeps_ctrl_c_and_a_quiet_shutdown(monkeypatch, main_mod):
    """Exit code 42 hands off to `robo update`, which must stay interruptible:
    the normal exit path, with the quiet shutdown handler, as before."""
    handler = signal.getsignal(signal.SIGINT)
    relaunched = []

    monkeypatch.setattr(main_mod.subprocess, "call", lambda argv, cwd=None, env=None: 42)
    monkeypatch.setattr(
        "robo_cli.relaunch.relaunch",
        lambda args, **kw: relaunched.append((args, signal.getsignal(signal.SIGINT))),
    )

    with pytest.raises(SystemExit) as exit_info:
        main_mod._launch_tui()

    assert exit_info.value.code == 42
    assert relaunched == [(["update"], handler)]
    assert main_mod._test_atexit_registered == [main_mod._quiet_sigint_at_exit]
    assert main_mod._test_events == []


def test_ctrl_c_that_closes_the_app_still_gets_its_summary(monkeypatch, main_mod):
    """Ctrl+C delivered to the wrapper while the app is running: treated as
    the app exiting on interrupt (130), summary printed, no traceback."""
    calls = []

    def _interrupted(argv, cwd=None, env=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(main_mod.subprocess, "call", _interrupted)
    monkeypatch.setattr(main_mod, "_print_tui_exit_summary", lambda *a, **k: calls.append("summary"))

    with pytest.raises(SystemExit) as exit_info:
        main_mod._launch_tui()

    assert exit_info.value.code == 130
    assert calls == ["summary"]


def test_ctrl_c_is_handed_back_even_when_the_summary_fails(monkeypatch, main_mod):
    handler = signal.getsignal(signal.SIGINT)

    monkeypatch.setattr(main_mod.subprocess, "call", lambda argv, cwd=None, env=None: 0)

    def _broken_summary(*_a, **_k):
        raise RuntimeError("summary failed")

    monkeypatch.setattr(main_mod, "_print_tui_exit_summary", _broken_summary)

    with pytest.raises(RuntimeError, match="summary failed"):
        main_mod._launch_tui()

    assert signal.getsignal(signal.SIGINT) is handler
    assert main_mod._test_events == []


def test_logs_close_before_ctrl_c_is_handed_back(monkeypatch):
    """The order is the whole point: tidy up, then hand back, then leave."""
    import robo_cli.main as mod

    order = []

    monkeypatch.setattr(mod.logging, "shutdown", lambda: order.append("logs closed"))
    monkeypatch.setattr(mod.os, "_exit", lambda code: order.append(("os._exit", code)))

    mod._end_tui_launcher(130, lambda: order.append("ctrl+c back"))

    assert order == ["logs closed", "ctrl+c back", ("os._exit", 130)]


def test_launcher_still_leaves_when_the_log_close_or_the_restore_fails(monkeypatch):
    import robo_cli.main as mod

    order = []

    def _broken_shutdown():
        raise RuntimeError("log close failed")

    def _broken_restore():
        raise RuntimeError("restore failed")

    monkeypatch.setattr(mod.logging, "shutdown", _broken_shutdown)
    monkeypatch.setattr(mod.os, "_exit", lambda code: order.append(("os._exit", code)))

    mod._end_tui_launcher(0, _broken_restore)

    assert order == [("os._exit", 0)]


def test_quiet_shutdown_handler_exits_without_a_traceback(monkeypatch, main_mod):
    exits = []
    monkeypatch.setattr(main_mod.os, "_exit", exits.append)

    main_mod._quiet_sigint_at_exit()
    signal.raise_signal(signal.SIGINT)

    assert exits == [130]


# ---------------------------------------------------------------------------
# The entry point: any command, any unhandled Ctrl+C
# ---------------------------------------------------------------------------

def test_unhandled_ctrl_c_in_any_command_exits_130_without_a_traceback(monkeypatch, tmp_path, capsys):
    import robo_cli.main as cli_main
    import robo_runtime.cli as entry

    def _interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(entry, "activate_robo_home", lambda: tmp_path)
    monkeypatch.setattr(cli_main, "main", _interrupted)
    monkeypatch.setattr(sys, "argv", ["robo", "status"])

    with pytest.raises(SystemExit) as exit_info:
        entry.main()

    assert exit_info.value.code == 130
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert "KeyboardInterrupt" not in captured.err


def test_entry_point_leaves_other_exits_alone(monkeypatch, tmp_path):
    import robo_cli.main as cli_main
    import robo_runtime.cli as entry

    def _exit_3():
        raise SystemExit(3)

    monkeypatch.setattr(entry, "activate_robo_home", lambda: tmp_path)
    monkeypatch.setattr(cli_main, "main", _exit_3)
    monkeypatch.setattr(sys, "argv", ["robo", "status"])

    with pytest.raises(SystemExit) as exit_info:
        entry.main()

    assert exit_info.value.code == 3
