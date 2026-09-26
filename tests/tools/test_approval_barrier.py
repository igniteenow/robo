"""Approval barrier: an open approval prompt must stop the whole agent.

Covers the interactive wait policy (``wait_forever`` / ``halt_on_deny``)
that the TUI/desktop gateway registers, the session-wide barrier that the
conversation loop and tool executor consult, teardown while a prompt is
pending, and the distinction between a deny and an interrupt/redirect.
"""
from __future__ import annotations

import threading
import time

import pytest

from tools import approval


@pytest.fixture(autouse=True)
def _fast_timeout(monkeypatch):
    # A tiny messaging-platform timeout so tests can prove the interactive
    # policy ignores it.
    monkeypatch.setattr(approval, "_get_approval_timeout", lambda: 1)
    monkeypatch.setattr(approval, "_fire_approval_hook", lambda *a, **k: None)
    yield


def _decide(key, data=None, *, surface="gateway"):
    data = data or {"command": "rm -rf build", "description": "recursive delete",
                    "pattern_key": "recursive delete", "pattern_keys": ["recursive delete"]}
    notified = []
    return approval._await_gateway_decision(key, lambda d: notified.append(d), data, surface=surface), notified


def test_wait_forever_policy_outlives_the_config_timeout():
    key = "tui:wait-forever"
    approval.register_gateway_notify(key, lambda d: None, wait_forever=True)
    try:
        assert approval.human_wait_ceiling(key) > 1_000_000
        result = {}

        def run():
            result["decision"], _ = _decide(key)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        # Past the 1s messaging timeout and still parked.
        time.sleep(1.6)
        assert t.is_alive(), "interactive wait expired into a BLOCKED result"
        assert approval.get_pending_gateway_approvals(key)[0]["command"] == "rm -rf build"
        assert approval.has_blocking_approval(key)
        assert approval.resolve_gateway_approval(key, "once") == 1
        t.join(5)
        assert not t.is_alive()
        assert result["decision"]["resolved"] and result["decision"]["choice"] == "once"
    finally:
        approval.unregister_gateway_notify(key)


def test_wait_ceiling_fits_the_platform_lock_limit(monkeypatch):
    # The ceiling is also a lock timeout (the tool executor's authorization
    # gate), and a lock wait past threading.TIMEOUT_MAX raises OverflowError.
    # Windows allows about 49.7 days.
    monkeypatch.setattr(threading, "TIMEOUT_MAX", 4294967.0)
    key = "tui:ceiling"
    approval.register_gateway_notify(key, lambda d: None, wait_forever=True)
    try:
        assert approval.human_wait_ceiling(key) <= threading.TIMEOUT_MAX
    finally:
        approval.unregister_gateway_notify(key)
    monkeypatch.setattr(approval, "_get_approval_timeout", lambda: 10**9)
    assert approval.human_wait_ceiling("telegram:ceiling") <= threading.TIMEOUT_MAX


def test_messaging_policy_still_times_out():
    key = "telegram:bounded"
    approval.register_gateway_notify(key, lambda d: None)
    try:
        t0 = time.monotonic()
        decision, _ = _decide(key)
        assert time.monotonic() - t0 < 4
        assert not decision["resolved"] and decision["choice"] is None
    finally:
        approval.unregister_gateway_notify(key)


def test_deny_halts_turn_via_on_halt_hook():
    key = "tui:deny"
    halts = []
    approval.register_gateway_notify(key, lambda d: None, wait_forever=True, halt_on_deny=True,
                                     on_halt=lambda reason, data: halts.append((reason, data["command"])))
    try:
        def deny_later():
            time.sleep(0.2)
            approval.resolve_gateway_approval(key, "deny", reason="not now")

        threading.Thread(target=deny_later, daemon=True).start()
        decision, _ = _decide(key)
        assert decision["resolved"] and decision["choice"] == "deny" and decision["reason"] == "not now"
        assert halts == [("denied", "rm -rf build")]
    finally:
        approval.unregister_gateway_notify(key)


def test_session_teardown_resolves_as_closed_and_halts():
    key = "tui:closed"
    halts = []
    approval.register_gateway_notify(key, lambda d: None, wait_forever=True, halt_on_deny=True,
                                     on_halt=lambda reason, data: halts.append(reason))
    result = {}

    def run():
        result["decision"], _ = _decide(key)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(0.2)
    approval.unregister_gateway_notify(key)  # client closed the session
    t.join(5)
    assert not t.is_alive()
    d = result["decision"]
    assert d["surface_closed"] and d["choice"] == "deny" and d["reason"] is None
    assert halts == ["closed"]


def test_interrupt_while_pending_is_not_a_deny(monkeypatch):
    key = "tui:interrupted"
    halts = []
    approval.register_gateway_notify(key, lambda d: None, wait_forever=True, halt_on_deny=True,
                                     on_halt=lambda reason, data: halts.append(reason))
    try:
        flag = {"v": False}
        monkeypatch.setattr(approval, "is_interrupted", lambda: flag["v"])

        def interrupt_later():
            time.sleep(0.2)
            flag["v"] = True

        threading.Thread(target=interrupt_later, daemon=True).start()
        decision, _ = _decide(key)
        assert decision["interrupted"] and decision["choice"] == "deny"
        assert halts == []  # the redirect/stop already owns the turn
    finally:
        approval.unregister_gateway_notify(key)


def test_barrier_parks_other_threads_while_prompt_is_open():
    key = "tui:barrier"
    approval.register_gateway_notify(key, lambda d: None, wait_forever=True)
    try:
        token = approval.set_current_session_key(key)
        try:
            release = threading.Event()
            waited = {}

            def holder():
                with approval.human_wait_window(key):
                    release.wait(5)

            h = threading.Thread(target=holder, daemon=True)
            h.start()
            time.sleep(0.1)
            assert approval.is_human_wait_pending(key)

            def other_tool():
                t0 = time.monotonic()
                waited["v"] = approval.wait_for_approval_barrier(key)
                waited["dt"] = time.monotonic() - t0

            o = threading.Thread(target=other_tool, daemon=True)
            o.start()
            time.sleep(0.5)
            assert o.is_alive(), "sibling work proceeded while the prompt was open"
            release.set()
            o.join(5)
            assert waited["v"] is True and waited["dt"] >= 0.4
            assert approval.wait_for_approval_barrier(key) is False
        finally:
            approval.reset_current_session_key(token)
    finally:
        approval.unregister_gateway_notify(key)


def test_check_all_command_guards_reports_interrupt_distinctly(monkeypatch):
    key = "tui:guards"
    approval.register_gateway_notify(key, lambda d: None, wait_forever=True)
    token = approval.set_current_session_key(key)
    try:
        monkeypatch.setattr(approval, "_is_gateway_approval_context", lambda: True)
        monkeypatch.setattr(approval, "_is_interactive_cli", lambda: False)
        monkeypatch.setattr(approval, "_get_approval_mode", lambda: "manual")
        monkeypatch.setattr(approval, "_command_matches_permanent_allowlist", lambda c: False)
        monkeypatch.setattr(approval, "_await_gateway_decision",
                            lambda *a, **k: {"resolved": True, "choice": "deny", "reason": None,
                                             "surface_closed": False, "interrupted": True})
        res = approval.check_all_command_guards("rm -rf build", "local")
        assert res["approved"] is False and res["outcome"] == "interrupted"
        assert "newest instruction" in res["message"]
    finally:
        approval.reset_current_session_key(token)
        approval.unregister_gateway_notify(key)
