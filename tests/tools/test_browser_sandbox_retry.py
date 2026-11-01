"""When Chromium's sandbox cannot start, the browser tool relaunches once with
--no-sandbox instead of leaving the browser dead.

The up-front detection covers root / Docker / AppArmor; this covers what it
cannot know in advance (Windows security software, Linux without user
namespaces, locked-down macOS): the first sandbox failure arms the bypass for
the process, the session is dropped so a fresh daemon picks up the flag, and
the same command runs again. It arms once, never for a page that merely
mentions "sandbox", and never over flags the person set themselves.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

import tools.browser_tool as bt


@pytest.fixture(autouse=True)
def _disarmed(monkeypatch):
    monkeypatch.setattr(bt, "_sandbox_bypass_forced", False)
    monkeypatch.delenv("AGENT_BROWSER_ARGS", raising=False)
    monkeypatch.delenv("AGENT_BROWSER_CHROME_FLAGS", raising=False)
    yield
    bt._sandbox_bypass_forced = False


class TestDetection:
    @pytest.mark.parametrize(
        "error",
        [
            "Failed to launch the browser process! No usable sandbox! Update your kernel",
            "browserType.launch: Target crashed — sandbox_win.cc(123) Check failed",
            "Daemon process exited during startup: chrome sandbox could not be initialised",
            "[FATAL:zygote_host_impl_linux.cc(127)] No usable sandbox! Hint: run with --no-sandbox",
        ],
    )
    def test_sandbox_launch_failures_are_recognised(self, error):
        assert bt._looks_like_sandbox_failure({"success": False, "error": error}) is True

    @pytest.mark.parametrize(
        "result",
        [
            {"success": True, "data": {"url": "https://sandbox.example.com"}},
            {"success": False, "error": "Timeout navigating to https://sandbox.stripe.com/login"},
            {"success": False, "error": "Element not found: #sandbox-toggle"},
            {"success": False, "error": "Failed to launch the browser process! Missing libnss3.so"},
            # Windows: Chrome hands off to a running instance and exits 0; the
            # launcher's generic advice mentions --no-sandbox. Not a sandbox failure.
            {
                "success": False,
                "error": "Auto-launch failed: Chrome exited early (exit code: 0) without writing "
                "DevToolsActivePort\n(also tried parsing stderr) Chrome exited before providing "
                "DevTools URL (no stderr output from Chrome)\nHint: try --no-sandbox if Chrome cannot start",
            },
            "not a dict",
        ],
    )
    def test_everything_else_is_left_alone(self, result):
        assert bt._looks_like_sandbox_failure(result) is False


class TestArming:
    def test_arms_once_and_makes_the_bypass_needed(self, monkeypatch):
        monkeypatch.setattr(bt, "_running_in_docker", lambda: False)
        monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)

        assert bt._needs_chromium_sandbox_bypass() is False
        assert bt._arm_sandbox_bypass() is True
        assert bt._needs_chromium_sandbox_bypass() is True
        # A second failure cannot arm again, so a retry can never loop.
        assert bt._arm_sandbox_bypass() is False

    def test_never_overrides_the_persons_own_flags(self, monkeypatch):
        monkeypatch.setenv("AGENT_BROWSER_ARGS", "--disable-gpu")

        assert bt._arm_sandbox_bypass() is False
        assert bt._sandbox_bypass_forced is False


class TestRetry:
    """Drive _run_browser_command with a fake agent-browser: the first launch
    fails on the sandbox, the second succeeds."""

    def _run(self, stderr_by_call, stdout_by_call):
        calls = []
        envs = []
        current = {"n": -1}

        def fake_popen(cmd, **kwargs):
            current["n"] += 1
            calls.append(cmd)
            envs.append(dict(kwargs.get("env") or {}))
            proc = MagicMock()
            proc.wait.return_value = None
            proc.returncode = 0 if stdout_by_call[current["n"]] else 1
            return proc

        def fake_open(path, *a, **kw):
            text = ""
            if "_stderr_" in str(path):
                text = stderr_by_call[current["n"]]
            elif "_stdout_" in str(path):
                text = stdout_by_call[current["n"]]
            handle = MagicMock()
            handle.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=text)))
            handle.__exit__ = MagicMock(return_value=False)
            return handle

        cleaned = []

        with patch("tools.browser_tool._get_session_info", return_value={"session_name": "sess-1"}), \
             patch("tools.browser_tool._find_agent_browser", return_value="/usr/bin/agent-browser"), \
             patch("tools.browser_tool._is_local_mode", return_value=True), \
             patch("tools.browser_tool._chromium_installed", return_value=True), \
             patch("tools.browser_tool._get_cloud_provider", return_value=None), \
             patch("tools.browser_tool._get_cdp_override", return_value=""), \
             patch("tools.browser_tool._is_camofox_mode", return_value=False), \
             patch("tools.browser_tool._running_in_docker", return_value=False), \
             patch("tools.browser_tool._cleanup_single_browser_session", side_effect=cleaned.append), \
             patch("subprocess.Popen", side_effect=fake_popen), \
             patch("os.open", return_value=99), \
             patch("os.close"), \
             patch("os.unlink"), \
             patch("os.makedirs"), \
             patch("builtins.open", side_effect=fake_open), \
             patch("tools.interrupt.is_interrupted", return_value=False), \
             patch("tools.browser_tool._write_owner_pid"):
            result = bt._run_browser_command("task1", "open", ["https://example.com"])

        return result, calls, envs, cleaned

    def test_relaunches_once_with_no_sandbox_and_succeeds(self, monkeypatch):
        monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
        result, calls, envs, cleaned = self._run(
            stderr_by_call=["Failed to launch the browser process! No usable sandbox!", ""],
            stdout_by_call=["", '{"success": true, "data": {"url": "https://example.com"}}'],
        )

        assert result["success"] is True
        assert len(calls) == 2
        assert "AGENT_BROWSER_ARGS" not in envs[0]
        assert "--no-sandbox" in envs[1]["AGENT_BROWSER_ARGS"]
        # The old session (and its daemon) is dropped before the relaunch.
        assert cleaned == ["task1"]
        assert bt._sandbox_bypass_forced is True

    def test_a_second_sandbox_failure_is_reported_not_retried(self, monkeypatch):
        monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
        result, calls, _envs, cleaned = self._run(
            stderr_by_call=[
                "Failed to launch the browser process! No usable sandbox!",
                "Failed to launch the browser process! No usable sandbox!",
            ],
            stdout_by_call=["", ""],
        )

        assert result["success"] is False
        assert "sandbox" in result["error"].lower()
        assert len(calls) == 2
        assert cleaned == ["task1"]

    def test_other_failures_do_not_touch_the_sandbox_flag(self, monkeypatch):
        monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
        result, calls, _envs, cleaned = self._run(
            stderr_by_call=["Timeout navigating to https://sandbox.stripe.com", ""],
            stdout_by_call=["", ""],
        )

        assert result["success"] is False
        assert len(calls) == 1
        assert cleaned == []
        assert bt._sandbox_bypass_forced is False


class TestElevatedWindows:
    """Robo run as administrator on Windows: Chrome would relaunch itself
    de-elevated and the launch would read as a failure (one leaked headless
    Chrome per attempt); --do-not-de-elevate keeps it in place."""

    def test_flag_is_added_only_when_elevated_on_windows(self, monkeypatch):
        monkeypatch.setattr(bt, "_needs_chromium_sandbox_bypass", lambda: False)

        monkeypatch.setattr(bt, "_windows_process_is_elevated", lambda: True)
        assert bt._chromium_launch_flags() == ["--do-not-de-elevate"]

        monkeypatch.setattr(bt, "_windows_process_is_elevated", lambda: False)
        assert bt._chromium_launch_flags() == []

    def test_flags_combine_with_the_sandbox_bypass(self, monkeypatch):
        monkeypatch.setattr(bt, "_needs_chromium_sandbox_bypass", lambda: True)
        monkeypatch.setattr(bt, "_windows_process_is_elevated", lambda: True)

        assert bt._chromium_launch_flags() == ["--no-sandbox", "--disable-dev-shm-usage", "--do-not-de-elevate"]

    def test_not_windows_is_never_elevated(self, monkeypatch):
        monkeypatch.setattr(os, "name", "posix")
        assert bt._windows_process_is_elevated() is False

    def test_the_persons_own_flags_win(self, monkeypatch):
        monkeypatch.setattr(bt, "_windows_process_is_elevated", lambda: True)
        monkeypatch.setattr(bt, "_needs_chromium_sandbox_bypass", lambda: False)
        monkeypatch.setenv("AGENT_BROWSER_ARGS", "--disable-gpu")

        env = bt._build_browser_env()
        # _build_browser_env passes the person's value through untouched; the
        # injection in _run_browser_command only fills the key when absent.
        assert env.get("AGENT_BROWSER_ARGS") == "--disable-gpu"
