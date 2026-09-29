"""`robo update` keeps local commits before resetting a diverged checkout.

When the checkout's history no longer lines up with origin, update resets to
origin/<branch>. Commits that exist only locally are first saved on a
robo-update-backup-<timestamp> branch. Uses real git repositories.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from robo_cli.update_cmd import _backup_local_commits

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or sys.platform == "win32",
    reason="needs git; POSIX paths (Linux CI runs it)",
)

GIT = ["git", "-c", "user.name=Robo Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        GIT + list(args), cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def diverged(tmp_path):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    upstream = tmp_path / "upstream"
    _git(tmp_path, "clone", "-q", str(origin), str(upstream))
    _git(upstream, "checkout", "-q", "-b", "main")
    _commit(upstream, "base.txt")
    _git(upstream, "push", "-q", "origin", "main")

    checkout = tmp_path / "checkout"
    _git(tmp_path, "clone", "-q", str(origin), str(checkout))
    local_sha = _commit(checkout, "local-change.txt")

    _commit(upstream, "remote-change.txt")
    _git(upstream, "push", "-q", "origin", "main")
    _git(checkout, "fetch", "-q", "origin")
    return checkout, local_sha


def test_local_commits_are_saved_on_a_backup_branch(diverged, capsys):
    checkout, local_sha = diverged

    name = _backup_local_commits(GIT, checkout, "main")

    assert name is not None and name.startswith("robo-update-backup-")
    assert _git(checkout, "rev-parse", name) == local_sha
    assert f"Saved 1 commit(s) that are not on origin/main to branch {name}" in capsys.readouterr().out


def test_backup_survives_the_reset(diverged):
    checkout, local_sha = diverged

    name = _backup_local_commits(GIT, checkout, "main")
    _git(checkout, "reset", "-q", "--hard", "origin/main")

    assert _git(checkout, "rev-parse", "HEAD") == _git(checkout, "rev-parse", "origin/main")
    assert _git(checkout, "rev-parse", name) == local_sha


def test_nothing_local_creates_no_branch(diverged):
    checkout, _local_sha = diverged
    _git(checkout, "reset", "-q", "--hard", "origin/main")

    assert _backup_local_commits(GIT, checkout, "main") is None
    assert "robo-update-backup-" not in _git(checkout, "branch", "--list")


def test_missing_git_never_raises(tmp_path):
    assert _backup_local_commits(["git-binary-that-does-not-exist"], tmp_path, "main") is None


def test_not_a_repository_never_raises(tmp_path):
    assert _backup_local_commits(GIT, tmp_path, "main") is None
