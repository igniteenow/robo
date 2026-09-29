"""Install hints name a command that works on the user's OS.

Windows users were told to run `apt install ...` or `curl ... | sh`. The
Linux/macOS wording must stay exactly as before.
"""

import sys
from types import SimpleNamespace

import pytest

# These tests stand in for Windows on a POSIX host (they patch sys.platform
# and use POSIX file modes and shell shims); Linux CI runs them. On a real
# Windows machine the same behavior is checked by hand.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="simulates Windows on a POSIX host"
)


class TestOpenSSHHint:
    @pytest.fixture
    def ssh_mod(self, monkeypatch):
        from tools.environments import ssh

        monkeypatch.setattr(ssh.shutil, "which", lambda name, *a, **k: None)
        return ssh

    def test_windows_points_at_the_optional_feature(self, ssh_mod, monkeypatch):
        monkeypatch.setattr(ssh_mod.sys, "platform", "win32")

        with pytest.raises(RuntimeError) as excinfo:
            ssh_mod._ensure_ssh_available()

        message = str(excinfo.value)
        assert "Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0" in message
        assert "apt" not in message

    def test_linux_message_is_unchanged(self, ssh_mod, monkeypatch):
        monkeypatch.setattr(ssh_mod.sys, "platform", "linux")

        with pytest.raises(RuntimeError) as excinfo:
            ssh_mod._ensure_ssh_available()

        assert str(excinfo.value) == (
            "SSH is not installed or not in PATH. Install OpenSSH client: apt install openssh-client"
        )

    def test_macos_does_not_suggest_apt(self, ssh_mod, monkeypatch):
        monkeypatch.setattr(ssh_mod.sys, "platform", "darwin")

        assert "apt" not in ssh_mod._openssh_install_hint()


class TestVoiceInstallHint:
    @pytest.fixture
    def voice(self, monkeypatch):
        from tools import voice_mode

        monkeypatch.setattr(voice_mode, "_is_termux_environment", lambda: False)
        return voice_mode

    @staticmethod
    def _windows_venv(voice, monkeypatch, exe=r"C:\Users\u\.robo\robo-engineer\.venv\Scripts\python.exe"):
        fake_sys = SimpleNamespace(
            prefix=exe.rsplit("\\Scripts", 1)[0],
            base_prefix=r"C:\Python313",
            platform="win32",
            executable=exe,
        )
        monkeypatch.setattr(voice, "sys", fake_sys)
        return exe

    def test_windows_venv_uses_the_running_interpreter(self, voice, monkeypatch):
        exe = self._windows_venv(voice, monkeypatch)
        monkeypatch.setattr(voice, "_pip_available", lambda: True)

        assert voice._voice_capture_install_hint() == f"{exe} -m pip install sounddevice numpy"

    def test_windows_path_with_spaces_uses_the_call_operator(self, voice, monkeypatch):
        exe = self._windows_venv(voice, monkeypatch, exe=r"C:\Users\Jo Smith\robo\.venv\Scripts\python.exe")
        monkeypatch.setattr(voice, "_pip_available", lambda: True)

        assert voice._voice_capture_install_hint() == f'& "{exe}" -m pip install sounddevice numpy'

    def test_windows_venv_without_pip_bootstraps_it_first(self, voice, monkeypatch):
        exe = self._windows_venv(voice, monkeypatch)
        monkeypatch.setattr(voice, "_pip_available", lambda: False)

        assert voice._voice_capture_install_hint() == (
            f"{exe} -m ensurepip --upgrade, then {exe} -m pip install sounddevice numpy"
        )

    def test_posix_venv_hint_is_unchanged(self, voice, tmp_path, monkeypatch):
        pip = tmp_path / "bin" / "pip"
        pip.parent.mkdir()
        pip.write_text("", encoding="utf-8")
        fake_sys = SimpleNamespace(
            prefix=str(tmp_path), base_prefix="/usr", platform="linux", executable=str(tmp_path / "bin" / "python")
        )
        monkeypatch.setattr(voice, "sys", fake_sys)

        assert voice._voice_capture_install_hint() == f"{pip} install sounddevice numpy"


class TestOllamaOnWindows:
    @pytest.fixture
    def mem0_setup(self, monkeypatch):
        from plugins.memory.mem0 import _setup

        monkeypatch.setattr(_setup.shutil, "which", lambda name, *a, **k: None)
        monkeypatch.setattr(_setup, "_check_ollama", lambda url: (False, ""))
        monkeypatch.setattr(_setup, "_wait_for_port", lambda *a, **k: None)
        return _setup

    def test_finds_ollama_in_its_default_folder_when_not_on_path(self, mem0_setup, tmp_path, monkeypatch):
        exe = tmp_path / "Programs" / "Ollama" / "ollama.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("", encoding="utf-8")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setattr(mem0_setup.sys, "platform", "win32")
        started = []
        monkeypatch.setattr(
            mem0_setup.subprocess, "Popen", lambda cmd, **k: started.append(list(cmd))
        )

        mem0_setup._ensure_ollama([])

        assert started == [[str(exe), "serve"]]

    def test_windows_not_installed_suggests_winget(self, mem0_setup, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setattr(mem0_setup.sys, "platform", "win32")

        assert mem0_setup._ensure_ollama([]) is False

        out = capsys.readouterr().out
        assert "winget install Ollama.Ollama" in out
        assert "curl" not in out

    def test_linux_not_installed_hint_is_unchanged(self, mem0_setup, monkeypatch, capsys):
        monkeypatch.setattr(mem0_setup.sys, "platform", "linux")

        assert mem0_setup._ensure_ollama([]) is False

        out = capsys.readouterr().out
        assert "curl -fsSL https://ollama.com/install.sh | sh" in out
        assert "brew install ollama" in out
