"""Codex / Copilot CLIs installed with npm are launched by resolved path.

On Windows they are npm .cmd shims, which CreateProcess cannot start from the
bare name; with Robo's own Node they can also live in <ROBO_HOME>\\node, which
is not always on PATH. The spawn uses resolve_cli_command() (its Windows
lookup is covered in tests/test_robo_node_path_helpers.py); a CLI that is
nowhere keeps its bare name so the existing "not found" message still shows.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# These tests stand in for Windows on a POSIX host (they patch sys.platform
# and use POSIX file modes and shell shims); Linux CI runs them. On a real
# Windows machine the same behavior is checked by hand.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="simulates Windows on a POSIX host"
)


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def lookup(tmp_path, monkeypatch):
    from robo_constants import iter_robo_node_dirs

    monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo-home"))
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    managed = iter_robo_node_dirs()[0]
    managed.mkdir(parents=True)
    return SimpleNamespace(path_dir=empty, managed=managed)


class TestCheckCodexBinary:
    @staticmethod
    def _run(monkeypatch, *, raise_not_found=False):
        from agent.transports import codex_app_server

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if raise_not_found:
                raise FileNotFoundError(cmd[0])
            return SimpleNamespace(returncode=0, stdout="codex-cli 99.0.0\n", stderr="")

        monkeypatch.setattr(codex_app_server.subprocess, "run", fake_run)
        return calls, codex_app_server.check_codex_binary

    def test_runs_the_resolved_codex(self, lookup, monkeypatch):
        import robo_constants

        monkeypatch.setattr(
            robo_constants, "resolve_cli_command", lambda c: rf"C:\robo\node\{c}.cmd"
        )
        calls, check = self._run(monkeypatch)

        ok, _msg = check()

        assert ok is True
        assert calls == [[r"C:\robo\node\codex.cmd", "--version"]]

    def test_prefers_codex_on_path(self, lookup, monkeypatch):
        on_path = _exe(lookup.path_dir / "codex")
        _exe(lookup.managed / "codex")
        calls, check = self._run(monkeypatch)

        check()

        assert calls == [[str(on_path), "--version"]]

    def test_missing_codex_keeps_the_install_message(self, lookup, monkeypatch):
        # Also when Robo's Node dir has a POSIX codex shim: outside PATH it
        # could not find `node`, so it must not be picked on POSIX.
        _exe(lookup.managed / "codex")
        calls, check = self._run(monkeypatch, raise_not_found=True)

        ok, msg = check()

        assert ok is False
        assert calls == [["codex", "--version"]]
        assert "npm i -g @openai/codex" in msg

    def test_explicit_path_is_used_as_given(self, lookup, monkeypatch):
        calls, check = self._run(monkeypatch)

        check("/opt/codex/bin/codex")

        assert calls == [["/opt/codex/bin/codex", "--version"]]


class TestCopilotSpawn:
    @staticmethod
    def _spawn(monkeypatch, command: str) -> tuple[list, Exception]:
        from agent import copilot_acp_client as mod

        popen_calls = []

        def fake_popen(cmd, **kwargs):
            popen_calls.append(list(cmd))
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(mod.subprocess, "Popen", fake_popen)
        client = mod.CopilotACPClient(acp_command=command, acp_args=["--acp", "--stdio"])
        with pytest.raises(RuntimeError) as excinfo:
            client._run_prompt("hi", timeout_seconds=1)
        return popen_calls, excinfo.value

    def test_launches_the_resolved_copilot(self, lookup, monkeypatch):
        import robo_constants

        monkeypatch.setattr(
            robo_constants, "resolve_cli_command", lambda c: rf"C:\robo\node\{c}.cmd"
        )

        calls, _err = self._spawn(monkeypatch, "copilot")

        assert calls == [[r"C:\robo\node\copilot.cmd", "--acp", "--stdio"]]

    def test_copilot_on_path_is_launched_by_full_path(self, lookup, monkeypatch):
        on_path = _exe(lookup.path_dir / "copilot")

        calls, _err = self._spawn(monkeypatch, "copilot")

        assert calls == [[str(on_path), "--acp", "--stdio"]]

    def test_missing_copilot_keeps_the_readable_error(self, lookup, monkeypatch):
        calls, err = self._spawn(monkeypatch, "copilot")

        assert calls == [["copilot", "--acp", "--stdio"]]
        assert "Could not start Copilot ACP command 'copilot'" in str(err)


def test_resolution_matches_what_popen_would_find(lookup):
    """The resolved path is the same file a POSIX exec would pick from PATH."""
    from robo_constants import resolve_cli_command

    on_path = _exe(lookup.path_dir / "codex")

    assert resolve_cli_command("codex") == str(on_path)
    assert subprocess.run([resolve_cli_command("codex")], check=False).returncode == 0
