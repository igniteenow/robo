"""``robo desktop`` skips ``npm ci`` when the packages already match the lockfile.

The build stamp covers the SOURCE, so every update used to mean a full
reinstall of every workspace's packages (plus the Electron download) before
the rebuild — minutes of quiet work that changed nothing. These pin the
rule: lockfile + workspace manifests unchanged since the last successful
install AND the build toolchain in place → the install is skipped; any doubt
reinstalls.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from robo_cli import main as cli_main


def _ns() -> argparse.Namespace:
    return argparse.Namespace(
        skip_build=False,
        build_only=False,
        force_build=False,
        source=False,
        fake_boot=False,
        ignore_existing=False,
        robo_root=None,
        cwd=None,
        foreground=False,
    )


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "robo-engineer"
    desktop = root / "apps" / "desktop"
    desktop.mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({"name": "robo", "workspaces": ["apps/*"]}), encoding="utf-8")
    (root / "package-lock.json").write_text('{"lockfileVersion": 3}', encoding="utf-8")
    (desktop / "package.json").write_text('{"name": "robo-desktop"}', encoding="utf-8")
    return root


def _install_toolchain(root: Path) -> None:
    for pkg in cli_main._DESKTOP_TOOLCHAIN_PACKAGES:
        pkg_dir = root / "node_modules" / pkg
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "package.json").write_text("{}", encoding="utf-8")
    binary = cli_main._electron_dist_binary(root)
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("", encoding="utf-8")


@pytest.fixture
def root(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.setattr(cli_main, "PROJECT_ROOT", root)
    return root


def test_no_stamp_means_install(root):
    _install_toolchain(root)
    assert cli_main._desktop_deps_current(root) is False


def test_recorded_install_with_toolchain_is_current(root):
    _install_toolchain(root)
    cli_main._record_desktop_deps(root)
    assert cli_main._desktop_deps_current(root) is True


def test_a_changed_lockfile_or_workspace_manifest_defeats_the_skip(root):
    _install_toolchain(root)
    cli_main._record_desktop_deps(root)
    (root / "package-lock.json").write_text('{"lockfileVersion": 3, "x": 1}', encoding="utf-8")
    assert cli_main._desktop_deps_current(root) is False

    cli_main._record_desktop_deps(root)
    assert cli_main._desktop_deps_current(root) is True
    (root / "apps" / "desktop" / "package.json").write_text('{"name": "robo-desktop", "v": 2}', encoding="utf-8")
    assert cli_main._desktop_deps_current(root) is False


def test_a_missing_tool_or_electron_binary_defeats_the_skip(root):
    _install_toolchain(root)
    cli_main._record_desktop_deps(root)
    cli_main._electron_dist_binary(root).unlink()
    assert cli_main._desktop_deps_current(root) is False

    _install_toolchain(root)
    assert cli_main._desktop_deps_current(root) is True
    (root / "node_modules" / "vite" / "package.json").unlink()
    assert cli_main._desktop_deps_current(root) is False


def test_toolchain_may_live_under_the_desktop_workspace(root):
    _install_toolchain(root)
    # npm sometimes keeps a workspace devDependency local instead of hoisting it.
    (root / "node_modules" / "typescript" / "package.json").unlink()
    local = root / "apps" / "desktop" / "node_modules" / "typescript"
    local.mkdir(parents=True)
    (local / "package.json").write_text("{}", encoding="utf-8")
    assert cli_main._desktop_toolchain_ready(root) is True


def test_no_lockfile_never_skips(root):
    _install_toolchain(root)
    cli_main._record_desktop_deps(root)
    (root / "package-lock.json").unlink()
    assert cli_main._desktop_deps_current(root) is False


def test_stamp_is_per_checkout(root, tmp_path, monkeypatch):
    _install_toolchain(root)
    cli_main._record_desktop_deps(root)
    other = tmp_path / "other-checkout"
    assert cli_main._desktop_deps_stamp_path(root) != cli_main._desktop_deps_stamp_path(other)


class _FakeChild:
    pid = 4242

    def poll(self):
        return None


def _packaged_executable(root: Path, monkeypatch) -> Path:
    # darwin, as in test_gui_command: the Linux launch path checks for
    # Electron's sandbox helper, which has nothing to do with the install.
    monkeypatch.setattr(cli_main.sys, "platform", "darwin")
    exe = root / "apps" / "desktop" / "release" / "mac-arm64" / "Robo.app" / "Contents" / "MacOS" / "Robo"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    return exe


def _run_gui(root, tmp_path, *, install_result):
    pack_ok = subprocess.CompletedProcess(["npm", "run", "pack"], 0)
    with patch("robo_cli.main.shutil.which", return_value="/usr/bin/npm"), \
         patch("robo_cli.main._run_npm_install_deterministic", return_value=install_result) as mock_install, \
         patch("robo_cli.main._desktop_build_needed", return_value=True), \
         patch("robo_cli.main._write_desktop_build_stamp"), \
         patch("robo_cli.main._desktop_macos_relaunchable_fixup"), \
         patch("robo_cli.main.subprocess.run", side_effect=[pack_ok]) as mock_run, \
         patch.multiple("robo_cli.main", _desktop_stdio_log_path=lambda: tmp_path / "desktop-stdio.log"), \
         patch("robo_cli.main.subprocess.Popen", return_value=_FakeChild()), \
         pytest.raises(SystemExit) as exc:
        cli_main.cmd_gui(_ns())
    assert exc.value.code == 0
    return mock_install, mock_run


def test_robo_desktop_skips_the_install_when_packages_are_current(root, tmp_path, monkeypatch, capsys):
    _packaged_executable(root, monkeypatch)  # sets the platform the binary name follows
    _install_toolchain(root)
    cli_main._record_desktop_deps(root)

    mock_install, mock_run = _run_gui(root, tmp_path, install_result=subprocess.CompletedProcess(["npm", "ci"], 0))

    mock_install.assert_not_called()
    assert mock_run.call_args_list[0].args[0] == ["/usr/bin/npm", "run", "pack"]
    out = capsys.readouterr().out
    assert "skipping the install" in out
    assert "Building desktop packaged app" in out


def test_robo_desktop_installs_and_records_when_packages_are_stale(root, tmp_path, monkeypatch, capsys):
    _packaged_executable(root, monkeypatch)
    _install_toolchain(root)
    assert cli_main._desktop_deps_current(root) is False

    mock_install, _mock_run = _run_gui(root, tmp_path, install_result=subprocess.CompletedProcess(["npm", "ci"], 0))

    mock_install.assert_called_once()
    assert mock_install.call_args.kwargs["extra_args"] == ("--no-fund", "--no-audit", "--prefer-offline", "--progress=false")
    assert "Installing desktop packages" in capsys.readouterr().out
    # The successful install was recorded: the next `robo desktop` skips it.
    assert cli_main._desktop_deps_current(root) is True


def test_a_failed_install_is_not_recorded(root, tmp_path, monkeypatch):
    _packaged_executable(root, monkeypatch)
    _install_toolchain(root)
    failed = subprocess.CompletedProcess(["npm", "ci"], 1)

    with patch("robo_cli.main.shutil.which", return_value="/usr/bin/npm"), \
         patch("robo_cli.main._run_npm_install_deterministic", return_value=failed), \
         patch("robo_cli.main._desktop_build_needed", return_value=True), \
         patch("robo_cli.main._electron_pkg_staged_missing_dist", return_value=False), \
         pytest.raises(SystemExit) as exc:
        cli_main.cmd_gui(_ns())
    assert exc.value.code == 1
    assert cli_main._desktop_deps_current(root) is False
