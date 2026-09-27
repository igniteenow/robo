"""The desktop's updater window: progress from `robo update` output, and running it."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from robo_cli import update_window as uw

# What a real Windows "Update now" printed, trimmed (package lists and npm noise
# kept so the parser has to ignore them).
TRANSCRIPT = """\
Updating Robo...

◆ Pre-update snapshot: 20260926-192357-pre-update

⚠ Updating from fork:
  https://github.com/example/robo.git

→ Fetching updates...
→ Found 1 new commit(s)
→ Pulling updates...
  ✓ Cleared 81 stale __pycache__ directories

→ Fetching upstream...
  ✓ Fork is up to date with upstream
→ Updating Python dependencies...
  → Installing managed uv into C:\\Users\\me\\.robo\\bin ...
  ⚠ Robo venv links SQLite 3.45.1, which has the WAL-reset bug.
  → Provisioning a private Python 3.11 runtime with fixed SQLite...
  → Building a relocatable replacement environment...
Resolved 251 packages in 1ms
 + agent-client-protocol==0.9.0
  ✓ Managed Python runtime repaired (SQLite 3.45.1 → 3.53.1)

→ Refreshing 8 active lazy backend(s)...
  ✓ 8 already current
→ Updating Node.js dependencies...
added 209 packages in 9s
  ✓ repo root + ui-tui, web workspaces (desktop skipped)
→ Building web UI...
  ✓ Web UI built
→ Checking if desktop app needs rebuilding...
  ✓ Desktop app up to date

✓ Code updated!
→ Syncing bundled skills...
→ Checking configuration for new options...
✓ Update complete!

