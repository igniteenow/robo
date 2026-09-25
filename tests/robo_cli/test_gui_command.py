"""Tests for ``robo gui`` desktop launcher wiring."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from robo_cli import main as cli_main


def _ns(**kw):
    defaults = dict(
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
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class _FakeChild:
    pid = 4242


def _same_exe(argv: list, exe: Path) -> bool:
    """The launched executable is *exe* — compared the way the host filesystem
    does. A Windows checkout resolves the Linux fixture's `robo` as `Robo`
    (case-insensitive NTFS), which is the same file, not a different launch."""
    import os

    return len(argv) >= 1 and os.path.normcase(str(argv[0])) == os.path.normcase(str(exe))


def _detached_launch(tmp_path: Path):
    """Patch the detached launch's spawn + sidecar log so a test never touches
    the real ROBO_HOME or starts a process. Yields the Popen mock."""
    return patch.multiple(
        "robo_cli.main",
        _desktop_stdio_log_path=lambda: tmp_path / "desktop-stdio.log",
    ), patch("robo_cli.main.subprocess.Popen", return_value=_FakeChild())


def _make_desktop_tree(tmp_path: Path) -> Path:
    root = tmp_path / "robo-engineer"
    desktop_dir = root / "apps" / "desktop"
    desktop_dir.mkdir(parents=True)
    (desktop_dir / "package.json").write_text("{}", encoding="utf-8")
    return root


def _make_packaged_executable(root: Path, monkeypatch, platform: str = "darwin") -> Path:
    monkeypatch.setattr(cli_main.sys, "platform", platform)
    desktop_dir = root / "apps" / "desktop"
    if platform == "darwin":
        exe = desktop_dir / "release" / "mac-arm64" / "Robo.app" / "Contents" / "MacOS" / "Robo"
    elif platform == "win32":
        exe = desktop_dir / "release" / "win-unpacked" / "Robo.exe"
    else:
        exe = desktop_dir / "release" / "linux-unpacked" / "robo"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    return exe


def test_gui_installs_packages_and_launches_desktop_app(tmp_path, monkeypatch):
    root = _make_desktop_tree(tmp_path)
    desktop_dir = root / "apps" / "desktop"
    monkeypatch.setattr(cli_main, "PROJECT_ROOT", root)
    packaged_exe = _make_packaged_executable(root, monkeypatch)

    install_ok = subprocess.CompletedProcess(["npm", "ci"], 0)
    pack_ok = subprocess.CompletedProcess(["npm", "run", "pack"], 0)
    log_patch, popen_patch = _detached_launch(tmp_path)

    with patch("robo_cli.main.shutil.which", return_value="/usr/bin/npm"), \
         patch("robo_cli.main._run_npm_install_deterministic", return_value=install_ok) as mock_install, \
         patch("robo_cli.main._desktop_build_needed", return_value=True), \
         patch("robo_cli.main._write_desktop_build_stamp"), \
         patch("robo_cli.main._desktop_macos_relaunchable_fixup"), \
         patch("robo_cli.main.subprocess.run", side_effect=[pack_ok]) as mock_run, \
         log_patch, popen_patch as mock_popen, \
         pytest.raises(SystemExit) as exc:
        cli_main.cmd_gui(_ns())

    assert exc.value.code == 0
    # The install now runs with a resolved env (managed-Node PATH), never a bare
    # ``env=None`` that would leave npm's child scripts unable to find ``node``.
    mock_install.assert_called_once()
    assert mock_install.call_args.args == ("/usr/bin/npm", root)
    assert mock_install.call_args.kwargs["capture_output"] is False
    install_env = mock_install.call_args.kwargs["env"]
    assert install_env is not None and "PATH" in install_env
    # The build is a blocking run; the LAUNCH is a detached spawn that returns
    # at once — the app must outlive the terminal that started it.
    assert mock_run.call_args_list == [mock_run.call_args_list[0]]
    assert mock_run.call_args_list[0].args[0] == ["/usr/bin/npm", "run", "pack"]
    assert mock_run.call_args_list[0].kwargs["cwd"] == desktop_dir
    mock_popen.assert_called_once()
    assert _same_exe(mock_popen.call_args.args[0], packaged_exe)
    assert mock_popen.call_args.kwargs["cwd"] == desktop_dir
    assert mock_popen.call_args.kwargs["stdin"] is subprocess.DEVNULL
    assert mock_popen.call_args.kwargs["close_fds"] is True
    assert mock_popen.call_args.kwargs["start_new_session"] is True  # darwin: own session


def test_gui_foreground_keeps_the_old_attached_launch(tmp_path, monkeypatch):
    """--foreground: Electron stays attached to this terminal and its exit
    code is mirrored — the debugging run."""
    root = _make_desktop_tree(tmp_path)
    desktop_dir = root / "apps" / "desktop"
    monkeypatch.setattr(cli_main, "PROJECT_ROOT", root)
    packaged_exe = _make_packaged_executable(root, monkeypatch)

    launch_done = subprocess.CompletedProcess([str(packaged_exe)], 3)

    with patch("robo_cli.main._desktop_build_needed", return_value=False), \
         patch("robo_cli.main._resolve_node_runtime_npm", return_value="/usr/bin/npm"), \
         patch("robo_cli.main._desktop_macos_relaunchable_fixup"), \
         patch("robo_cli.main.subprocess.run", return_value=launch_done) as mock_run, \
         patch("robo_cli.main.subprocess.Popen") as mock_popen, \
         pytest.raises(SystemExit) as exc:
        cli_main.cmd_gui(_ns(foreground=True))

    assert exc.value.code == 3
    assert _same_exe(mock_run.call_args.args[0], packaged_exe)
    assert mock_run.call_args.kwargs["cwd"] == desktop_dir
    mock_popen.assert_not_called()


def test_launch_desktop_detached_on_windows_uses_the_gateway_detach_bundle(tmp_path, monkeypatch):
    """Windows: own process group + hidden console + job breakaway, no inherited
    stdio, and Electron told not to attach to the launching console."""
    from robo_cli._subprocess_compat import windows_detach_flags

    monkeypatch.setattr(cli_main.sys, "platform", "win32")
    log_patch, popen_patch = _detached_launch(tmp_path)

    with log_patch, popen_patch as mock_popen:
        rc = cli_main._launch_desktop_detached([r"C:\\app\\Robo.exe"], cwd=tmp_path, env={"PATH": "x"})

    assert rc == 0
    kwargs = mock_popen.call_args.kwargs
    assert kwargs["creationflags"] == windows_detach_flags()
    assert "start_new_session" not in kwargs
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["close_fds"] is True
    assert kwargs["env"]["ELECTRON_NO_ATTACH_CONSOLE"] == "1"
    assert kwargs["env"]["PATH"] == "x"
    assert (tmp_path / "desktop-stdio.log").exists()


def test_launch_desktop_detached_retries_without_job_breakaway(tmp_path, monkeypatch):
    """A job object that forbids breakaway makes the first spawn fail with
    OSError; the hidden-console spawn without the breakaway bit still goes."""
    from robo_cli._subprocess_compat import windows_detach_flags_without_breakaway

    monkeypatch.setattr(cli_main.sys, "platform", "win32")
    log_patch, popen_patch = _detached_launch(tmp_path)

    with log_patch, popen_patch as mock_popen:
        mock_popen.side_effect = [OSError("access denied"), _FakeChild()]
        rc = cli_main._launch_desktop_detached(["Robo.exe"], cwd=tmp_path, env={})

    assert rc == 0
    assert mock_popen.call_count == 2
    assert mock_popen.call_args_list[1].kwargs["creationflags"] == windows_detach_flags_without_breakaway()


def test_launch_desktop_detached_reports_a_spawn_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_main.sys, "platform", "linux")
    log_patch, popen_patch = _detached_launch(tmp_path)

    with log_patch, popen_patch as mock_popen:
        mock_popen.side_effect = OSError("no such file")
        rc = cli_main._launch_desktop_detached(["/nope/robo"], cwd=tmp_path, env={})

    assert rc == 1
    assert "Could not start Robo Desktop" in capsys.readouterr().out


def test_gui_install_env_prepends_managed_node_on_bare_path(tmp_path, monkeypatch):
    """Regression: npm's child scripts (electron-winstaller's select-7z-arch.js)
    shell out to bare ``node``. When Desktop is launched from the updater chain
    the parent PATH is stripped, so the install env MUST carry the Robo-managed
    Node ahead of that bare PATH or the install dies with ``node: not found``.
    """
    import os

    from robo_constants import iter_robo_node_dirs

    root = _make_desktop_tree(tmp_path)
    monkeypatch.setattr(cli_main, "PROJECT_ROOT", root)
    _make_packaged_executable(root, monkeypatch, platform="win32")

    # A managed Node tree on disk so with_robo_node_path() actually prepends it.
    home = tmp_path / "robo-home"
    (home / "node" / "bin").mkdir(parents=True)
    monkeypatch.setenv("ROBO_HOME", str(home))
    # Simulate the stripped PATH the desktop updater chain hands us.
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/bin"]))

    install_ok = subprocess.CompletedProcess(["npm", "ci"], 0)
    log_patch, popen_patch = _detached_launch(tmp_path)

    with patch("robo_cli.main._resolve_node_runtime_npm", return_value="/usr/bin/npm"), \
         patch("robo_cli.main._run_npm_install_deterministic", return_value=install_ok) as mock_install, \
         patch("robo_cli.main._desktop_build_needed", return_value=True), \
         patch("robo_cli.main._write_desktop_build_stamp"), \
         patch("robo_cli.main.subprocess.run", side_effect=[subprocess.CompletedProcess([], 0)]), \
         log_patch, popen_patch, \
         pytest.raises(SystemExit):
        cli_main.cmd_gui(_ns(skip_build=False))

    managed_dirs = [str(p) for p in iter_robo_node_dirs() if p.is_dir()]
    assert managed_dirs, "managed node tree not discovered"
    install_env = mock_install.call_args.kwargs["env"]
    path_parts = install_env["PATH"].split(os.pathsep)
    assert path_parts[: len(managed_dirs)] == managed_dirs
    assert "/usr/bin" in path_parts  # the bare updater PATH is preserved, just after managed Node








# ── Content-hash stamp tests ──────────────────────────────────────────








# ── Electron build-cache recovery tests ───────────────────────────────


def _write_zip(path: Path) -> None:
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("electron", "fake binary payload")


def test_purge_electron_build_cache_clears_all_zips_and_unpacked_dir(tmp_path, monkeypatch):
    """Purge is unconditional: it removes every electron-*.zip (regardless of
    whether stdlib zipfile thinks it's corrupt) plus the half-written unpacked
    dir, because @electron/get's own SHASUM check on re-download is the real
    validator — not a self-rolled one."""
    cache = tmp_path / "electron-cache"
    # A "clean" zip and a prepended-junk zip — the latter is the real-world
    # corruption that zipfile.testzip() silently passes (it reads from the
    # end-of-central-directory backward), which is why we don't gate on it.
    clean = cache / "electron-v40.9.3-linux-x64.zip"
    prepended = cache / "hashdir" / "electron-v40.9.3-linux-x64.zip"
    _write_zip(clean)
    _write_zip(prepended)
    prepended.write_bytes(b"\x00" * 4096 + prepended.read_bytes())

    desktop_dir = tmp_path / "apps" / "desktop"
    unpacked = desktop_dir / "release" / "linux-unpacked"
    unpacked.mkdir(parents=True)
    (unpacked / "LICENSE.electron.txt").write_text("x", encoding="utf-8")
    (unpacked / "resources.pak").write_text("x", encoding="utf-8")

    monkeypatch.setattr(cli_main, "_electron_download_cache_dirs", lambda: [cache])

    removed = cli_main._purge_electron_build_cache(desktop_dir)

    assert clean in removed
    assert prepended in removed
    assert unpacked in removed
    assert not clean.exists()
    assert not prepended.exists()
    assert not unpacked.exists()




def test_gui_does_not_retry_after_packaged_executable_exists(tmp_path, monkeypatch, capsys):
    """A build that already produced a packaged executable did NOT fail from the
    Electron-download problem the cache purge + mirror retries exist to repair.

    Regression for #40187: a late failure such as macOS code signing leaves
    Robo.app/Contents/MacOS/Robo in place. Re-downloading Electron can't
    repair a signing failure, so the destructive purge + slow mirror retry must
    be skipped — we fail directly instead of grinding through an identical retry.
    """
    root = _make_desktop_tree(tmp_path)
    monkeypatch.setattr(cli_main, "PROJECT_ROOT", root)
    # Executable EXISTS at failure time → late failure, not a corrupt download.
    _make_packaged_executable(root, monkeypatch, platform="darwin")
    monkeypatch.delenv("ELECTRON_MIRROR", raising=False)

    install_ok = subprocess.CompletedProcess(["npm", "ci"], 0)
    pack_fail = subprocess.CompletedProcess(["npm", "run", "pack"], 1)

    with patch("robo_cli.main.shutil.which", return_value="/usr/bin/npm"), \
         patch("robo_cli.main._run_npm_install_deterministic", return_value=install_ok), \
         patch("robo_cli.main._desktop_macos_relaunchable_fixup"), \
         patch("robo_cli.main._purge_electron_build_cache", return_value=[Path("/c/electron.zip")]) as mock_purge, \
         patch("robo_cli.main._redownload_electron_dist", return_value=True) as mock_dl, \
         patch("robo_cli.main.subprocess.run", return_value=pack_fail) as mock_run, \
         pytest.raises(SystemExit) as exc:
        cli_main.cmd_gui(_ns())

    assert exc.value.code == 1
    # Neither destructive recovery runs, and there is exactly ONE pack attempt.
    mock_purge.assert_not_called()
    mock_dl.assert_not_called()
    assert mock_run.call_count == 1
    assert "Desktop GUI build failed" in capsys.readouterr().out




# ── electronDist (re)download helper tests (#47266) ───────────────────


@pytest.mark.parametrize(
    "platform,rel",
    [
        ("linux", "dist/electron"),
        ("win32", "dist/electron.exe"),
        ("darwin", "dist/Electron.app/Contents/MacOS/Electron"),
    ],
)
def test_electron_dist_ok_per_platform(tmp_path, monkeypatch, platform, rel):
    monkeypatch.setattr(cli_main.sys, "platform", platform)
    electron = tmp_path / "node_modules" / "electron"
    # A dist dir that exists but lacks the binary is NOT ok (partial extraction).
    (electron / "dist").mkdir(parents=True)
    assert cli_main._electron_dist_ok(tmp_path) is False

    binp = electron / rel
    binp.parent.mkdir(parents=True, exist_ok=True)
    binp.write_text("", encoding="utf-8")
    assert cli_main._electron_dist_ok(tmp_path) is True










class _FakeProc:
    """Minimal psutil.Process stand-in for the lock-breaker tests."""

    def __init__(self, pid: int, exe: str | None):
        self.pid = pid
        self.info = {"pid": pid, "exe": exe}
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True












# --- macOS TCC-stable local signing (relaunch fixup) -----------------------


def _write_info_plist(bundle: Path, identifier: str) -> None:
    import plistlib

    info = bundle / "Contents" / "Info.plist"
    info.parent.mkdir(parents=True, exist_ok=True)
    info.write_bytes(plistlib.dumps({"CFBundleIdentifier": identifier}))


def _make_signable_app(desktop_dir: Path) -> Path:
    """Build a fake packaged Robo.app with the pieces the signer must find."""
    ent_dir = desktop_dir / "electron"
    ent_dir.mkdir(parents=True, exist_ok=True)
    (ent_dir / "entitlements.mac.plist").write_text("<plist/>", encoding="utf-8")
    (ent_dir / "entitlements.mac.inherit.plist").write_text("<plist/>", encoding="utf-8")

    app = desktop_dir / "release" / "mac-arm64" / "Robo.app"
    _write_info_plist(app, "com.igniteenow.robo")
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "Robo").write_text("", encoding="utf-8")

    helper = app / "Contents" / "Frameworks" / "Robo Helper.app"
    _write_info_plist(helper, "com.igniteenow.robo.helper")

    native_dir = app / "Contents" / "Resources" / "app.asar.unpacked" / "node_modules" / "pty"
    native_dir.mkdir(parents=True)
    (native_dir / "pty.node").write_text("", encoding="utf-8")
    (app / "Contents" / "Frameworks" / "chrome_crashpad_handler").write_text("", encoding="utf-8")
    return app


def _collect_codesign_calls(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(
        cli_main.shutil, "which", lambda name: "/usr/bin/codesign" if name == "codesign" else None
    )
    monkeypatch.setattr(cli_main.subprocess, "run", fake_run)
    return calls


def test_desktop_macos_local_codesign_signs_native_binaries(tmp_path, monkeypatch):
    """The standalone Mach-O pass must actually find files inside the bundle.

    Regression: an absolute-path parts check always matches the outer
    Robo.app component, silently skipping every .node/.dylib/crashpad
    binary — codesign then rejects the outer signature (nested code unsigned).
    """
    desktop_dir = tmp_path / "apps" / "desktop"
    app = _make_signable_app(desktop_dir)
    calls = _collect_codesign_calls(monkeypatch)

    assert cli_main._desktop_macos_local_codesign(app, desktop_dir=desktop_dir) is True

    signed = [c[-1] for c in calls if c[:3] == ["/usr/bin/codesign", "--force", "--sign"]]
    assert str(app / "Contents" / "Resources" / "app.asar.unpacked" / "node_modules" / "pty" / "pty.node") in signed
    assert str(app / "Contents" / "Frameworks" / "chrome_crashpad_handler") in signed




def test_relaunchable_fixup_falls_back_to_legacy_adhoc_on_failure(tmp_path, monkeypatch, capsys):
    """A failing stable sign must still leave a launchable (deep ad-hoc) bundle."""
    root = _make_desktop_tree(tmp_path)
    desktop_dir = root / "apps" / "desktop"
    monkeypatch.setattr(cli_main, "PROJECT_ROOT", root)
    monkeypatch.delenv("CSC_LINK", raising=False)
    monkeypatch.delenv("APPLE_SIGNING_IDENTITY", raising=False)
    exe = _make_packaged_executable(root, monkeypatch, platform="darwin")
    app = exe.parents[2]

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(
        cli_main.shutil, "which", lambda name: "/usr/bin/codesign" if name == "codesign" else None
    )
    monkeypatch.setattr(cli_main.subprocess, "run", fake_run)
    monkeypatch.setattr(cli_main, "_desktop_macos_has_valid_real_signature", lambda a: False)
    monkeypatch.setattr(cli_main, "_desktop_macos_local_signing_identity", lambda: None)

    def boom(*a, **kw):
        raise subprocess.CalledProcessError(1, ["codesign"])

    monkeypatch.setattr(cli_main, "_desktop_macos_local_codesign", boom)

    assert cli_main._desktop_macos_relaunchable_fixup(desktop_dir) is False
    assert ["xattr", "-cr", str(app)] in calls
    assert ["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app)] in calls


# --- desktop.* launch options (config.yaml) -------------------------------




# --- Linux launcher entry registration ------------------------------------


def test_gui_registers_linux_desktop_entry_before_launch(tmp_path, monkeypatch):
    """`robo desktop` gives the app a launcher presence on Linux."""
    root = _make_desktop_tree(tmp_path)
    monkeypatch.setattr(cli_main, "PROJECT_ROOT", root)
    packaged_exe = _make_packaged_executable(root, monkeypatch, platform="linux")

    registered: list[Path] = []
    monkeypatch.setattr("robo_cli.linux_desktop_entry.is_supported", lambda: True)
    monkeypatch.setattr(
        "robo_cli.linux_desktop_entry.install_desktop_entry",
        lambda project_root: registered.append(project_root) or (tmp_path / "robo.desktop"),
    )

    log_patch, popen_patch = _detached_launch(tmp_path)

    with patch("robo_cli.main._desktop_build_needed", return_value=False), \
         patch("robo_cli.main._resolve_node_runtime_npm", return_value="/usr/bin/npm"), \
         patch("robo_cli.main._desktop_linux_sandbox_fixup", return_value=True), \
         log_patch, popen_patch as mock_popen, \
         pytest.raises(SystemExit):
        cli_main.cmd_gui(_ns())

    assert registered == [root]
    assert _same_exe(mock_popen.call_args.args[0], packaged_exe)


def test_gui_launches_even_when_desktop_entry_install_fails(tmp_path, monkeypatch):
    """Launcher plumbing is a convenience — it must never block the app."""
    root = _make_desktop_tree(tmp_path)
    monkeypatch.setattr(cli_main, "PROJECT_ROOT", root)
    packaged_exe = _make_packaged_executable(root, monkeypatch, platform="linux")

    def boom(_project_root):
        raise OSError("read-only /home")

    monkeypatch.setattr("robo_cli.linux_desktop_entry.is_supported", lambda: True)
    monkeypatch.setattr("robo_cli.linux_desktop_entry.install_desktop_entry", boom)

    log_patch, popen_patch = _detached_launch(tmp_path)

    with patch("robo_cli.main._desktop_build_needed", return_value=False), \
         patch("robo_cli.main._resolve_node_runtime_npm", return_value="/usr/bin/npm"), \
         patch("robo_cli.main._desktop_linux_sandbox_fixup", return_value=True), \
         log_patch, popen_patch as mock_popen, \
         pytest.raises(SystemExit) as exc:
        cli_main.cmd_gui(_ns())

    assert exc.value.code == 0
    assert _same_exe(mock_popen.call_args.args[0], packaged_exe)


def test_gui_skips_desktop_entry_off_linux(tmp_path, monkeypatch):
    root = _make_desktop_tree(tmp_path)
    monkeypatch.setattr(cli_main, "PROJECT_ROOT", root)
    packaged_exe = _make_packaged_executable(root, monkeypatch, platform="darwin")

    monkeypatch.setattr("robo_cli.linux_desktop_entry.is_supported", lambda: False)

    def fail(_project_root):
        raise AssertionError("must not install a desktop entry off Linux")

    monkeypatch.setattr("robo_cli.linux_desktop_entry.install_desktop_entry", fail)

    log_patch, popen_patch = _detached_launch(tmp_path)

    with patch("robo_cli.main._desktop_build_needed", return_value=False), \
         patch("robo_cli.main._resolve_node_runtime_npm", return_value="/usr/bin/npm"), \
         patch("robo_cli.main._desktop_macos_relaunchable_fixup"), \
         log_patch, popen_patch as mock_popen, \
         pytest.raises(SystemExit) as exc:
        cli_main.cmd_gui(_ns())

    assert exc.value.code == 0
    assert _same_exe(mock_popen.call_args.args[0], packaged_exe)
