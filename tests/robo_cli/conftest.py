"""Fixtures shared across robo_cli kanban tests."""

from __future__ import annotations

import shutil
import sys

import pytest


@pytest.fixture
def all_assignees_spawnable(monkeypatch):
    """Pretend every assignee maps to a real Robo profile.

    Most dispatcher tests use synthetic assignees ("alice", "bob") that
    don't correspond to actual profile directories on disk. Without this
    patch, the dispatcher's profile-exists guard (PR #20105) routes
    those tasks into ``skipped_nonspawnable`` instead of spawning, which
    would break tests that assert spawn behavior.
    """
    from robo_cli import profiles
    monkeypatch.setattr(profiles, "profile_exists", lambda name: True)


@pytest.fixture(autouse=True)
def _suppress_concurrent_robo_gate(request, monkeypatch):
    """Default ``_detect_concurrent_robo_instances`` to ``[]`` for every test.

    The Windows update path now refuses to proceed when another
    ``robo.exe`` is detected (issue #26670). On a developer's Windows
    machine running the test suite via ``robo`` itself, this would
    flag the running agent as a concurrent instance and abort every
    ``cmd_update`` test. Tests that want to exercise the gate explicitly
    re-patch ``_detect_concurrent_robo_instances`` with their own
    return value — autouse here gives a clean default without touching
    the rest of the suite.

    Tests that need to call the REAL function (e.g. unit tests for the
    helper itself) opt out with ``@pytest.mark.real_concurrent_gate``.
    """
    if request.node.get_closest_marker("real_concurrent_gate"):
        return
    try:
        from robo_cli import main as _cli_main
    except Exception:
        return
    # raising=False: under pytest's per-test spawn isolation, a concurrent
    # xdist worker importing a module that transitively touches robo_cli.main
    # can briefly expose a partially-initialized module object here — one where
    # _detect_concurrent_robo_instances isn't defined yet. A bare setattr
    # would raise AttributeError and error the (unrelated) test. The attribute
    # always exists once main.py finishes importing, so a no-op when it's
    # transiently absent is the correct, race-free default.
    monkeypatch.setattr(
        _cli_main,
        "_detect_concurrent_robo_instances",
        lambda *_a, **_k: [],
        raising=False,
    )


@pytest.fixture(autouse=True)
def _hermetic_windows_update_side_effects(request, monkeypatch):
    """On Windows, keep the ``cmd_update`` tests as hermetic as they are on POSIX.

    The update flow's Windows-only steps — pausing (killing) running gateways,
    stopping venv holders, regenerating the Scheduled-Task launcher scripts and
    cold-starting a gateway afterwards — are ``_is_windows()``-gated no-ops on
    Linux/macOS, which is the only reason the ``cmd_update`` tests (with
    ``subprocess.run`` mocked and ``shutil.which`` → None) are safe there. On a
    developer's Windows box the same tests reached the real helpers: they
    stopped the live gateway, scanned and killed venv holders and — because
    ``find_node_executable_on_path`` walks PATH itself instead of going through
    the mocked ``shutil.which`` — found the real npm and ran a real ``npm ci``
    against the checkout. Stub those steps on win32 so a test run never
    mutates the machine.

    Tests of the helpers themselves opt out with
    ``@pytest.mark.real_windows_update_helpers``; a test that patches one of
    these names itself still wins (its patch is applied after this one).
    """
    if sys.platform != "win32":
        return
    if request.node.get_closest_marker("real_windows_update_helpers"):
        return
    try:
        import robo_constants
        from robo_cli import main as _cli_main
    except Exception:
        return
    # raising=False for the same reason as ``_suppress_concurrent_robo_gate``:
    # a partially-initialised ``robo_cli.main`` under xdist must not error
    # an unrelated test.
    for name, stub in (
        ("_pause_windows_gateways_for_update", lambda: None),
        ("_resume_windows_gateways_after_update", lambda token=None: None),
        ("_cold_start_windows_gateway_after_update", lambda: None),
        ("_refresh_windows_gateway_launchers", lambda: None),
        ("_detect_venv_python_processes", lambda: []),
    ):
        monkeypatch.setattr(_cli_main, name, stub, raising=False)
    # POSIX parity: resolve npm/node through ``shutil.which`` (late-bound, so a
    # test's ``patch("shutil.which")`` flows through) instead of the Windows
    # PATH scan that ignores the mock.
    monkeypatch.setattr(
        robo_constants,
        "find_node_executable_on_path",
        lambda command: shutil.which(command),
        raising=False,
    )
