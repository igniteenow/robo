"""Tests for the update checker in robo_cli.banner. Copyright (c) 2026 Ignitee Now.

Most of these run against real, throwaway git repositories: a bare "remote"
and clones of it. That tests what the checker actually asks git, rather than a
script of mocked replies.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import robo_cli.banner as banner

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

_ENV = {
    **os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(cwd, *args):
    done = subprocess.run(["git", *args], cwd=str(cwd), env=_ENV, capture_output=True, text=True)
    assert done.returncode == 0, f"git {args} failed: {done.stderr}"
    return done.stdout.strip()


def commit(repo, name):
    (Path(repo) / name).write_text(name, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A bare remote with 3 commits on main, a seeding repo, and a clone."""
    remote, seed, clone = tmp_path / "remote.git", tmp_path / "seed", tmp_path / "clone"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(tmp_path, "init", "-q", "-b", "main", str(seed))
    git(seed, "remote", "add", "origin", str(remote))
    for name in ("a", "b", "c"):
        commit(seed, name)
    git(seed, "push", "-q", "origin", "main")
    git(tmp_path, "clone", "-q", str(remote), str(clone))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("ROBO_HOME", str(home))
    monkeypatch.delenv("ROBO_REVISION", raising=False)
    monkeypatch.delenv("ROBO_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(banner, "_resolve_repo_dir", lambda: clone)
    monkeypatch.setattr(banner, "_latest_release_cache", None)

    def publish(*names):
        for name in names:
            commit(seed, name)
        git(seed, "push", "-q", "origin", "main")

    return type("World", (), {"remote": remote, "seed": seed, "clone": clone, "home": home, "publish": staticmethod(publish)})


class TestRemoteUrls:
    @pytest.mark.parametrize("url", [
        "https://github.com/igniteenow/robo.git", "https://github.com/igniteenow/robo",
        "https://github.com/igniteenow/robo/", "git@github.com:igniteenow/robo.git",
        "ssh://git@github.com/igniteenow/robo.git", "ssh://git@github.com:22/igniteenow/robo",
        "https://user:s3cr3t-token@github.com/igniteenow/robo.git", "  git://github.com/igniteenow/robo.git  ",
    ])
    def test_every_spelling_of_the_official_repo_is_recognised(self, url):
        assert banner._canonical_github_remote(url) == "github.com/igniteenow/robo"

    def test_credentials_never_survive_canonicalisation(self):
        assert "s3cr3t" not in banner._canonical_github_remote("https://user:s3cr3t@github.com/o/r.git")

    @pytest.mark.parametrize("url", [None, "", "   ", "not a url", "https://github.com/only-owner", "github.com", "/local/path", "file:///x"])
    def test_unrecognisable_remotes_are_empty(self, url):
        assert banner._canonical_github_remote(url) == ""

    @pytest.mark.parametrize("url, ssh", [
        ("git@github.com:o/r.git", True), ("ssh://git@github.com/o/r", True), ("git+ssh://git@h/o/r", True),
        ("https://github.com/o/r", False), ("/srv/git/r.git", False), (r"C:\repos\r", False), ("C:/repos/r", False), (None, False),
    ])
    def test_ssh_detection(self, url, ssh):
        assert banner._is_ssh_remote(url) is ssh

    def test_only_ignitee_nows_repo_is_official(self):
        assert banner._is_official_ssh_remote("git@github.com:igniteenow/robo.git")
        assert not banner._is_official_ssh_remote("git@github.com:someone/robo-engineer.git")
        assert not banner._is_official_ssh_remote("https://github.com/igniteenow/robo.git")  # not SSH
        assert not banner._is_official_ssh_remote("git@github.com.evil.test:igniteenow/robo.git")

    def test_the_official_constants_agree_with_each_other(self):
        assert banner._canonical_github_remote(banner._UPSTREAM_REPO_URL) == banner._OFFICIAL_REPO_CANONICAL
        assert banner._canonical_github_remote(banner._RELEASE_URL_BASE) == banner._OFFICIAL_REPO_CANONICAL
        assert "igniteenow" in banner._OFFICIAL_REPO_CANONICAL


class TestLocalGitCheck:
    def test_up_to_date(self, world):
        assert banner._check_via_local_git(world.clone) == 0

    def test_counts_commits_behind(self, world):
        world.publish("d", "e")
        assert banner._check_via_local_git(world.clone) == 2

    def test_local_only_commits_are_not_behind(self, world):
        commit(world.clone, "mine")
        assert banner._check_via_local_git(world.clone) == 0

    def test_diverged_counts_only_what_is_missing(self, world):
        commit(world.clone, "mine")
        world.publish("d")
        assert banner._check_via_local_git(world.clone) == 1

    def test_feature_branch_is_measured_against_main(self, world):
        git(world.clone, "checkout", "-q", "-b", "feature")
        world.publish("d", "e", "f")
        assert banner._check_via_local_git(world.clone) == 3

    def test_shallow_clone_reports_presence_only(self, world, tmp_path):
        shallow = tmp_path / "shallow"
        git(tmp_path, "clone", "-q", "--depth", "1", f"file://{world.remote}", str(shallow))
        assert banner._check_via_local_git(shallow) == 0
        world.publish("d")
        assert banner._check_via_local_git(shallow) == banner.UPDATE_AVAILABLE_NO_COUNT

    def test_no_origin_means_unknown(self, world):
        git(world.clone, "remote", "remove", "origin")
        assert banner._check_via_local_git(world.clone) is None

    def test_unreachable_remote_means_unknown_not_zero(self, world, tmp_path):
        git(world.clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
        assert banner._check_via_local_git(world.clone) is None

    def test_not_a_repository(self, tmp_path):
        assert banner._check_via_local_git(tmp_path) is None

    def test_git_missing_entirely(self, world):
        with patch("robo_cli.banner.subprocess.run", side_effect=FileNotFoundError("git")):
            assert banner._check_via_local_git(world.clone) is None

    def test_a_hung_git_times_out_instead_of_hanging_startup(self, world):
        with patch("robo_cli.banner.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 5)):
            assert banner._check_via_local_git(world.clone) is None


class TestSshRemotesAreNeverFetched:
    def _calls(self, world, url):
        git(world.clone, "remote", "set-url", "origin", url)
        seen, real = [], subprocess.run

        def spy(argv, **kwargs):
            seen.append(list(argv))
            return real(argv, **kwargs)

        with patch("robo_cli.banner.subprocess.run", side_effect=spy):
            result = banner._check_via_local_git(world.clone)
        return result, seen

    def test_a_fork_over_ssh_stays_off_the_network(self, world):
        world.publish("d")  # the clone has not fetched this
        result, seen = self._calls(world, "git@github.com:someone/their-fork.git")
        assert not [c for c in seen if "fetch" in c or "ls-remote" in c]
        assert result == 0  # compared with the origin/main it already had

    def test_the_official_repo_over_ssh_is_fetched_over_https_instead(self, world, monkeypatch):
        monkeypatch.setattr(banner, "_UPSTREAM_REPO_URL", str(world.remote))  # stand-in for the HTTPS URL
        world.publish("d", "e")
        result, seen = self._calls(world, "git@github.com:igniteenow/robo.git")
        fetches = [c for c in seen if "fetch" in c]
        assert len(fetches) == 1 and str(world.remote) in fetches[0] and "origin" not in fetches[0]
        assert result == 2


class TestEveryGitCallIsSafe:
    def test_non_interactive_bounded_and_quiet(self, world):
        seen, real = [], subprocess.run

        def spy(argv, **kwargs):
            seen.append((list(argv), kwargs))
            return real(argv, **kwargs)

        world.publish("d")
        with patch("robo_cli.banner.subprocess.run", side_effect=spy):
            banner._check_via_local_git(world.clone)
            banner.get_git_banner_state(world.clone)
            banner.get_latest_release_tag(world.clone)
        assert len(seen) >= 6
        for argv, kwargs in seen:
            assert argv[0] == "git" and all(isinstance(a, str) for a in argv), argv
            assert kwargs.get("timeout"), f"no timeout on {argv}"
            assert kwargs.get("stdin") == subprocess.DEVNULL, f"stdin open on {argv}"
            assert "shell" not in kwargs or kwargs["shell"] is False
            env = kwargs.get("env") or {}
            assert env.get("GIT_TERMINAL_PROMPT") == "0", f"git may prompt on {argv}"

    def test_windows_hide_flags_are_passed_when_present(self, world, monkeypatch):
        from robo_cli import _subprocess_compat

        monkeypatch.setattr(_subprocess_compat, "windows_hide_flags", lambda: 0x08000000)
        captured = {}

        def fake(argv, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout="abcdef12\n", stderr="")

        with patch("robo_cli.banner.subprocess.run", side_effect=fake):
            banner._git_stdout(["rev-parse", "HEAD"], cwd=world.clone)
        assert captured["creationflags"] == 0x08000000

    def test_no_creationflags_off_windows(self, world, monkeypatch):
        from robo_cli import _subprocess_compat

        monkeypatch.setattr(_subprocess_compat, "windows_hide_flags", lambda: 0)
        captured = {}

        def fake(argv, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout="x\n", stderr="")

        with patch("robo_cli.banner.subprocess.run", side_effect=fake):
            banner._git_stdout(["rev-parse", "HEAD"], cwd=world.clone)
        assert "creationflags" not in captured  # a non-zero value raises on POSIX; zero is pointless


class TestEmbeddedRevision:
    def _ls_remote(self, stdout, rc=0):
        return patch("robo_cli.banner.subprocess.run",
                     return_value=subprocess.CompletedProcess(["git"], rc, stdout=stdout, stderr=""))

    def test_same_revision_is_up_to_date(self):
        sha = "a" * 40
        with self._ls_remote(f"{sha}\trefs/heads/main\n"):
            assert banner._check_via_rev(sha) == 0
            assert banner._check_via_rev(sha[:12]) == 0  # builds often embed a short hash

    def test_different_revision_is_behind_without_a_count(self):
        with self._ls_remote("b" * 40 + "\trefs/heads/main\n"):
            assert banner._check_via_rev("a" * 40) == banner.UPDATE_AVAILABLE_NO_COUNT

    @pytest.mark.parametrize("stdout, rc", [("", 0), ("garbage\n", 0), ("a" * 40, 128)])
    def test_an_unusable_answer_is_unknown(self, stdout, rc):
        with self._ls_remote(stdout, rc):
            assert banner._check_via_rev("a" * 40) is None

    @pytest.mark.parametrize("rev", ["", None, "not-hex", "--upload-pack=evil", "abc"])
    def test_a_malformed_revision_never_reaches_git(self, rev):
        with patch("robo_cli.banner.subprocess.run") as run:
            assert banner._check_via_rev(rev) is None
        run.assert_not_called()

    def test_it_only_ever_asks_the_official_repository(self):
        with self._ls_remote("a" * 40 + "\trefs/heads/main\n") as run:
            banner._check_via_rev("a" * 40)
        argv = run.call_args[0][0]
        assert argv == ["git", "ls-remote", banner._UPSTREAM_REPO_URL, "refs/heads/main"]

    def test_check_for_updates_uses_the_embedded_revision(self, world, monkeypatch):
        monkeypatch.setenv("ROBO_REVISION", "a" * 40)
        with self._ls_remote("b" * 40 + "\trefs/heads/main\n"):
            assert banner.check_for_updates() == banner.UPDATE_AVAILABLE_NO_COUNT


class TestCache:
    def _cache(self, world):
        return json.loads((world.home / ".update_check").read_text(encoding="utf-8"))

    def test_a_result_is_cached_and_reused_without_git(self, world):
        world.publish("d")
        assert banner.check_for_updates() == 1
        record = self._cache(world)
        assert record["behind"] == 1 and record["ver"] and record["head"] == git(world.clone, "rev-parse", "HEAD")
        with patch("robo_cli.banner.subprocess.run") as run:
            assert banner.check_for_updates() == 1
        run.assert_not_called()

    def test_updating_the_checkout_invalidates_the_cache(self, world):
        world.publish("d", "e")
        assert banner.check_for_updates() == 2
        git(world.clone, "pull", "-q", "origin", "main")  # what `robo update` does
        assert banner.check_for_updates() == 0  # not a stale 2

    def test_a_new_version_invalidates_the_cache(self, world):
        world.publish("d")
        assert banner.check_for_updates() == 1
        record = self._cache(world)
        record["ver"] = "0.0.0-older"
        record["behind"] = 99
        (world.home / ".update_check").write_text(json.dumps(record))
        assert banner.check_for_updates() == 1

    def test_an_expired_entry_is_ignored(self, world):
        (world.home / ".update_check").write_text(json.dumps(
            {"ts": time.time() - banner._UPDATE_CHECK_CACHE_SECONDS - 1, "behind": 7, "ver": banner._current_version()}))
        assert banner.check_for_updates() == 0

    def test_a_timestamp_from_the_future_is_not_trusted(self, world):
        (world.home / ".update_check").write_text(json.dumps(
            {"ts": time.time() + 10_000, "behind": 7, "ver": banner._current_version()}))
        assert banner.check_for_updates() == 0

    @pytest.mark.parametrize("content", ["", "not json", "[]", "null", '{"ts": "x", "behind": 1}', '{"behind": true, "ts": 1}',
                                         '{"behind": -5, "ts": 1}', '{"behind": 1.5, "ts": 1}'])
    def test_a_corrupt_cache_is_ignored(self, world, content):
        (world.home / ".update_check").write_text(content)
        assert banner.check_for_updates() == 0

    def test_failures_are_not_cached(self, world, tmp_path):
        git(world.clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
        assert banner.check_for_updates() is None
        assert not (world.home / ".update_check").exists()

    def test_the_legacy_cache_shape_still_reads(self, world):
        (world.home / ".update_check").write_text(json.dumps({"ts": time.time(), "behind": 3, "ver": banner._current_version()}))
        with patch("robo_cli.banner.subprocess.run") as run:
            assert banner.check_for_updates() == 3
        run.assert_not_called()

    def test_an_unwritable_home_does_not_break_the_check(self, world, monkeypatch):
        monkeypatch.setattr(banner, "_cache_path", lambda: world.home / "no" / "such" / "\0bad" / ".update_check")
        assert banner.check_for_updates() == 0


    def test_an_interrupted_write_leaves_no_scratch_file(self, world):
        with patch("robo_cli.banner.os.replace", side_effect=OSError("disk full")):
            assert banner.check_for_updates() == 0
        assert [p.name for p in world.home.iterdir()] == []


class TestSwitches:
    @pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
    def test_opt_out(self, world, monkeypatch, value):
        monkeypatch.setenv("ROBO_NO_UPDATE_CHECK", value)
        with patch("robo_cli.banner.subprocess.run") as run:
            assert banner.check_for_updates() is None
        run.assert_not_called()

    def test_a_non_git_install_has_nothing_to_report(self, world, monkeypatch):
        monkeypatch.setattr(banner, "_resolve_repo_dir", lambda: None)
        assert banner.check_for_updates() is None

    def test_it_never_raises(self, world, monkeypatch):
        monkeypatch.setattr(banner, "_resolve_repo_dir", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert banner.check_for_updates() is None


class TestReadHeadWithoutGit:
    def test_matches_git(self, world):
        assert banner._read_head_sha(world.clone) == git(world.clone, "rev-parse", "HEAD")

    def test_detached_head(self, world):
        sha = git(world.clone, "rev-parse", "HEAD~1")
        git(world.clone, "checkout", "-q", sha)
        assert banner._read_head_sha(world.clone) == sha

    def test_packed_refs(self, world):
        git(world.clone, "pack-refs", "--all")
        assert banner._read_head_sha(world.clone) == git(world.clone, "rev-parse", "HEAD")

    def test_linked_worktree(self, world, tmp_path):
        tree = tmp_path / "tree"
        git(world.clone, "worktree", "add", "-q", "-b", "wt", str(tree))
        commit(tree, "in-worktree")
        assert banner._read_head_sha(tree) == git(tree, "rev-parse", "HEAD")

    def test_it_starts_no_process(self, world):
        with patch("robo_cli.banner.subprocess.run") as run:
            banner._read_head_sha(world.clone)
        run.assert_not_called()

    @pytest.mark.parametrize("setup", ["missing", "empty", "garbage"])
    def test_a_broken_git_dir_is_none(self, tmp_path, setup):
        if setup != "missing":
            (tmp_path / ".git").mkdir()
            if setup == "garbage":
                (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/../../etc/passwd\n")
        assert banner._read_head_sha(tmp_path) is None


class TestBannerFacts:
    def test_git_state_of_a_clean_clone(self, world):
        sha = git(world.clone, "rev-parse", "--short=8", "HEAD")
        assert banner.get_git_banner_state(world.clone) == {"upstream": sha, "local": sha, "ahead": 0}

    def test_git_state_counts_local_commits(self, world):
        commit(world.clone, "mine")
        commit(world.clone, "mine2")
        state = banner.get_git_banner_state(world.clone)
        assert state["ahead"] == 2 and state["local"] != state["upstream"]

    def test_git_state_without_a_checkout_uses_the_build_sha(self, tmp_path):
        with patch("robo_cli.build_info.get_build_sha", return_value="1234abcd"):
            assert banner.get_git_banner_state(tmp_path) == {"upstream": "1234abcd", "local": "1234abcd", "ahead": 0}
        with patch("robo_cli.build_info.get_build_sha", return_value=None):
            assert banner.get_git_banner_state(tmp_path) is None

    def test_release_tag_links_only_for_the_official_repo(self, world, monkeypatch):
        git(world.clone, "tag", "v3.0.0")
        assert banner.get_latest_release_tag(world.clone) == ("v3.0.0", None)  # origin is a local path: a fork
        monkeypatch.setattr(banner, "_latest_release_cache", None)
        git(world.clone, "remote", "set-url", "origin", "https://github.com/igniteenow/robo.git")
        assert banner.get_latest_release_tag(world.clone) == ("v3.0.0", "https://github.com/igniteenow/robo/releases/tag/v3.0.0")

    def test_release_tag_is_looked_up_once_per_process(self, world):
        git(world.clone, "tag", "v1")
        assert banner.get_latest_release_tag(world.clone)[0] == "v1"
        git(world.clone, "tag", "-d", "v1")
        with patch("robo_cli.banner.subprocess.run") as run:
            assert banner.get_latest_release_tag(world.clone)[0] == "v1"
        run.assert_not_called()

    def test_no_tags_is_remembered_too(self, world):
        assert banner.get_latest_release_tag(world.clone) is None
        with patch("robo_cli.banner.subprocess.run") as run:
            assert banner.get_latest_release_tag(world.clone) is None
        run.assert_not_called()

    def test_a_hostile_tag_name_never_becomes_a_url(self, world, monkeypatch):
        git(world.clone, "remote", "set-url", "origin", "https://github.com/igniteenow/robo.git")
        evil = subprocess.CompletedProcess(["git"], 0, stdout='v1"><script>\n', stderr="")
        with patch("robo_cli.banner.subprocess.run", return_value=evil):
            assert banner.get_latest_release_tag(world.clone) is None


class TestPrefetch:
    def _reset(self, monkeypatch):
        monkeypatch.setattr(banner, "_update_result", None)
        monkeypatch.setattr(banner, "_update_check_done", threading.Event())
        monkeypatch.setattr(banner, "_prefetch_thread", None)

    def test_returns_immediately_and_delivers_the_answer(self, monkeypatch):
        self._reset(monkeypatch)
        release = threading.Event()

        def slow():
            release.wait(5)
            return 4

        with patch.object(banner, "check_for_updates", side_effect=slow):
            started = time.monotonic()
            banner.prefetch_update_check()
            assert time.monotonic() - started < 0.5
            assert banner.get_update_result(timeout=0.05) is None  # not ready yet, and it did not block
            release.set()
            assert banner.get_update_result(timeout=5) == 4

    def test_a_second_call_does_not_start_a_second_check(self, monkeypatch):
        self._reset(monkeypatch)
        calls, release = [], threading.Event()

        def slow():
            calls.append(1)
            release.wait(5)
            return 0

        with patch.object(banner, "check_for_updates", side_effect=slow):
            banner.prefetch_update_check()
            banner.prefetch_update_check()
            release.set()
            banner.get_update_result(timeout=5)
            banner.prefetch_update_check()  # already done
            time.sleep(0.05)
        assert calls == [1]

    def test_a_crashing_check_still_completes(self, monkeypatch):
        self._reset(monkeypatch)
        with patch.object(banner, "check_for_updates", side_effect=RuntimeError("boom")):
            banner.prefetch_update_check()
            assert banner._update_check_done.wait(5)
            assert banner.get_update_result() is None
