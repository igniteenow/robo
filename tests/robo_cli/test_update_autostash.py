from pathlib import Path
from subprocess import CalledProcessError
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from robo_cli import config as robo_config
from robo_cli import main as robo_main


# ---------------------------------------------------------------------------
# Managed-uv compatibility for tests that patch shutil.which
# ---------------------------------------------------------------------------
# The production code now uses ``ensure_uv()`` / ``update_managed_uv()``
# instead of ``shutil.which("uv")``.  Many tests in this file patch
# ``shutil.which`` to control whether uv is "available" — these autouse
# fixtures make the managed_uv functions delegate to the patched
# ``shutil.which`` so the existing test setup keeps working without
# per-test changes.
@pytest.fixture(autouse=True)
def _patch_managed_uv(request):
    """Make managed_uv helpers follow shutil.which mocking in tests."""
    import shutil

    # resolve_uv delegates to shutil.which("uv") so that test patches
    # on shutil.which flow through naturally.
    def _fake_resolve_uv(**kwargs):
        return shutil.which("uv")

    def _fake_ensure_uv(**kwargs):
        return shutil.which("uv")

    def _fake_update_managed_uv(**kwargs):
        return None  # never actually self-update in tests

    with patch("robo_cli.managed_uv.resolve_uv", side_effect=_fake_resolve_uv), \
         patch("robo_cli.managed_uv.ensure_uv", side_effect=_fake_ensure_uv), \
         patch("robo_cli.managed_uv.update_managed_uv", side_effect=_fake_update_managed_uv):
        yield













# ---------------------------------------------------------------------------
# Update uses .[all] with fallback to .
# ---------------------------------------------------------------------------

