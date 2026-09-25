"""Which running executables a desktop build may stop before it rewrites them.

A packaged build replaces ``release/…/Robo.exe``; a source build stamps Robo's
icon onto ``node_modules/electron/dist/electron.exe`` (the binary a from-source
Robo runs as). Windows refuses either while the file is running, so the build
stops that process first — and only that one: nothing outside the build's own
tree is ever a candidate.
"""

from __future__ import annotations

from pathlib import Path

from robo_cli import main as cli_main


def _layout(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "robo"
    desktop_dir = project_root / "apps" / "desktop"
    (desktop_dir / "release" / "win-unpacked").mkdir(parents=True)
    (project_root / "node_modules" / "electron" / "dist").mkdir(parents=True)
    return project_root, desktop_dir


def test_packaged_build_locks_release_only(tmp_path: Path) -> None:
    project_root, desktop_dir = _layout(tmp_path)

    roots = cli_main._desktop_build_lock_roots(desktop_dir, project_root, source_mode=False)

    assert roots == [(desktop_dir / "release").resolve()]


def test_source_build_locks_the_electron_binary_it_runs_from(tmp_path: Path) -> None:
    project_root, desktop_dir = _layout(tmp_path)

    roots = cli_main._desktop_build_lock_roots(desktop_dir, project_root, source_mode=True)

    assert roots == [(project_root / "node_modules" / "electron" / "dist").resolve()]


def test_source_build_prefers_the_workspace_local_electron(tmp_path: Path) -> None:
    project_root, desktop_dir = _layout(tmp_path)
    local_dist = desktop_dir / "node_modules" / "electron" / "dist"
    local_dist.mkdir(parents=True)

    roots = cli_main._desktop_build_lock_roots(desktop_dir, project_root, source_mode=True)

    assert roots == [local_dist.resolve()]


def test_missing_trees_yield_no_roots(tmp_path: Path) -> None:
    project_root = tmp_path / "empty"
    desktop_dir = project_root / "apps" / "desktop"
    desktop_dir.mkdir(parents=True)

    assert cli_main._desktop_build_lock_roots(desktop_dir, project_root, source_mode=False) == []
    assert cli_main._desktop_build_lock_roots(desktop_dir, project_root, source_mode=True) == []


def test_exe_runs_from_matches_only_inside_the_roots(tmp_path: Path) -> None:
    project_root, desktop_dir = _layout(tmp_path)
    dist = (project_root / "node_modules" / "electron" / "dist").resolve()
    release = (desktop_dir / "release").resolve()
    roots = [dist]

    assert cli_main._exe_runs_from(str(dist / "electron.exe"), roots) is True
    assert cli_main._exe_runs_from(str(release / "win-unpacked" / "Robo.exe"), roots) is False
    assert cli_main._exe_runs_from(str(tmp_path / "Program Files" / "Robo" / "Robo.exe"), roots) is False
    assert cli_main._exe_runs_from(None, roots) is False
    assert cli_main._exe_runs_from("", roots) is False
    assert cli_main._exe_runs_from(str(dist / "electron.exe"), []) is False
