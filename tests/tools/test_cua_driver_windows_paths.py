"""cua-driver lookup on Windows covers the official installer's folders.

The installer (cua-driver-rs install.ps1) puts the binary in
%LOCALAPPDATA%\\Programs\\Cua\\cua-driver\\bin (a junction to
~\\.cua-driver\\packages\\current) and adds that folder to the User PATH
only, which a Robo process started before the install never sees.
"""

from __future__ import annotations

from types import SimpleNamespace

from tools.computer_use import cua_backend


def _windows_without_driver_on_path(tmp_path, monkeypatch):
    monkeypatch.delenv("ROBO_CUA_DRIVER_CMD", raising=False)
    monkeypatch.setattr(cua_backend, "sys", SimpleNamespace(platform="win32"))
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    local_appdata = home / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    return home, local_appdata


def _exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ")
    path.chmod(0o755)
    return path


def test_finds_driver_in_programs_cua_folder(tmp_path, monkeypatch):
    _home, local_appdata = _windows_without_driver_on_path(tmp_path, monkeypatch)
    exe = _exe(local_appdata / "Programs" / "Cua" / "cua-driver" / "bin" / "cua-driver.exe")

    assert cua_backend.resolve_cua_driver_cmd() == str(exe)


def test_finds_driver_in_package_home(tmp_path, monkeypatch):
    home, _local_appdata = _windows_without_driver_on_path(tmp_path, monkeypatch)
    exe = _exe(home / ".cua-driver" / "packages" / "current" / "cua-driver.exe")

    assert cua_backend.resolve_cua_driver_cmd() == str(exe)


def test_explicit_override_is_still_authoritative(tmp_path, monkeypatch):
    _home, local_appdata = _windows_without_driver_on_path(tmp_path, monkeypatch)
    _exe(local_appdata / "Programs" / "Cua" / "cua-driver" / "bin" / "cua-driver.exe")
    monkeypatch.setenv("ROBO_CUA_DRIVER_CMD", str(tmp_path / "missing" / "cua-driver.exe"))

    assert cua_backend.resolve_cua_driver_cmd() is None
