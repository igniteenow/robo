"""npm-installed language servers on Windows.

npm writes two shims into node_modules/.bin: an extensionless POSIX shell
script (CreateProcess cannot run it: WinError 193) and a .cmd that finds the
package relative to its own folder, so a copy of it elsewhere points nowhere.
On Windows the server is therefore run from node_modules/.bin via its .cmd.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.lsp import install as install_mod

# These tests stand in for Windows on a POSIX host (they patch sys.platform
# and use POSIX file modes and shell shims); Linux CI runs them. On a real
# Windows machine the same behavior is checked by hand.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="simulates Windows on a POSIX host"
)


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("shim\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def lsp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo-home"))
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    return install_mod.robo_lsp_bin_dir().parent


class TestNativeBinaryCandidates:
    def test_windows_offers_only_runnable_forms(self, monkeypatch):
        monkeypatch.setattr(install_mod, "_is_windows", lambda: True)
        base = Path("lsp") / "pyright-langserver"

        assert install_mod._native_binary_candidates(base) == [
            Path(str(base) + ".cmd"),
            Path(str(base) + ".exe"),
            Path(str(base) + ".bat"),
        ]

    def test_windows_name_with_a_launcher_suffix_is_kept(self, monkeypatch):
        monkeypatch.setattr(install_mod, "_is_windows", lambda: True)
        base = Path("lsp") / "gopls.exe"

        assert install_mod._native_binary_candidates(base) == [base]

    def test_posix_is_unchanged(self, monkeypatch):
        monkeypatch.setattr(install_mod, "_is_windows", lambda: False)
        base = Path("lsp") / "pyright-langserver"

        assert install_mod._native_binary_candidates(base) == [base]


class TestExistingBinary:
    def test_windows_finds_cmd_in_npm_bin_dir(self, lsp_home, monkeypatch):
        monkeypatch.setattr(install_mod, "_is_windows", lambda: True)
        nm_bin = lsp_home / "node_modules" / ".bin"
        _exe(nm_bin / "pyright-langserver")
        cmd = _exe(nm_bin / "pyright-langserver.cmd")

        assert install_mod._existing_binary("pyright-langserver") == str(cmd)

    def test_windows_ignores_the_extensionless_shim(self, lsp_home, monkeypatch):
        monkeypatch.setattr(install_mod, "_is_windows", lambda: True)
        _exe(lsp_home / "node_modules" / ".bin" / "pyright-langserver")

        assert install_mod._existing_binary("pyright-langserver") is None

    def test_staged_bin_still_wins(self, lsp_home, monkeypatch):
        monkeypatch.setattr(install_mod, "_is_windows", lambda: True)
        staged = _exe(lsp_home / "bin" / "pyright-langserver.cmd")
        _exe(lsp_home / "node_modules" / ".bin" / "pyright-langserver.cmd")

        assert install_mod._existing_binary("pyright-langserver") == str(staged)

    def test_posix_lookup_is_unchanged(self, lsp_home, tmp_path, monkeypatch):
        """POSIX keeps the lsp/bin symlink, then PATH - node_modules/.bin is
        not consulted, so a server on PATH is still the one used."""
        monkeypatch.setattr(install_mod, "_is_windows", lambda: False)
        _exe(lsp_home / "node_modules" / ".bin" / "pyright-langserver")
        on_path = _exe(tmp_path / "global-bin" / "pyright-langserver")
        monkeypatch.setenv("PATH", str(on_path.parent))

        assert install_mod._existing_binary("pyright-langserver") == str(on_path)


def _fake_npm_install(staging: Path, bin_name: str, captured: dict):
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        nm_bin = staging / "node_modules" / ".bin"
        _exe(nm_bin / bin_name)
        _exe(nm_bin / f"{bin_name}.cmd")
        return MagicMock(returncode=0, stderr="")

    return fake_run


class TestInstallNpm:
    def test_windows_returns_the_cmd_shim_where_npm_put_it(self, lsp_home, monkeypatch):
        monkeypatch.setattr(install_mod, "_is_windows", lambda: True)
        monkeypatch.setattr(install_mod, "find_node_executable", lambda cmd: "/managed/npm")
        captured = {}
        monkeypatch.setattr(
            install_mod.subprocess, "run", _fake_npm_install(lsp_home, "pyright-langserver", captured)
        )

        result = install_mod._install_npm("pyright", "pyright-langserver")

        assert result == str(lsp_home / "node_modules" / ".bin" / "pyright-langserver.cmd")
        assert list((lsp_home / "bin").iterdir()) == []

    def test_posix_still_links_into_lsp_bin(self, lsp_home, monkeypatch):
        monkeypatch.setattr(install_mod, "_is_windows", lambda: False)
        monkeypatch.setattr(install_mod, "find_node_executable", lambda cmd: "/managed/npm")
        captured = {}
        monkeypatch.setattr(
            install_mod.subprocess, "run", _fake_npm_install(lsp_home, "pyright-langserver", captured)
        )

        result = install_mod._install_npm("pyright", "pyright-langserver")

        assert result == str(lsp_home / "bin" / "pyright-langserver")
        assert (lsp_home / "bin" / "pyright-langserver").exists()

    def test_npm_runs_with_robo_node_on_path(self, lsp_home, tmp_path, monkeypatch):
        from robo_constants import iter_robo_node_dirs

        node_dir = iter_robo_node_dirs()[0]
        node_dir.mkdir(parents=True)
        monkeypatch.setattr(install_mod, "find_node_executable", lambda cmd: "/managed/npm")
        captured = {}
        monkeypatch.setattr(
            install_mod.subprocess, "run", _fake_npm_install(lsp_home, "pyright-langserver", captured)
        )

        install_mod._install_npm("pyright", "pyright-langserver")

        assert captured["cmd"][0] == "/managed/npm"
        assert str(node_dir) in captured["env"]["PATH"].split(os.pathsep)


class TestClientSpawnEnv:
    @staticmethod
    def _spawn_env(monkeypatch, **client_kwargs) -> dict:
        import asyncio

        from agent.lsp import client as client_mod

        captured = {}

        async def fake_exec(*cmd, **kwargs):
            captured["env"] = kwargs.get("env")
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(client_mod.asyncio, "create_subprocess_exec", fake_exec)
        lsp = client_mod.LSPClient(
            server_id="pyright",
            workspace_root=os.getcwd(),
            command=["pyright-langserver", "--stdio"],
            **client_kwargs,
        )
        with pytest.raises(client_mod.LSPProtocolError):
            asyncio.run(lsp._spawn())
        return captured["env"]

    def test_robo_node_dir_is_appended_after_existing_path(self, tmp_path, monkeypatch):
        from robo_constants import iter_robo_node_dirs

        monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo-home"))
        node_dir = iter_robo_node_dirs()[0]
        node_dir.mkdir(parents=True)
        monkeypatch.setenv("PATH", os.pathsep.join(["/first", "/second"]))

        env = self._spawn_env(monkeypatch)

        entries = env["PATH"].split(os.pathsep)
        assert entries[:2] == ["/first", "/second"]
        assert str(node_dir) in entries[2:]

    def test_server_specific_env_still_wins(self, tmp_path, monkeypatch):
        from robo_constants import iter_robo_node_dirs

        monkeypatch.setenv("ROBO_HOME", str(tmp_path / "robo-home"))
        iter_robo_node_dirs()[0].mkdir(parents=True)

        env = self._spawn_env(monkeypatch, env={"PATH": "/only-this"})

        assert env["PATH"] == "/only-this"