def _setup_update_mocks(monkeypatch, tmp_path):
    """Common setup for cmd_update tests."""
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(robo_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(robo_main, "_stash_local_changes_if_needed", lambda *a, **kw: None)
    monkeypatch.setattr(robo_main, "_restore_stashed_changes", lambda *a, **kw: True)
    monkeypatch.setattr(robo_config, "get_missing_env_vars", lambda required_only=True: [])
    monkeypatch.setattr(robo_config, "get_missing_config_fields", lambda: [])
    monkeypatch.setattr(robo_config, "check_config_version", lambda: (5, 5))
    monkeypatch.setattr(robo_config, "migrate_config", lambda **kw: {"env_added": [], "config_added": []})
    monkeypatch.setattr(robo_main, "_upgrade_pip_before_lazy_refresh", lambda *a, **kw: None)
    monkeypatch.setattr(robo_main, "_refresh_active_lazy_features", lambda *a, **kw: True)




def test_refresh_active_memory_provider_dependencies_reinstalls_active_provider(monkeypatch):
    """#53272/#70636: update must re-run the active provider's dep install."""
    recorded = []

    monkeypatch.setattr(
        "robo_cli.config.load_config",
        lambda: {"memory": {"provider": "mem0"}},
    )
    monkeypatch.setattr(
        "robo_cli.memory_setup._install_dependencies",
        lambda provider_name, force=False: recorded.append((provider_name, force)),
    )

    robo_main._refresh_active_memory_provider_dependencies()

    assert recorded == [("mem0", True)]




def test_reload_updated_runtime_modules_restores_new_robo_constants_symbol(monkeypatch):
    """A pre-pull module object missing a new helper is repaired by reload."""
    import robo_constants

    monkeypatch.delattr(robo_constants, "apply_subprocess_home_env", raising=False)
    assert not hasattr(robo_constants, "apply_subprocess_home_env")

    robo_main._reload_updated_runtime_modules()

    assert callable(robo_constants.apply_subprocess_home_env)






# ---------------------------------------------------------------------------
# ff-only fallback to reset --hard on diverged history
# ---------------------------------------------------------------------------

def _make_update_side_effect(
    current_branch="main",
    commit_count="3",
    ff_only_fails=False,
    reset_fails=False,
    fetch_fails=False,
    fetch_stderr="",
):
    """Build a subprocess.run side_effect for cmd_update tests."""
    recorded = []

    def side_effect(cmd, **kwargs):
        recorded.append(cmd)
        joined = " ".join(str(c) for c in cmd)
        if "fetch" in joined and "origin" in joined:
            if fetch_fails:
                return SimpleNamespace(stdout="", stderr=fetch_stderr, returncode=128)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if "rev-parse" in joined and "--abbrev-ref" in joined:
            return SimpleNamespace(stdout=f"{current_branch}\n", stderr="", returncode=0)
        if "checkout" in joined and "main" in joined:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if "rev-list" in joined:
            return SimpleNamespace(stdout=f"{commit_count}\n", stderr="", returncode=0)
        if "--ff-only" in joined:
            if ff_only_fails:
                return SimpleNamespace(
                    stdout="",
                    stderr="fatal: Not possible to fast-forward, aborting.\n",
                    returncode=128,
                )
            return SimpleNamespace(stdout="Updating abc..def\n", stderr="", returncode=0)
        if "reset" in joined and "--hard" in joined:
            if reset_fails:
                return SimpleNamespace(stdout="", stderr="error: unable to write\n", returncode=1)
            return SimpleNamespace(stdout="HEAD is now at abc123\n", stderr="", returncode=0)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return side_effect, recorded


# ---------------------------------------------------------------------------
# Non-main branch → auto-checkout main
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Fetch failure — friendly error messages
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# reset --hard failure — don't attempt stash restore
# ---------------------------------------------------------------------------

def test_cmd_update_skips_stash_restore_when_reset_fails(monkeypatch, tmp_path, capsys):
    """When reset --hard fails, stash restore is skipped with a helpful message."""
    _setup_update_mocks(monkeypatch, tmp_path)
    # Re-enable stash so it actually returns a ref
    monkeypatch.setattr(
        robo_main, "_stash_local_changes_if_needed",
        lambda *a, **kw: "abc123deadbeef",
    )
    restore_calls = []
    monkeypatch.setattr(
        robo_main, "_restore_stashed_changes",
        lambda *a, **kw: restore_calls.append(1) or True,
    )

    side_effect, _ = _make_update_side_effect(ff_only_fails=True, reset_fails=True)
    monkeypatch.setattr(robo_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        robo_main.cmd_update(SimpleNamespace())

    # Stash restore should NOT have been called
    assert len(restore_calls) == 0

    out = capsys.readouterr().out
    assert "preserved in stash" in out


# ---------------------------------------------------------------------------
# Non-interactive update.non_interactive_local_changes setting
# (chat app / gateway): "discard" throws stashed changes away, "stash"
# (default) restores them. Interactive terminal updates ignore the setting
# and always go through the restore path.
# ---------------------------------------------------------------------------

def _setup_setting_test(monkeypatch, tmp_path, mode):
    """Common wiring: real stash returns a ref, restore + discard are
    recorded, and load_config reports the given non_interactive_local_changes
    mode."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(
        robo_main, "_stash_local_changes_if_needed",
        lambda *a, **kw: "abc123deadbeef",
    )
    restore_calls = []
    discard_calls = []
    monkeypatch.setattr(
        robo_main, "_restore_stashed_changes",
        lambda *a, **kw: restore_calls.append(1) or True,
    )
    monkeypatch.setattr(
        robo_main, "_discard_stashed_changes",
        lambda *a, **kw: discard_calls.append(1) or True,
    )
    monkeypatch.setattr(
        robo_config, "load_config",
        lambda *a, **kw: {"updates": {"non_interactive_local_changes": mode}},
    )
    side_effect, recorded = _make_update_side_effect()
    monkeypatch.setattr(robo_main.subprocess, "run", side_effect)
    return restore_calls, discard_calls, recorded






def test_bootstrap_marker_not_autostashed_by_update(tmp_path):
    """#38529: the Desktop bootstrap marker must be git-ignored so that
    ``robo update``'s ``git stash push --include-untracked`` does not sweep it
    into an autostash on every run.

    Behavioral + hermetic: build a throwaway repo that adopts the project's real
    ``.gitignore`` (the contract under test), drop the marker, and confirm the
    same stash invocation the updater uses leaves it untouched.
    """
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git not available")

    repo_gitignore = Path(robo_main.__file__).resolve().parents[1] / ".gitignore"

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        )

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / ".gitignore").write_text(repo_gitignore.read_text())
    (tmp_path / "tracked.txt").write_text("x\n")
    git("add", "-A")
    git("commit", "-qm", "init")

    marker = tmp_path / ".robo-bootstrap-complete"
    marker.write_text("")

    # Exact flags used by robo update (robo_cli/main.py).
    git("stash", "push", "--include-untracked", "-m", "robo-update-autostash")

    assert marker.exists(), (
        ".robo-bootstrap-complete was swept into the update autostash — it must "
        "be listed in .gitignore so `git stash -u` skips it (#38529)."
    )
    # It must not even register as a dirty/untracked change.
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True
    ).stdout
    assert ".robo-bootstrap-complete" not in status


@pytest.mark.parametrize("parked", ["venv.stale.runtime-1-2-aaaa", ".venv.stale.runtime-1790690355-8556-1744368d"])
def test_parked_venv_backup_not_autostashed_by_update(tmp_path, parked):
    """A runtime repair parks the previous venv as ``<venv>.stale.runtime-*``
    next to the live one. Only the managed ``venv`` spelling was gitignored,
    so on ``.venv`` installs ``robo update`` autostashed the parked copy
    (about 1 GB) and restored it on every run - with a fresh mtime that
    kept it out of reach of the age-gated sweep for good. Both spellings
    must be invisible to the stash invocation the updater uses.
    """
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git not available")

    repo_gitignore = Path(robo_main.__file__).resolve().parents[1] / ".gitignore"

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        )

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / ".gitignore").write_text(repo_gitignore.read_text())
    (tmp_path / "tracked.txt").write_text("x\n")
    git("add", "-A")
    git("commit", "-qm", "init")

    backup = tmp_path / parked / "lib" / "site-packages"
    backup.mkdir(parents=True)
    (backup / "robo.pth").write_text("old venv\n")

    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True
    ).stdout
    assert parked not in status, (
        f"{parked} shows up as a local change - it must be listed in .gitignore"
    )
    # Exact flags used by robo update: nothing to stash, so nothing moves.
    git("stash", "push", "--include-untracked", "-m", "robo-update-autostash")
    assert (backup / "robo.pth").exists()


def test_cmd_update_sweeps_parked_venvs_before_looking_for_local_changes(monkeypatch, tmp_path):
    """The parked venv is reclaimed BEFORE the updater reads the working tree,
    so the autostash never carries it - whatever the checkout's .gitignore
    says (an install that is still on an older checkout has the old one)."""
    import os
    import time

    _setup_update_mocks(monkeypatch, tmp_path)
    old = tmp_path / ".venv.stale.runtime-1790690355-8556-1744368d"
    (old / "Scripts").mkdir(parents=True)
    (old / "Scripts" / "python.exe").write_text("old")
    when = time.time() - 5 * 86400
    os.utime(old, (when, when))
    fresh = tmp_path / ".venv.stale.runtime-9-9-bbbb"
    (fresh / "Scripts").mkdir(parents=True)

    seen_at_stash = {}

    def fake_stash(*a, **kw):
        seen_at_stash["old"] = old.exists()
        seen_at_stash["fresh"] = fresh.exists()
        return None

    monkeypatch.setattr(robo_main, "_stash_local_changes_if_needed", fake_stash)
    side_effect, _ = _make_update_side_effect(ff_only_fails=True, reset_fails=True)
    monkeypatch.setattr(robo_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit):
        robo_main.cmd_update(SimpleNamespace())

    assert seen_at_stash == {"old": False, "fresh": True}, seen_at_stash


# ---------------------------------------------------------------------------
# Permission-denied autostash class: undeletable untracked files (root-owned
# packaging/ etc.) must not abort the update when the stash entry was created.
# ---------------------------------------------------------------------------






def test_update_autostash_survives_undeletable_untracked_dir(tmp_path):
    """Behavioral E2E of the whole permission-denied class with real git:
    root-owned-style undeletable untracked dir → stash succeeds, update-style
    reset works, restore round-trips, nothing lost. (#70127 follow-up)"""
    import os
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git not available")
    if os.name == "nt":
        pytest.skip("POSIX permission semantics")
    if os.geteuid() == 0:
        pytest.skip("root ignores directory write bits")

    def git(*args, check=True):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=check
        )

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "tracked.txt").write_text("v1\n")
    git("add", "-A")
    git("commit", "-qm", "init")

    (tmp_path / "tracked.txt").write_text("v2 local change\n")
    pkg = tmp_path / "packaging" / "homebrew"
    pkg.mkdir(parents=True)
    (pkg / "robo-engineer.rb").write_text("formula\n")
    os.chmod(pkg, 0o555)  # undeletable contents, like a root-owned dir
    try:
        stash_ref = robo_main._stash_local_changes_if_needed(["git"], tmp_path)
        assert stash_ref

        # The tracked change is stashed; simulate the updater's checkout window.
        assert (tmp_path / "tracked.txt").read_text() == "v1\n"

        restored = robo_main._restore_stashed_changes(
            ["git"], tmp_path, stash_ref, prompt_user=False
        )
        assert restored is True
        assert (tmp_path / "tracked.txt").read_text() == "v2 local change\n"
        assert (pkg / "robo-engineer.rb").read_text() == "formula\n"
    finally:
        os.chmod(pkg, 0o755)


# ---------------------------------------------------------------------------
# Diverged history: local commits are kept on a backup branch before reset
# ---------------------------------------------------------------------------

def test_cmd_update_backs_up_local_commits_before_reset(monkeypatch, tmp_path, capsys):
    _setup_update_mocks(monkeypatch, tmp_path)
    # reset_fails stops the update right after the reset, which is all this
    # test needs to see.
    side_effect, recorded = _make_update_side_effect(ff_only_fails=True, reset_fails=True)
    monkeypatch.setattr(robo_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit):
        robo_main.cmd_update(SimpleNamespace())

    joined = [" ".join(str(c) for c in cmd) for cmd in recorded]
    backup = [i for i, c in enumerate(joined) if " branch robo-update-backup-" in c and c.endswith(" HEAD")]
    reset = [i for i, c in enumerate(joined) if "reset" in c and "--hard" in c]
    assert backup and reset
    assert backup[0] < reset[0]
    assert "to branch robo-update-backup-" in capsys.readouterr().out
