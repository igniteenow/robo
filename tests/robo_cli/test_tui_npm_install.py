"""_tui_need_npm_install: auto npm when node_modules is behind the lockfile."""

import os
import types
from pathlib import Path

import pytest


@pytest.fixture
def main_mod():
    import robo_cli.main as m

    return m


def _touch_ink(root: Path) -> None:
    ink = root / "node_modules" / "@robo" / "ink" / "package.json"
    ink.parent.mkdir(parents=True, exist_ok=True)
    ink.write_text("{}")


def _touch_tui_entry(root: Path) -> None:
    entry = root / "dist" / "entry.js"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("console.log('tui')")


def _assert_utf8_replace_capture(kwargs: dict) -> None:
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"














def test_make_tui_argv_uses_bundled_tui_when_workspace_missing(
    tmp_path: Path, main_mod, monkeypatch
) -> None:
    """Prebuilt-install regression (#56665): a prebuilt install (Docker
    image, Nix build, or prior `npm run build`) ships
    robo_cli/tui_dist/entry.js but never ships ui-tui/ (that directory only
    exists in a git checkout). _make_tui_argv must try the bundled entry.js
    BEFORE _ensure_tui_workspace() — requiring the workspace first hard-exits
    every prebuilt dashboard Chat tab connection with `sys.exit(1)` (surfaced
    to the user as the unhelpful "Chat unavailable: 1") despite a perfectly
    runnable bundled TUI on disk. The bundled shortcut must succeed without
    ever touching the (missing) ui-tui workspace or git.
    """
    monkeypatch.delenv("ROBO_TUI_DIR", raising=False)
    monkeypatch.setattr(main_mod, "_ensure_tui_node", lambda: None)

    bundled_entry = tmp_path / "bundled" / "entry.js"
    bundled_entry.parent.mkdir(parents=True)
    bundled_entry.write_text("// bundled TUI")
    monkeypatch.setattr(main_mod, "_find_bundled_tui", lambda: bundled_entry)

    def which(name: str) -> str | None:
        if name == "node":
            return "/usr/bin/node"
        raise AssertionError(f"unexpected shutil.which({name!r}) call — bundled path must not need npm/git")

    monkeypatch.setattr(main_mod.shutil, "which", which)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("bundled TUI path must not spawn any subprocess (no npm install/build, no git restore)")

    monkeypatch.setattr(main_mod.subprocess, "run", fail_run)

    # ui-tui/ deliberately does not exist under tmp_path, and there is no
    # .git either — this mirrors a prebuilt (Docker/Nix) install exactly.
    tui_dir = tmp_path / "ui-tui"
    assert not tui_dir.exists()

    argv, cwd = main_mod._make_tui_argv(tui_dir, tui_dev=False)

    assert argv == ["/usr/bin/node", "--expose-gc", str(bundled_entry)]
    assert cwd == bundled_entry.parent


# ── _workspace_root helper ──────────────────────────────────────────




    # (Smoke test: just confirm _tui_need_npm_install doesn't crash)
    # It won't need install because the lockfile exists and there's no
    # hidden lockfile to compare against, and ink is missing → True.
    # But the key invariant is: ws_root for the need-check == ws_root
    # for the install cwd — both use _workspace_root(sub).


def test_no_stray_lockfiles_in_workspace_subdirs(main_mod) -> None:
    """Workspace sub-directories must not contain their own package-lock.json.

    With a single workspace root lockfile, per-directory lockfiles are
    always accidental (typically from running ``npm install`` inside the
    wrong directory).  They cause ``_workspace_root`` to treat the
    sub-package as standalone, which breaks hoisted ``node_modules``
    resolution and can silently diverge the install cwd from the
    lockfile-check root.

    This is an invariant, not a change-detector: the workspace structure
    is not expected to gain per-dir lockfiles.
    """
    root = main_mod.PROJECT_ROOT
    # Workspace members that live one level below the root and should
    # NOT have their own lockfile.  (ui-tui/packages/* members are
    # two levels deep and even less likely to get accidental lockfiles,
    # but we check them too for completeness.)
    subdirs = [
        root / "ui-tui",
        root / "web",
        root / "apps" / "desktop",
        root / "apps" / "shared",
    ]
    # Also sweep ui-tui/packages/* (robo-ink etc.)
    tui_pkgs = root / "ui-tui" / "packages"
    if tui_pkgs.is_dir():
        subdirs.extend(d for d in tui_pkgs.iterdir() if d.is_dir())

    stray = [d for d in subdirs if (d / "package-lock.json").is_file()]
    assert not stray, (
        "stray package-lock.json found in workspace sub-directory(es); "
        "delete them and run `npm install` from the repo root instead: "
        + ", ".join(str(d / "package-lock.json") for d in stray)
    )


