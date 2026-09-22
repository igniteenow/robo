from __future__ import annotations

from robo_cli import main as cli_main


def test_robo_windows_desktop_executable_is_discovered(tmp_path, monkeypatch):
    desktop_dir = tmp_path / "apps" / "desktop"
    executable = desktop_dir / "release" / "win-unpacked" / "Robo.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ" + b"\0" * 1024)

    monkeypatch.setattr(cli_main.sys, "platform", "win32")
    monkeypatch.setattr(cli_main, "_expected_windows_pe_machines", lambda: set())

    assert cli_main._desktop_packaged_executable(desktop_dir) == executable


def test_robo_linux_desktop_executable_is_discovered(tmp_path, monkeypatch):
    desktop_dir = tmp_path / "apps" / "desktop"
    executable = desktop_dir / "release" / "linux-unpacked" / "Robo"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"robo")

    monkeypatch.setattr(cli_main.sys, "platform", "linux")

    assert cli_main._desktop_packaged_executable(desktop_dir) == executable