→ Reopening Robo...
"""


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _progress(clock: Clock | None = None) -> uw.UpdateProgress:
    return uw.UpdateProgress(clock=clock or Clock())


class TestCleanLine:
    def test_drops_colour_codes_and_surrounding_space(self):
        assert uw.clean_line("  \x1b[32m✓ Web UI built\x1b[0m  ") == "✓ Web UI built"

    def test_keeps_only_the_last_redraw_of_a_progress_line(self):
        assert uw.clean_line("Downloading 10%\rDownloading 55%\rDownloading 100%\r") == "Downloading 100%"


class TestUpdateProgress:
    def test_follows_a_real_update_through_every_phase_in_order(self):
        progress = _progress()
        seen = [progress.phase.key]
        for line in TRANSCRIPT.splitlines():
            progress.feed(line)
            if progress.phase.key != seen[-1]:
                seen.append(progress.phase.key)

        assert seen == [phase.key for phase in uw.PHASES]
        assert progress.errors == []
        assert progress.notes == []

    def test_the_bar_never_moves_backwards(self):
        clock = Clock()
        progress = _progress(clock)
        last = progress.fraction()
        for line in TRANSCRIPT.splitlines():
            clock.now += 3
            progress.feed(line)
            current = progress.fraction()
            assert current >= last
            last = current
        assert last < 1.0  # only a finished update fills it

    def test_an_earlier_step_printed_late_does_not_rewind(self):
        progress = _progress()
        progress.feed("→ Building web UI...")
        progress.feed("→ Updating Python dependencies...")

        assert progress.phase.key == "web"

    def test_a_long_step_keeps_creeping_but_stays_inside_its_phase(self):
        clock = Clock()
        progress = _progress(clock)
        progress.feed("→ Updating Python dependencies...")
        start = progress.fraction()
        clock.now += 30
        middle = progress.fraction()
        clock.now += 3600
        late = progress.fraction()

        next_start = uw.PHASES[uw._PHASE_INDEX["python"] + 1].start
        assert start < middle < late < next_start

    def test_step_lines_become_the_detail_and_noise_does_not(self):
        progress = _progress()
        progress.feed("  → Provisioning a private Python 3.11 runtime with fixed SQLite...")
        progress.feed(" + pywin32==311")
        progress.feed("Resolved 251 packages in 1ms")

        assert progress.detail == "Provisioning a private Python 3.11 runtime with fixed SQLite…"

    def test_a_very_long_step_is_shortened(self):
        progress = _progress()
        progress.feed("→ " + "x" * 300)

        assert len(progress.detail) == uw._DETAIL_MAX
        assert progress.detail.endswith("…")

    def test_knows_when_nothing_needed_updating(self):
        progress = _progress()
        progress.feed("✓ Already up to date!")

        assert progress.already_current

    def test_notices_when_robo_could_not_be_reopened(self):
        progress = _progress()
        progress.feed("  Couldn't reopen Robo. Start it again with: robo desktop")

        assert progress.reopen_failed

    def test_collects_parts_that_did_not_refresh(self):
        progress = _progress()
        progress.feed("  ⚠ Web UI build failed (robo web will not be available)")
        progress.feed("  ⚠ Web UI build failed (robo web will not be available)")
        progress.feed("  ⚠ Desktop build failed (non-fatal; run `robo desktop` to retry)")

        assert progress.notes == ["The web dashboard didn't rebuild.", "The desktop app didn't rebuild."]


class TestFailureMessage:
    def test_names_the_step_and_the_reason(self):
        progress = _progress()
        for line in (
            "Updating Robo...",
            "→ Fetching updates...",
            "→ Pulling updates...",
            "→ Updating Python dependencies...",
            "✗ Update failed: uv sync exited with status 1",
            "  Your code was not changed.",
        ):
            progress.feed(line)

        headline, explanation = progress.failure(1)

        assert headline == "The update didn't finish"
        assert explanation.startswith("Something went wrong while installing Python components.")
        assert "Update failed: uv sync exited with status 1" in explanation
        assert explanation.endswith("Your code was not changed.")

    def test_another_update_running_is_its_own_message(self):
        progress = _progress()
        progress.feed("✗ Another Robo update is already running (PID 4242, started 12s ago).")

        headline, explanation = progress.failure(uw.EXIT_CONCURRENT)

        assert headline == "Another update is already running"
        assert "try again" in explanation.lower()

    def test_without_an_error_line_it_falls_back_to_the_last_warnings(self):
        progress = _progress()
        progress.feed("→ Updating Python dependencies...")
        progress.feed("⚠ Venv still unhealthy after repair: robo_cli not importable")

        _headline, explanation = progress.failure(1)

        assert "Venv still unhealthy after repair" in explanation

    def test_a_failure_before_any_output_says_so(self):
        _headline, explanation = _progress().failure(1)

        assert explanation == "Something went wrong while starting the update."


class TestCommands:
    def test_runs_the_same_update_the_desktop_always_ran(self):
        assert uw.build_update_command("py.exe", None, "packaged") == [
            "py.exe", "-m", "robo_cli.main", "update", "--yes", "--reopen-desktop", "packaged",
        ]

    def test_passes_a_non_default_branch(self):
        command = uw.build_update_command("py.exe", "bb/gui", "source")

        assert command[4:] == ["--yes", "--branch", "bb/gui", "--reopen-desktop", "source"]
        assert "--branch" not in uw.build_update_command("py.exe", "main", "packaged")

    def test_never_asks_the_update_for_a_console_of_its_own(self):
        assert "--new-window" not in uw.build_update_command("py.exe", "dev", "packaged")

    @pytest.mark.parametrize(("mode", "extra"), [("packaged", []), ("source", ["--source"])])
    def test_open_robo_starts_the_app_the_way_it_was_running(self, mode, extra):
        assert uw.build_open_command("py.exe", mode) == ["py.exe", "-m", "robo_cli.main", "desktop", *extra]

    def test_update_env_reads_utf8_and_waits_for_the_app(self):
        env = uw.update_env({"PATH": "x", uw.UPDATE_HANDOFF_ENV: "1,2"}, 4242)

        assert env["PATH"] == "x"
        assert env["PYTHONIOENCODING"] == "utf-8"
        assert env["PYTHONUNBUFFERED"] == "1"
        assert env[uw.UPDATE_HANDOFF_ENV] == "4242"

    def test_git_never_waits_on_a_prompt_nobody_can_see(self):
        assert uw.update_env({}, None)["GIT_TERMINAL_PROMPT"] == "0"

    def test_a_retry_has_nobody_to_wait_for(self):
        env = uw.update_env({uw.UPDATE_HANDOFF_ENV: "4242"}, None)

        assert uw.UPDATE_HANDOFF_ENV not in env

    def test_handoff_name_matches_the_update_command(self):
        from robo_cli.update_cmd import UPDATE_HANDOFF_ENV
        from robo_cli.update_lock import UPDATE_EXIT_CONCURRENT

        assert uw.UPDATE_HANDOFF_ENV == UPDATE_HANDOFF_ENV
        assert uw.EXIT_CONCURRENT == UPDATE_EXIT_CONCURRENT

    def test_log_lives_in_robo_home(self, tmp_path):
        assert uw.log_path({"ROBO_HOME": str(tmp_path)}) == tmp_path / "logs" / uw.LOG_NAME


def _drain(runner: uw.UpdateRunner, timeout: float = 15.0) -> tuple[list[str], int | None]:
    lines: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            kind, value = runner.events.get(timeout=0.2)
        except Exception:
            continue
        if kind == "line":
            lines.append(value)
        else:
            return lines, value
    return lines, None


class TestUpdateRunner:
    def test_streams_every_line_then_the_exit_code(self, tmp_path):
        script = "import sys\nprint('→ Fetching updates...')\nprint('✓ Käse — 100%')\nsys.exit(3)\n"
        runner = uw.UpdateRunner(
            [sys.executable, "-c", script], cwd=str(tmp_path), env=uw.update_env(dict(os.environ), None)
        )
        runner.start()

        lines, code = _drain(runner)

        assert lines == ["→ Fetching updates...", "✓ Käse — 100%"]
        assert code == 3

    def test_the_update_has_nobody_to_ask(self, tmp_path):
        """No terminal on stdin, and a question gets an immediate end-of-input."""
        script = (
            "import sys\n"
            "print('tty', sys.stdin.isatty())\n"
            "try:\n"
            "    input('Continue? ')\n"
            "except EOFError:\n"
            "    print('eof')\n"
        )
        runner = uw.UpdateRunner(
            [sys.executable, "-c", script], cwd=str(tmp_path), env=uw.update_env(dict(os.environ), None)
        )
        runner.start()

        lines, code = _drain(runner)

        assert code == 0
        assert lines[0] == "tty False"
        assert lines[-1].endswith("eof")

    def test_stop_ends_a_running_update(self, tmp_path):
        runner = uw.UpdateRunner(
            [sys.executable, "-c", "import time; print('working', flush=True); time.sleep(60)"],
            cwd=str(tmp_path),
            env=uw.update_env(dict(os.environ), None),
        )
        runner.start()
        assert runner.events.get(timeout=10) == ("line", "working")

        runner.stop()
        _lines, code = _drain(runner)

        assert code not in (None, 0)
        assert not runner.running

    def test_reports_the_exit_even_when_something_it_started_keeps_the_output_open(self, tmp_path):
        """The reopened app or a restarted gateway can outlive the update and hold its stdout."""
        script = (
            "import subprocess, sys\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(8)'])\n"
            "print('→ Reopening Robo...', flush=True)\n"
        )
        runner = uw.UpdateRunner(
            [sys.executable, "-c", script], cwd=str(tmp_path), env=uw.update_env(dict(os.environ), None)
        )
        started = time.monotonic()
        runner.start()

        lines, code = _drain(runner, timeout=10)

        assert lines == ["→ Reopening Robo..."]
        assert code == 0
        assert time.monotonic() - started < 5  # well before the grandchild lets go of the pipe


class TestWithoutTk:
    def test_falls_back_to_a_console_update(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(uw, "tk", None)
        monkeypatch.setattr(
            uw, "run_update_in_console", lambda command, cwd, env: calls.append((command, cwd, env)) or True
        )

        code = uw.main(["--python", "py.exe", "--root", str(tmp_path), "--reopen", "source", "--wait-pid", "77"])

        assert code == 0
        (command, cwd, env), = calls
        assert command == uw.build_update_command("py.exe", None, "source")
        assert cwd == str(tmp_path)
        assert env[uw.UPDATE_HANDOFF_ENV] == "77"

    def test_reports_failure_when_no_console_can_be_opened_either(self, monkeypatch, tmp_path):
        monkeypatch.setattr(uw, "tk", None)
        monkeypatch.setattr(uw, "run_update_in_console", lambda *a, **k: False)

        assert uw.main(["--python", "py.exe", "--root", str(tmp_path)]) == 1

    def test_the_console_fallback_is_windows_only(self, tmp_path):
        if sys.platform == "win32":
            pytest.skip("opens a real console on Windows")
        assert uw.run_update_in_console(["true"], cwd=str(tmp_path), env={}) is False


class TestRunsStandalone:
    def test_imports_nothing_outside_the_standard_library(self, tmp_path):
        """The desktop runs this file with -I -S on the base interpreter: no venv, no repo."""
        script = Path(uw.__file__)
        probe = (
            "import runpy, sys\n"
            f"module = runpy.run_path({str(script)!r}, run_name='probe')\n"
            "print(module['build_update_command']('py', None, 'packaged')[3])\n"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-c", probe], cwd=str(tmp_path), capture_output=True, text=True, timeout=60
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "update"


# ---------------------------------------------------------------------------
# The window itself, where a display is available
# ---------------------------------------------------------------------------


@pytest.fixture
def tk_root():
    tkinter = pytest.importorskip("tkinter")
    try:
        root = tkinter.Tk()
    except tkinter.TclError:
        pytest.skip("no display")
    yield root
    try:
        root.destroy()
    except tkinter.TclError:
        pass


def _run_window(root, monkeypatch, tmp_path, script: str) -> uw.UpdateWindow:
    fake = tmp_path / "fake_steps.py"
    fake.write_text(script, encoding="utf-8")
    monkeypatch.setattr(uw, "build_update_command", lambda python, branch, reopen: [sys.executable, str(fake)])
    monkeypatch.setattr(uw, "SUCCESS_CLOSE_MS", 60_000)
    window = uw.UpdateWindow(
        root, python=sys.executable, checkout=str(Path(__file__).resolve().parents[2]), reopen="packaged",
        branch=None, env={**os.environ, "ROBO_HOME": str(tmp_path)},
    )
    window.start(wait_pid=None)
    deadline = time.monotonic() + 20
    while window.state == "running" and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    return window


def test_window_shows_a_finished_update(tk_root, monkeypatch, tmp_path):
    script = "print('Updating Robo...')\nprint('→ Updating Python dependencies...')\nprint('✓ Update complete!')\n"
    window = _run_window(tk_root, monkeypatch, tmp_path, script)

    assert window.state == "done"
    assert window.title_label.cget("text") == "Robo is up to date"
    assert int(window.bar["value"]) == 1000
    assert "✓ Update complete!" in (tmp_path / "logs" / uw.LOG_NAME).read_text(encoding="utf-8")


def test_window_explains_a_failed_update_and_offers_a_retry(tk_root, monkeypatch, tmp_path):
    script = (
        "import sys\nprint('→ Updating Node.js dependencies...')\n"
        "print('✗ Update failed: npm exited with status 1')\nsys.exit(1)\n"
    )
    window = _run_window(tk_root, monkeypatch, tmp_path, script)

    assert window.state == "failed"
    assert window.title_label.cget("text") == "The update didn't finish"
    assert "npm exited with status 1" in window.status_label.cget("text")
    buttons = [child.cget("text") for child in window.buttons.winfo_children()]
    assert buttons == ["Close", "Open Robo", "Try again"]


def test_closing_mid_update_asks_first_and_can_stop_it(tk_root, monkeypatch, tmp_path):
    from tkinter import messagebox

    fake = tmp_path / "fake_steps.py"
    fake.write_text("import time\nprint('→ Updating Python dependencies...', flush=True)\ntime.sleep(60)\n",
                    encoding="utf-8")
    monkeypatch.setattr(uw, "build_update_command", lambda python, branch, reopen: [sys.executable, str(fake)])
    window = uw.UpdateWindow(
        tk_root, python=sys.executable, checkout=str(Path(__file__).resolve().parents[2]), reopen="packaged",
        branch=None, env={**os.environ, "ROBO_HOME": str(tmp_path)},
    )
    window.start(wait_pid=None)
    deadline = time.monotonic() + 10
    while window.progress.phase.key != "python" and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.02)

    answers = iter([False, True])
    asked = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(k.get("default")) or next(answers))

    window._on_close()  # "No": keeps going
    assert window.runner.running and window.state == "running"

    window._on_close()  # "Yes": stops it
    deadline = time.monotonic() + 10
    while window.state == "running" and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.02)

    assert asked == ["no", "no"]  # the safe answer is the default
    assert window.state == "failed"
    assert window.title_label.cget("text") == "The update was stopped"
    assert [child.cget("text") for child in window.buttons.winfo_children()][-1] == "Try again"


def test_try_again_runs_the_update_again_without_waiting_for_the_app(tk_root, monkeypatch, tmp_path):
    marker = tmp_path / "failed-once"
    script = (
        "import os, sys\n"
        f"marker = {str(marker)!r}\n"
        f"print('handoff=' + os.environ.get({uw.UPDATE_HANDOFF_ENV!r}, ''))\n"
        "if not os.path.exists(marker):\n"
        "    open(marker, 'w').close()\n"
        "    print('✗ Update failed: network error')\n"
        "    sys.exit(1)\n"
        "print('✓ Update complete!')\n"
    )
    window = _run_window(tk_root, monkeypatch, tmp_path, script)
    assert window.state == "failed"

    window._retry()
    assert window.status_label.cget("text") == "Getting ready…"  # the app is already closed
    tk_root.update()
    assert window.status_label.cget("text") != "Waiting for Robo to close…"
    deadline = time.monotonic() + 20
    while window.state == "running" and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.02)

    assert window.state == "done"
    assert window.title_label.cget("text") == "Robo is up to date"
    assert window.log_lines.count("handoff=") == 2  # neither run waited on a pid
    assert "— Trying again —" in window.log_lines