def test_make_tui_argv_omits_workspace_when_tui_has_own_lockfile(
    tmp_path: Path, main_mod, monkeypatch
) -> None:
    """When ui-tui/ has its own package-lock.json, _workspace_root returns
    tui_dir itself.  npm install --workspace ui-tui would fail in that case
    because npm cannot find a workspace named "ui-tui" inside ui-tui/.
    The fix omits --workspace and runs plain npm install from tui_dir.
    See #42973.
    """
    tui_dir = tmp_path / "ui-tui"
    tui_dir.mkdir()
    (tui_dir / "package.json").write_text("{}")
    # Simulate curl-install layout: tui_dir has its own lockfile
    (tui_dir / "package-lock.json").write_text("{}")
    # Parent also has lockfile (but _workspace_root prefers tui_dir's own)
    (tmp_path / "package-lock.json").write_text("{}")

    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.setenv("PREFIX", "/usr")
    monkeypatch.setattr(main_mod, "_tui_need_npm_install", lambda _root: True)
    monkeypatch.setattr(main_mod.shutil, "which", lambda name: f"/bin/{name}")
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(main_mod.subprocess, "run", fake_run)

    main_mod._make_tui_argv(tui_dir, tui_dev=False)

    install_cmd = calls[0][0][0]
    # Must NOT contain --workspace when npm_cwd == tui_dir
    assert "--workspace" not in install_cmd, (
        f"npm install should omit --workspace when tui_dir has its own lockfile, got: {install_cmd}"
    )
    assert install_cmd[:2] == ["/bin/npm", "install"]
    # cwd must be tui_dir (standalone), not parent
    assert calls[0][1]["cwd"] == str(tui_dir)


# ---------------------------------------------------------------------------
# The dashboard resolves the TUI launch for EVERY chat it opens; rebuilding
# the bundle each time made new and resumed browser chats wait seconds.
# ---------------------------------------------------------------------------


def _tui_with_bundle(tmp_path: Path, *, source_newer: bool) -> Path:
    tui_dir = tmp_path / "ui-tui"
    (tui_dir / "src").mkdir(parents=True)
    src = tui_dir / "src" / "entry.tsx"
    src.write_text("export {}")
    _touch_tui_entry(tui_dir)
    entry = tui_dir / "dist" / "entry.js"
    old, new = 1_700_000_000, 1_700_000_100
    os.utime(src, (new, new) if source_newer else (old, old))
    os.utime(entry, (old, old) if source_newer else (new, new))
    return tui_dir


def _record_builds(main_mod, monkeypatch) -> list:
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.delenv("ROBO_TUI_FORCE_BUILD", raising=False)
    monkeypatch.delenv("ROBO_TUI_DIR", raising=False)
    monkeypatch.setenv("PREFIX", "/usr")
    monkeypatch.setattr(main_mod, "_tui_need_npm_install", lambda _root: False)
    monkeypatch.setattr(main_mod, "_find_bundled_tui", lambda *a, **k: None)
    monkeypatch.setattr(main_mod.shutil, "which", lambda name: f"/bin/{name}")
    builds = []

    def fake_run(cmd, *args, **kwargs):
        if list(cmd[-2:]) == ["run", "build"]:
            builds.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(main_mod.subprocess, "run", fake_run)
    return builds


def test_dashboard_chat_skips_the_build_when_the_bundle_is_fresh(
    tmp_path: Path, main_mod, monkeypatch
) -> None:
    tui_dir = _tui_with_bundle(tmp_path, source_newer=False)
    builds = _record_builds(main_mod, monkeypatch)

    argv, _cwd = main_mod._make_tui_argv(tui_dir, tui_dev=False, rebuild_if_stale=True)

    assert builds == []
    assert argv[-1] == str(tui_dir / "dist" / "entry.js")


