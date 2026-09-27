"""A release tag must match the version in every file that declares one."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_release_version", REPO / "scripts" / "check_release_version.py")
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def _project(root: Path, *, pyproject="3.0.2", runtime="3.0.2", root_pkg="3.0.2", desktop_pkg="3.0.2") -> Path:
    (root / "robo_runtime").mkdir(parents=True)
    (root / "apps" / "desktop").mkdir(parents=True)
    (root / "pyproject.toml").write_text(f'[project]\nname = "robo"\nversion = "{pyproject}"\n', encoding="utf-8")
    (root / "robo_runtime" / "version.py").write_text(f'"""x"""\n\nROBO_VERSION = "{runtime}"\n', encoding="utf-8")
    (root / "package.json").write_text(json.dumps({"version": root_pkg}), encoding="utf-8")
    (root / "apps" / "desktop" / "package.json").write_text(json.dumps({"version": desktop_pkg}), encoding="utf-8")
    return root


def test_a_matching_tag_passes(tmp_path, capsys):
    assert check.main(["v3.0.2", "--root", str(_project(tmp_path))]) == 0
    assert "matches" in capsys.readouterr().out


def test_every_stale_file_is_named(tmp_path, capsys):
    root = _project(tmp_path, runtime="3.0.1", desktop_pkg="3.0.1")

    assert check.main(["v3.0.2", "--root", str(root)]) == 1

    err = capsys.readouterr().err
    assert "robo_runtime/version.py says 3.0.1" in err
    assert "apps/desktop/package.json says 3.0.1" in err
    assert "pyproject.toml" not in err


@pytest.mark.parametrize("tag", ["3.0.2", "v3.0", "v3.0.2-rc1", "backup/v3.0.2", "release-3"])
def test_non_release_tags_are_refused(tmp_path, tag):
    assert check.mismatches(tag, _project(tmp_path))[0].startswith(repr(tag))


def test_a_missing_file_is_a_mismatch_not_a_crash(tmp_path):
    root = _project(tmp_path)
    (root / "apps" / "desktop" / "package.json").unlink()

    assert check.mismatches("v3.0.2", root) == ["apps/desktop/package.json says nothing readable, the tag says 3.0.2"]


def test_this_checkout_is_consistent_with_itself():
    # Whatever the current version is, every file must agree on it, so the
    # next release only needs the four files bumped together.
    versions = set(check.versions_in_code(REPO).values())

    assert len(versions) == 1 and None not in versions
