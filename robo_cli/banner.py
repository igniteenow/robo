"""Update checking for Robo, and the public import path for the start-up banner.
Copyright (c) 2026 Ignitee Now.

Two things live behind this module name:

* **Update checker** (below). Answers one question — "is a newer Robo
  available?" — without ever getting in the user's way.
* **Banner presentation**, implemented in ``robo_cli.welcome_banner`` and
  re-exported at the bottom, because ``robo_cli.banner`` is the path the rest of
  the codebase imports. The presentation code resolves the functions below
  through this module at call time, so replacing one here takes effect there.

Rules the checker follows:

* **Never prompt, never hang, never flash.** Every git call is non-interactive,
  has a timeout, and hides its console window on Windows. An SSH remote is
  never fetched at start-up, because that can stop to ask for a passphrase.
* **Never raise.** Every public function returns ``None`` when it cannot tell.
* **Only Ignitee Now's repository is "official".** Release links and the
  HTTPS fallback point at it and nowhere else; forks get no release link.
* **Cheap when it can be.** A result is cached for six hours, and the cache is
  read without starting a process. It is ignored if Robo's version or the
  checkout's HEAD has changed since it was written, so ``robo update`` never
  leaves a stale "3 behind" on screen.

Set ``ROBO_NO_UPDATE_CHECK=1`` to switch the check off (air-gapped machines).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import quote, urlparse

from robo_constants import get_robo_home

logger = logging.getLogger(__name__)

_UPDATE_CHECK_CACHE_SECONDS = 6 * 3600
_UPDATE_CACHE_FILE = ".update_check"

# check_for_updates() result meaning "newer code exists, but the number of
# commits cannot be counted" (shallow clones, embedded-revision builds).
UPDATE_AVAILABLE_NO_COUNT = -1

_UPSTREAM_REPO_URL = "https://github.com/igniteenow/robo.git"
_OFFICIAL_REPO_CANONICAL = "github.com/igniteenow/robo"
_RELEASE_URL_BASE = "https://github.com/igniteenow/robo/releases/tag"

_LOCAL_TIMEOUT = 5      # seconds; git commands that only read the local repo
_NETWORK_TIMEOUT = 15   # seconds; fetch / ls-remote
_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")
_SAFE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+/-]{0,127}$")
_SCP_LIKE = re.compile(r"^(?:[^@/\s]+@)?(?P<host>[^:/\s]+):(?P<path>[^\s]+)$")


# ----------------------------------------------------------------------------- git runner
def _run_git(args: List[str], *, cwd: Optional[Path], timeout: int) -> Optional[subprocess.CompletedProcess]:
    """Run ``git <args>`` quietly. ``None`` means git could not be run at all."""
    kwargs: dict = {
        "capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace",
        "timeout": timeout, "stdin": subprocess.DEVNULL,
    }
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    try:
        from robo_cli._subprocess_compat import noninteractive_git_env, windows_hide_flags

        kwargs["env"] = noninteractive_git_env()
        flags = windows_hide_flags()
        if flags:
            kwargs["creationflags"] = flags
    except Exception as exc:  # the helpers are a refinement, not a requirement
        logger.debug("update check: subprocess helpers unavailable: %s", exc)
        kwargs["env"] = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(["git", *args], timeout=kwargs.pop("timeout", timeout), **kwargs)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.debug("update check: git %s failed to run: %s", args[:2], exc)
        return None


def _git_stdout(args: list[str], *, cwd: Path, timeout: int = _LOCAL_TIMEOUT) -> Optional[str]:
    """Stripped stdout of a successful git command, else ``None``."""
    done = _run_git(list(args), cwd=cwd, timeout=timeout)
    if done is None or done.returncode != 0:
        return None
    return (done.stdout or "").strip()


# --------------------------------------------------------------------------- remote URLs
def _canonical_github_remote(url: str | None) -> str:
    """``host/owner/repo`` (lower case, no ``.git``, no credentials) for the
    common remote spellings, or ``""`` when the URL is not recognisable::

        https://github.com/Owner/Repo.git      git@github.com:Owner/Repo.git
        https://user:token@github.com/o/r      ssh://git@github.com:22/Owner/Repo
    """
    text = str(url or "").strip()
    if not text:
        return ""
    host = path = ""
    if "://" in text:
        try:
            parsed = urlparse(text)
        except ValueError:
            return ""
        host, path = (parsed.hostname or ""), parsed.path
    else:
        match = _SCP_LIKE.match(text)
        if not match:
            return ""
        host, path = match.group("host"), match.group("path")
    parts = [p for p in path.strip("/").split("/") if p]
    if not host or len(parts) < 2:
        return ""
    owner, repo = parts[0], parts[1]
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return ""
    return f"{host}/{owner}/{repo}".lower()


def _is_ssh_remote(url: str | None) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    if "://" in text:
        return text.lower().startswith(("ssh://", "git+ssh://", "ssh+git://"))
    return bool(_SCP_LIKE.match(text)) and not re.match(r"^[A-Za-z]:[\\/]", text)  # not a Windows path


def _is_official_ssh_remote(url: str | None) -> bool:
    return _is_ssh_remote(url) and _canonical_github_remote(url) == _OFFICIAL_REPO_CANONICAL


# ---------------------------------------------------------------------- reading the repo
def _resolve_repo_dir() -> Optional[Path]:
    """The git checkout Robo is running from, or ``None`` for non-git installs.

    The running code's own location wins over ``<robo home>/robo-engineer``,
    which can be a stale copy carried over when a profile was cloned.
    """
    candidates = [Path(__file__).resolve().parent.parent]
    try:
        candidates.append(get_robo_home() / "robo-engineer")
    except Exception as exc:
        logger.debug("update check: no robo home: %s", exc)
    for candidate in candidates:
        try:
            if (candidate / ".git").exists():
                return candidate
        except OSError:
            continue
    return None


def _git_dir(repo_dir: Path) -> Optional[Path]:
    dot_git = repo_dir / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():  # worktree or submodule: "gitdir: <path>"
        first = dot_git.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0]
        if first.lower().startswith("gitdir:"):
            target = Path(first.split(":", 1)[1].strip())
            return target if target.is_absolute() else (repo_dir / target).resolve()
    return None


def _read_head_sha(repo_dir: Path) -> Optional[str]:
    """Current commit, read from ``.git`` directly so checking the cache never
    has to start a process. ``None`` when it cannot be determined."""
    try:
        git_dir = _git_dir(repo_dir)
        if git_dir is None:
            return None
        head = (git_dir / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
        if _SHA.match(head):
            return head.lower()
        if not head.startswith("ref:"):
            return None
        ref = head.split(":", 1)[1].strip()
        roots = [git_dir]
        common = git_dir / "commondir"
        if common.is_file():
            shared = Path(common.read_text(encoding="utf-8").strip())
            roots.append(shared if shared.is_absolute() else (git_dir / shared).resolve())
        for root in roots:
            loose = root / ref
            if loose.is_file():
                value = loose.read_text(encoding="utf-8").strip()
                if _SHA.match(value):
                    return value.lower()
            packed = root / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
                    sha, _, name = line.partition(" ")
                    if name.strip() == ref and _SHA.match(sha):
                        return sha.lower()
    except (OSError, IndexError, ValueError) as exc:
        logger.debug("update check: could not read HEAD: %s", exc)
    return None


def _git_short_hash(repo_dir: Path, rev: str) -> Optional[str]:
    """``rev`` as an 8-character hash, or ``None`` if it does not resolve."""
    value = _git_stdout(["rev-parse", "--short=8", rev], cwd=repo_dir)
    return value if value and _SHA.match(value) else None


# -------------------------------------------------------------------------- the two checks
def _check_via_rev(local_rev: str) -> Optional[int]:
    """For builds with a baked-in revision (``ROBO_REVISION``): ask the official
    repository for the tip of ``main`` and compare.

    ``0`` up to date, ``UPDATE_AVAILABLE_NO_COUNT`` behind, ``None`` unknown.
    """
    local = str(local_rev or "").strip().lower()
    if not _SHA.match(local):
        return None
    done = _run_git(["ls-remote", _UPSTREAM_REPO_URL, "refs/heads/main"], cwd=None, timeout=_NETWORK_TIMEOUT)
    if done is None or done.returncode != 0:
        return None
    remote = ((done.stdout or "").split() or [""])[0].lower()
    if not _SHA.match(remote):
        return None
    same = remote.startswith(local) or local.startswith(remote)
    return 0 if same else UPDATE_AVAILABLE_NO_COUNT


def _check_via_local_git(repo_dir: Path) -> Optional[int]:
    """How far ``HEAD`` is behind ``main`` on the remote.

    The range is ``HEAD..origin/main`` — not the branch's own upstream — so a
    feature-branch checkout still reports against the release line. Shallow
    clones have no history to count, so they report presence only.
    """
    origin = _git_stdout(["remote", "get-url", "origin"], cwd=repo_dir)
    if not origin:
        return None

    target = "origin/main"
    if _is_ssh_remote(origin):
        if _is_official_ssh_remote(origin):
            # Same repository, reachable anonymously: use HTTPS rather than risk
            # an SSH passphrase or host-key prompt during start-up.
            fetched = _run_git(["fetch", "--quiet", "--no-tags", _UPSTREAM_REPO_URL, "main"],
                               cwd=repo_dir, timeout=_NETWORK_TIMEOUT)
            if fetched is None or fetched.returncode != 0:
                return None
            target = "FETCH_HEAD"
        # A fork over SSH: stay off the network and compare with the last
        # origin/main this checkout already knows about.
    else:
        fetched = _run_git(["fetch", "--quiet", "--no-tags", "origin", "main"], cwd=repo_dir, timeout=_NETWORK_TIMEOUT)
        if fetched is None or fetched.returncode != 0:
            return None

    tip = _git_stdout(["rev-parse", "--verify", "--quiet", f"{target}^{{commit}}"], cwd=repo_dir)
    head = _git_stdout(["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], cwd=repo_dir)
    if not tip or not head:
        return None
    if tip == head:
        return 0

    if _git_stdout(["rev-parse", "--is-shallow-repository"], cwd=repo_dir) == "true":
        ahead_only = _run_git(["merge-base", "--is-ancestor", tip, head], cwd=repo_dir, timeout=_LOCAL_TIMEOUT)
        if ahead_only is not None and ahead_only.returncode == 0:
            return 0  # the release tip is already part of this checkout
        return UPDATE_AVAILABLE_NO_COUNT

    count = _git_stdout(["rev-list", "--count", f"HEAD..{target}"], cwd=repo_dir)
    try:
        return max(0, int(count)) if count is not None else None
    except ValueError:
        return None


# ------------------------------------------------------------------------------- the cache
def _cache_path() -> Optional[Path]:
    try:
        return get_robo_home() / _UPDATE_CACHE_FILE
    except Exception:
        return None


def _current_version() -> str:
    try:
        from robo_cli import __version__

        return str(__version__)
    except Exception:
        return ""


def _read_cache(*, head: Optional[str], revision: Optional[str]) -> Optional[int]:
    """The cached answer if it is still trustworthy, else ``None``."""
    path = _cache_path()
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    behind, stamp = data.get("behind"), data.get("ts")
    if isinstance(behind, bool) or not isinstance(behind, int) or behind < UPDATE_AVAILABLE_NO_COUNT:
        return None
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return None
    age = time.time() - stamp
    if age < 0 or age >= _UPDATE_CHECK_CACHE_SECONDS:  # age < 0: the clock moved; do not trust it
        return None
    if data.get("ver") != _current_version():
        return None
    if head and data.get("head") and data["head"] != head:
        return None
    if revision and data.get("rev") and data["rev"] != revision:
        return None
    return behind


def _write_cache(behind: int, *, head: Optional[str], revision: Optional[str]) -> None:
    path = _cache_path()
    if path is None:
        return
    record: dict = {"ts": time.time(), "behind": behind, "ver": _current_version()}
    if head:
        record["head"] = head
    if revision:
        record["rev"] = revision
    scratch: Optional[Path] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        scratch = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        scratch.write_text(json.dumps(record), encoding="utf-8")
        os.replace(scratch, path)  # atomic: a reader never sees half a file
    except (OSError, ValueError) as exc:  # ValueError: a path the OS cannot express
        logger.debug("update check: could not write cache: %s", exc)
        try:
            if scratch is not None:
                scratch.unlink(missing_ok=True)  # never leave a scratch file in the user's home
        except (OSError, ValueError):
            pass


def check_for_updates() -> Optional[int]:
    """Is a newer Robo available?

    Returns the number of commits behind, ``UPDATE_AVAILABLE_NO_COUNT`` (-1)
    when behind by an unknown amount, ``0`` when up to date, or ``None`` when
    the check failed, was switched off, or does not apply to this install.
    Successful answers are cached for six hours; failures are not cached.
    """
    if os.environ.get("ROBO_NO_UPDATE_CHECK", "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    try:
        revision = (os.environ.get("ROBO_REVISION") or "").strip().lower() or None
        repo_dir = None if revision else _resolve_repo_dir()
        head = _read_head_sha(repo_dir) if repo_dir else None

        cached = _read_cache(head=head, revision=revision)
        if cached is not None:
            return cached

        if revision:
            behind = _check_via_rev(revision)
        elif repo_dir is not None:
            behind = _check_via_local_git(repo_dir)
        else:
            behind = None
        if behind is not None:
            _write_cache(behind, head=head, revision=revision)
        return behind
    except Exception as exc:  # a start-up nicety must never become a start-up failure
        logger.debug("update check failed: %s", exc)
        return None


# ------------------------------------------------------------------ facts for the banner
def get_git_banner_state(repo_dir: Optional[Path] = None) -> Optional[dict]:
    """``{"upstream": sha, "local": sha, "ahead": n}`` for the banner title.

    Reads the checkout when there is one. Images built without ``.git`` fall
    back to the build's baked-in commit, reported as ``upstream == local`` with
    nothing ahead, since a built image is pinned to exactly one commit.
    """
    try:
        repo = Path(repo_dir) if repo_dir is not None else _resolve_repo_dir()
        if repo is not None and (repo / ".git").exists():
            upstream = _git_short_hash(repo, "origin/main")
            local = _git_short_hash(repo, "HEAD")
            if upstream and local:
                ahead = 0
                count = _git_stdout(["rev-list", "--count", "origin/main..HEAD"], cwd=repo)
                if count and count.isdigit():
                    ahead = int(count)
                return {"upstream": upstream, "local": local, "ahead": ahead}
            return None
        from robo_cli.build_info import get_build_sha

        sha = get_build_sha(8)
        return {"upstream": sha, "local": sha, "ahead": 0} if sha else None
    except Exception as exc:
        logger.debug("banner git state unavailable: %s", exc)
        return None


# ``None`` means "not looked up yet"; a looked-up answer is stored as ``(answer,)``
# so that a genuine "no tag" is remembered too. Tests reset this to ``None``.
_latest_release_cache: Any = None


def get_latest_release_tag(repo_dir: Optional[Path] = None) -> Optional[tuple]:
    """``(tag, release_url)`` for the newest tag reachable from HEAD, or ``None``.

    Local only, and looked up once per process. The URL always points at Ignitee
    Now's repository; a fork gets ``(tag, None)`` — a tag, but no link, because
    its tags are not Ignitee Now's releases.
    """
    global _latest_release_cache
    if _latest_release_cache is not None:
        return _latest_release_cache[0]
    answer: Optional[tuple] = None
    try:
        repo = Path(repo_dir) if repo_dir is not None else _resolve_repo_dir()
        if repo is not None:
            tag = _git_stdout(["describe", "--tags", "--abbrev=0"], cwd=repo)
            if tag and _SAFE_TAG.match(tag):
                origin = _git_stdout(["remote", "get-url", "origin"], cwd=repo)
                official = _canonical_github_remote(origin) == _OFFICIAL_REPO_CANONICAL
                answer = (tag, f"{_RELEASE_URL_BASE}/{quote(tag, safe='')}" if official else None)
    except Exception as exc:
        logger.debug("latest release tag unavailable: %s", exc)
    _latest_release_cache = (answer,)
    return answer


# ------------------------------------------------------------------- background prefetch
_update_result: Optional[int] = None
_update_check_done = threading.Event()
_prefetch_thread: Optional[threading.Thread] = None
_prefetch_lock = threading.Lock()


def prefetch_update_check() -> None:
    """Start the check on a daemon thread and return at once. Calling it again
    while a check is running, or after one has finished, does nothing."""
    global _prefetch_thread
    done = _update_check_done  # bind now: tests swap the module-level event

    def work() -> None:
        global _update_result
        try:
            _update_result = check_for_updates()
        except Exception as exc:
            logger.debug("update prefetch failed: %s", exc)
            _update_result = None
        finally:
            done.set()

    with _prefetch_lock:
        if done.is_set() or (_prefetch_thread is not None and _prefetch_thread.is_alive()):
            return
        _prefetch_thread = threading.Thread(target=work, name="robo-update-check", daemon=True)
        _prefetch_thread.start()


def get_update_result(timeout: float = 0.5) -> Optional[int]:
    """The prefetched answer, waiting up to ``timeout`` seconds for it. ``None``
    if it is not ready (or there is nothing to report)."""
    if not _update_check_done.wait(timeout=max(0.0, float(timeout))):
        return None
    return _update_result


# --- Presentation lives in robo_cli.welcome_banner (Ignitee Now). Re-exported here
# because this module is the import path the rest of the codebase uses, and so
# that tests which replace collaborators on this module keep working.
from robo_cli.welcome_banner import (  # noqa: E402,F401
    ROBO_AGENT_LOGO,
    ROBO_HERO,
    _BOLD,
    _DIM,
    _GOLD,
    _RST,
    _display_toolset_name,
    _format_context_length,
    _skin_color,
    build_welcome_banner,
    cprint,
    format_banner_version_label,
    get_available_skills,
)