def test_dashboard_chat_never_runs_npm_when_the_bundle_is_fresh(
    tmp_path: Path, main_mod, monkeypatch
) -> None:
    """The dashboard's own web build (`npm ci --workspace web`) leaves
    node_modules looking "out of date" to the TUI install check forever; a
    fresh bundle must still start without any npm call."""
    tui_dir = _tui_with_bundle(tmp_path, source_newer=False)
    _record_builds(main_mod, monkeypatch)
    monkeypatch.setattr(main_mod, "_tui_need_npm_install", lambda _root: True)
    npm_calls = []
    monkeypatch.setattr(
        main_mod.subprocess,
        "run",
        lambda cmd, *a, **k: npm_calls.append(cmd)
        or types.SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    argv, _cwd = main_mod._make_tui_argv(tui_dir, tui_dev=False, rebuild_if_stale=True)

    assert npm_calls == []
    assert argv[-1] == str(tui_dir / "dist" / "entry.js")


def test_dashboard_chat_installs_and_builds_when_stale(
    tmp_path: Path, main_mod, monkeypatch
) -> None:
    tui_dir = _tui_with_bundle(tmp_path, source_newer=True)
    builds = _record_builds(main_mod, monkeypatch)
    monkeypatch.setattr(main_mod, "_tui_need_npm_install", lambda _root: True)
    installs = []
    real_run = main_mod.subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if "install" in list(cmd):
            installs.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(main_mod.subprocess, "run", fake_run)

    main_mod._make_tui_argv(tui_dir, tui_dev=False, rebuild_if_stale=True)

    assert len(installs) == 1
    assert len(builds) == 1


def test_dashboard_chat_rebuilds_after_a_source_change(
    tmp_path: Path, main_mod, monkeypatch
) -> None:
    tui_dir = _tui_with_bundle(tmp_path, source_newer=True)
    builds = _record_builds(main_mod, monkeypatch)

    main_mod._make_tui_argv(tui_dir, tui_dev=False, rebuild_if_stale=True)

    assert len(builds) == 1


def test_terminal_launch_still_rebuilds_every_time(
    tmp_path: Path, main_mod, monkeypatch
) -> None:
    tui_dir = _tui_with_bundle(tmp_path, source_newer=False)
    builds = _record_builds(main_mod, monkeypatch)

    main_mod._make_tui_argv(tui_dir, tui_dev=False)

    assert len(builds) == 1


def test_dashboard_chats_resolve_the_tui_with_rebuild_if_stale(monkeypatch) -> None:
    import robo_cli.main as cli_main
    import robo_cli.web_server as ws

    seen = {}

    def fake_make(root, tui_dev=False, **kwargs):
        seen.update(kwargs)
        return (["node", "fake-tui.js"], Path("/tmp"))

    monkeypatch.setattr(cli_main, "_make_tui_argv", fake_make)
    ws._resolve_chat_argv()
    assert seen.get("rebuild_if_stale") is True


@pytest.mark.asyncio
async def test_dashboard_prewarms_the_chat_tui_under_the_chat_lock(monkeypatch) -> None:
    import asyncio

    import robo_cli.main as cli_main
    import robo_cli.web_server as ws

    calls = []
    lock = ws._get_chat_argv_lock(ws.app)

    def fake_make(root, tui_dev, **kwargs):
        calls.append((tui_dev, kwargs, lock.locked()))
        return (["node", "x.js"], root)

    monkeypatch.setattr(cli_main, "_make_tui_argv", fake_make)
    await ws._prewarm_chat_tui(ws.app)
    assert calls == [(False, {"rebuild_if_stale": True}, True)]

    def no_node(*_a, **_k):
        raise SystemExit(1)                      # what _make_tui_argv does without Node

    monkeypatch.setattr(cli_main, "_make_tui_argv", no_node)
    await ws._prewarm_chat_tui(ws.app)           # never takes the dashboard down
    assert not lock.locked()


# ---------------------------------------------------------------------------
# The TUI build scripts call `node` by name. Windows installs keep Robo's
# Node in <ROBO_HOME>\node and never add it to PATH, so the build failed with
# "'node' is not recognized" on machines without a system Node.
# ---------------------------------------------------------------------------


def _managed_node_dir() -> Path:
    from robo_constants import get_robo_home, iter_robo_node_dirs

    assert get_robo_home()  # isolated temp ROBO_HOME from conftest
    node_dir = iter_robo_node_dirs()[0]
    node_dir.mkdir(parents=True, exist_ok=True)
    return node_dir


def _record_build_envs(main_mod, monkeypatch) -> list:
    import robo_constants

    _record_builds(main_mod, monkeypatch)
    # Resolve npm/node the same way on every OS (Windows scans PATH for .cmd
    # shims instead of calling shutil.which).
    monkeypatch.setattr(robo_constants, "find_node_executable", lambda cmd: f"/bin/{cmd}")
    envs = []

    def fake_run(cmd, *args, **kwargs):
        if list(cmd[-2:]) == ["run", "build"]:
            envs.append(kwargs.get("env"))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(main_mod.subprocess, "run", fake_run)
    return envs


def test_tui_build_runs_with_robo_managed_node_on_path(
    tmp_path: Path, main_mod, monkeypatch
) -> None:
    node_dir = _managed_node_dir()
    tui_dir = _tui_with_bundle(tmp_path, source_newer=True)
    envs = _record_build_envs(main_mod, monkeypatch)

    main_mod._make_tui_argv(tui_dir, tui_dev=False)

    assert len(envs) == 1
    assert envs[0] is not None
    assert envs[0]["PATH"].split(os.pathsep)[0] == str(node_dir)


def test_tui_dev_prebuild_runs_with_robo_managed_node_on_path(
    tmp_path: Path, main_mod, monkeypatch
) -> None:
    node_dir = _managed_node_dir()
    tui_dir = _tui_with_bundle(tmp_path, source_newer=True)
    (tui_dir / "packages" / "robo-ink").mkdir(parents=True)
    envs = _record_build_envs(main_mod, monkeypatch)

    main_mod._make_tui_argv(tui_dir, tui_dev=True)

    assert len(envs) == 1
    assert envs[0] is not None
    assert envs[0]["PATH"].split(os.pathsep)[0] == str(node_dir)
