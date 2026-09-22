"""Tests for the concurrent authorization gate and human-wait accounting (#79719).

Before the fix, a worker wedged *inside* the authorization gate — a hanging
``pre_tool_call`` plugin, or an approval round-trip to a client that went
away — had two coupled failure modes:

1. The serialization lock was an unbounded blocking acquire: every other
   worker needing authorization blocked behind the wedged holder forever.
2. ``excluded_seconds()`` measured residency in ``gate.run()`` (arbitrary
   code), so an open window grew 1:1 with wall clock while the batch-deadline
   loop added it to the deadline on every poll — ``remaining`` was constant
   and the deadline NEVER fired. Algebraically:
   ``remaining = (deadline + (now - window_started)) - now = deadline - window_started``.

The fix moves deadline exclusion to the source of the human wait
(``tools.approval.human_wait_window`` around the CLI prompt and the gateway
approval poll loop) and bounds the serialization lock acquire. A wedged
plugin now contributes nothing to the exclusion, so the batch times out
normally; a genuine approval wait is still excluded in full.
"""

import threading
import time

import pytest

from agent.tool_executor import _ConcurrentToolAuthorizationGate
from tools import approval as approval_mod


@pytest.fixture(autouse=True)
def _clean_human_wait_state():
    with approval_mod._human_wait_lock:
        approval_mod._human_wait_states.clear()
    yield
    with approval_mod._human_wait_lock:
        approval_mod._human_wait_states.clear()


SESSION = "test-session-79719"


def _make_gate(**kwargs) -> _ConcurrentToolAuthorizationGate:
    # Pin the session key so contextvar/env noise from other tests can't
    # change which wait state the gate reads.
    return _ConcurrentToolAuthorizationGate(session_key=SESSION, **kwargs)


class TestHumanWaitTracker:
    def test_no_wait_reports_zero(self):
        assert approval_mod.human_wait_seconds(SESSION) == 0.0

    def test_open_window_counts(self):
        opened = threading.Event()
        release = threading.Event()

        def _wait():
            with approval_mod.human_wait_window(SESSION):
                opened.set()
                release.wait(timeout=5)

        t = threading.Thread(target=_wait, daemon=True)
        t.start()
        assert opened.wait(timeout=5)
        time.sleep(0.05)
        assert approval_mod.human_wait_seconds(SESSION) > 0.0
        release.set()
        t.join(timeout=5)
        # Window closed: total is frozen (completed_seconds), not still growing.
        first = approval_mod.human_wait_seconds(SESSION)
        time.sleep(0.05)
        assert approval_mod.human_wait_seconds(SESSION) == pytest.approx(first)

    def test_overlapping_windows_coalesce(self):
        """Two concurrent windows on one session must not double-count wall clock."""
        release = threading.Event()
        started = threading.Barrier(3)

        def _wait():
            with approval_mod.human_wait_window(SESSION):
                started.wait(timeout=5)
                release.wait(timeout=5)

        threads = [threading.Thread(target=_wait, daemon=True) for _ in range(2)]
        start = time.monotonic()
        for t in threads:
            t.start()
        started.wait(timeout=5)
        time.sleep(0.1)
        release.set()
        for t in threads:
            t.join(timeout=5)
        elapsed = time.monotonic() - start
        # Coalesced: recorded ≤ wall clock (a double count would be ~2×).
        assert approval_mod.human_wait_seconds(SESSION) <= elapsed + 0.05

    def test_sessions_are_isolated(self):
        with approval_mod.human_wait_window("other-session"):
            time.sleep(0.05)
            assert approval_mod.human_wait_seconds(SESSION) == 0.0
        assert approval_mod.human_wait_seconds("other-session") > 0.0

    def test_open_window_clamped_to_approval_timeout(self, monkeypatch):
        """A window that overstays approvals.timeout is itself wedged and must
        stop extending the exclusion (belt-and-braces for #79719)."""
        monkeypatch.setattr(approval_mod, "_get_approval_timeout", lambda: 300)
        with approval_mod.human_wait_window(SESSION):
            state = approval_mod._human_wait_states[SESSION]
            # Simulate a window that has been open for a full day.
            state.window_started = time.monotonic() - 86_400.0
            assert approval_mod.human_wait_seconds(SESSION) <= 300.0 + 60.0

    def test_eviction_keeps_pending_sessions(self):
        with approval_mod.human_wait_window(SESSION):
            for i in range(approval_mod._HUMAN_WAIT_MAX_SESSIONS + 8):
                with approval_mod.human_wait_window(f"burst-{i}"):
                    pass
            # The active session survived the eviction pressure and the table
            # stayed at (or under) its cap.
            assert SESSION in approval_mod._human_wait_states
            assert approval_mod._human_wait_states[SESSION].pending == 1
            assert (
                len(approval_mod._human_wait_states)
                <= approval_mod._HUMAN_WAIT_MAX_SESSIONS
            )

    def test_late_close_of_wedged_window_is_clamped(self, monkeypatch):
        """A wedged window that eventually CLOSES must not retroactively inject
        its full overstay into completed_seconds (close-side clamp)."""
        monkeypatch.setattr(approval_mod, "_get_approval_timeout", lambda: 300)
        with approval_mod.human_wait_window(SESSION):
            state = approval_mod._human_wait_states[SESSION]
            # Simulate the window having been open for a full day before close.
            state.window_started = time.monotonic() - 86_400.0
        assert approval_mod.human_wait_seconds(SESSION) <= 300.0 + 60.0


class TestIsHumanWaitPending:
    """Direct coverage for is_human_wait_pending — the primitive the
    concurrent-batch submit loop (agent/tool_executor.py) uses to hold off
    submitting the next tool call while an earlier one in the same batch is
    genuinely blocked on a pending human approval decision.
    """

    def test_no_wait_reports_false(self):
        assert approval_mod.is_human_wait_pending(SESSION) is False

    def test_open_window_reports_true(self):
        opened = threading.Event()
        release = threading.Event()

        def _wait():
            with approval_mod.human_wait_window(SESSION):
                opened.set()
                release.wait(timeout=5)

        t = threading.Thread(target=_wait, daemon=True)
        t.start()
        assert opened.wait(timeout=5)
        assert approval_mod.is_human_wait_pending(SESSION) is True
        release.set()
        t.join(timeout=5)

    def test_closed_window_reports_false_again(self):
        with approval_mod.human_wait_window(SESSION):
            assert approval_mod.is_human_wait_pending(SESSION) is True
        # Window closed — a later, unrelated tool call must not be held up
        # by a decision that already resolved.
        assert approval_mod.is_human_wait_pending(SESSION) is False

    def test_overlapping_windows_stay_pending_until_all_close(self):
        """Two dangerous commands in one batch both awaiting approval: the
        gate must stay 'pending' until BOTH resolve, not just the first."""
        release_a = threading.Event()
        release_b = threading.Event()
        both_open = threading.Barrier(3)

        def _wait(release):
            with approval_mod.human_wait_window(SESSION):
                both_open.wait(timeout=5)
                release.wait(timeout=5)

        ta = threading.Thread(target=lambda: _wait(release_a), daemon=True)
        tb = threading.Thread(target=lambda: _wait(release_b), daemon=True)
        ta.start()
        tb.start()
        both_open.wait(timeout=5)

        assert approval_mod.is_human_wait_pending(SESSION) is True
        release_a.set()
        ta.join(timeout=5)
        # First of two resolved — the second is still open.
        assert approval_mod.is_human_wait_pending(SESSION) is True
        release_b.set()
        tb.join(timeout=5)
        assert approval_mod.is_human_wait_pending(SESSION) is False

    def test_sessions_are_isolated(self):
        with approval_mod.human_wait_window("other-session-79719"):
            assert approval_mod.is_human_wait_pending(SESSION) is False
            assert approval_mod.is_human_wait_pending("other-session-79719") is True
        assert approval_mod.is_human_wait_pending("other-session-79719") is False

    def test_defaults_to_current_session_key(self, monkeypatch):
        monkeypatch.setattr(approval_mod, "get_current_session_key", lambda: SESSION)
        with approval_mod.human_wait_window(SESSION):
            assert approval_mod.is_human_wait_pending() is True
        assert approval_mod.is_human_wait_pending() is False


class TestAuthorizationGate:
    def test_serializes_callbacks(self):
        gate = _make_gate()
        state_lock = threading.Lock()
        active = 0
        max_active = 0

        def _callback():
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.03)
            finally:
                with state_lock:
                    active -= 1

        threads = [
            threading.Thread(target=lambda: gate.run(_callback), daemon=True)
            for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert max_active == 1

    def test_lock_timeout_degrades_to_unserialized(self):
        """A wedged lock holder must not park later callers forever."""
        gate = _make_gate(lock_timeout=0.1)
        holder_in = threading.Event()
        release = threading.Event()

        def _wedged():
            holder_in.set()
            release.wait(timeout=10)

        holder = threading.Thread(target=lambda: gate.run(_wedged), daemon=True)
        holder.start()
        assert holder_in.wait(timeout=5)

        done = threading.Event()
        result = {}

        def _second():
            result["value"] = gate.run(lambda: "ran-unserialized")
            done.set()

        t = threading.Thread(target=_second, daemon=True)
        start = time.monotonic()
        t.start()
        assert done.wait(timeout=5), "second caller starved behind wedged holder"
        assert result["value"] == "ran-unserialized"
        assert time.monotonic() - start < 2.0
        release.set()
        holder.join(timeout=5)

    def test_wedged_callback_contributes_nothing_to_exclusion(self):
        """THE #79719 regression: gate residency is not deadline exclusion."""
        gate = _make_gate()
        wedged_in = threading.Event()
        release = threading.Event()

        def _wedged():
            wedged_in.set()
            release.wait(timeout=10)

        t = threading.Thread(target=lambda: gate.run(_wedged), daemon=True)
        t.start()
        assert wedged_in.wait(timeout=5)
        time.sleep(0.15)
        # No human prompt is pending — the wedge is invisible to the deadline.
        assert gate.excluded_seconds() == 0.0
        release.set()
        t.join(timeout=5)

    def test_deadline_arithmetic_converges_with_wedged_worker(self):
        """The issue's repro: remaining must DECREASE while a worker is wedged.

        Pre-fix, ``remaining = deadline - window_started`` was constant for
        the life of the wedge (24h simulated in the issue). Now the exclusion
        stays 0 for a wedge, so remaining tracks wall clock down to zero.
        """
        gate = _make_gate()
        wedged_in = threading.Event()
        release = threading.Event()

        def _wedged():
            wedged_in.set()
            release.wait(timeout=10)

        t = threading.Thread(target=lambda: gate.run(_wedged), daemon=True)
        t.start()
        assert wedged_in.wait(timeout=5)

        timeout_s = 0.3
        deadline = time.monotonic() + timeout_s
        first = deadline + gate.excluded_seconds() - time.monotonic()
        time.sleep(0.15)
        second = deadline + gate.excluded_seconds() - time.monotonic()
        assert second < first, "remaining is constant — deadline never fires (#79719)"
        time.sleep(0.25)
        assert deadline + gate.excluded_seconds() - time.monotonic() <= 0, (
            "deadline never became due despite the wedge"
        )
        release.set()
        t.join(timeout=5)

    def test_human_wait_is_excluded(self):
        """A genuine approval wait during the batch extends the deadline."""
        gate = _make_gate()
        with approval_mod.human_wait_window(SESSION):
            time.sleep(0.1)
        assert gate.excluded_seconds() >= 0.09

    def test_baseline_ignores_waits_before_batch(self):
        """Approval waits from BEFORE this batch must not extend its deadline."""
        with approval_mod.human_wait_window(SESSION):
            time.sleep(0.1)
        gate = _make_gate()
        assert gate.excluded_seconds() == 0.0

    def test_other_sessions_wait_not_excluded(self):
        gate = _make_gate()
        with approval_mod.human_wait_window("unrelated-session"):
            time.sleep(0.05)
        assert gate.excluded_seconds() == 0.0


class TestApprovalPathsRecordHumanWait:
    def test_await_gateway_decision_records_wait(self, monkeypatch):
        """The gateway approval poll loop must mark itself as human wait."""
        monkeypatch.setattr(approval_mod, "_get_approval_timeout", lambda: 300)
        approval_data = {
            "command": "rm -rf /tmp/x",
            "description": "test",
            "pattern_key": "k",
            "pattern_keys": ["k"],
        }
        notified = threading.Event()
        result_holder = {}

        def _worker():
            result_holder["result"] = approval_mod._await_gateway_decision(
                SESSION, lambda _data: notified.set(), approval_data
            )

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        assert notified.wait(timeout=5)
        time.sleep(0.1)
        try:
            assert approval_mod.human_wait_seconds(SESSION) > 0.0
        finally:
            # Resolve the pending entry via the real production path.
            approval_mod.resolve_gateway_approval(SESSION, "deny", resolve_all=True)
            t.join(timeout=5)
        assert not t.is_alive()
        # Window closed once the wait resolved.
        assert approval_mod._human_wait_states[SESSION].pending == 0

    def test_prompt_dangerous_approval_records_wait(self, monkeypatch):
        """The CLI prompt path must mark itself as human wait."""
        observed = {}

        def _callback(_command, _description, **_kwargs):
            observed["during"] = approval_mod.human_wait_seconds()
            return "deny"

        choice = approval_mod.prompt_dangerous_approval(
            "rm -rf /tmp/x", "test", approval_callback=_callback
        )
        assert choice == "deny"
        # The window was open while the callback (the human prompt) ran.
        state = approval_mod._human_wait_states.get(
            approval_mod.get_current_session_key()
        )
        assert state is not None
        assert state.pending == 0


class TestConcurrentApprovalsDoNotOverlap:
    """Two tool calls in one concurrent batch that BOTH need approval must
    not show overlapping prompts — the second waits for the first to clear
    before it notifies at all. A safe (non-approval) tool call never reaches
    _await_gateway_decision, so it's unaffected by anything tested here —
    but it is NOT unaffected by pending approvals generally: it now waits on
    the same is_human_wait_pending signal from a different point
    (agent/tool_executor.py's _execute; see
    tests/run_agent/test_start_order_gate.py's TestSafeCallWaitsForPendingApproval
    for that coverage). This class only covers the narrower case: two calls
    that both independently need a human decision.
    """

    def test_second_call_does_not_notify_until_first_clears(self, monkeypatch):
        monkeypatch.setattr(approval_mod, "_get_approval_timeout", lambda: 300)
        approval_a = {
            "command": "rm -rf /tmp/a", "description": "a",
            "pattern_key": "ka", "pattern_keys": ["ka"],
        }
        approval_b = {
            "command": "rm -rf /tmp/b", "description": "b",
            "pattern_key": "kb", "pattern_keys": ["kb"],
        }
        notified_a = threading.Event()
        notified_b = threading.Event()
        results = {}

        def _worker(label, data, notified):
            results[label] = approval_mod._await_gateway_decision(
                SESSION, lambda _d, ev=notified: ev.set(), data
            )

        ta = threading.Thread(
            target=_worker, args=("a", approval_a, notified_a), daemon=True
        )
        ta.start()
        assert notified_a.wait(timeout=5), "first call must notify right away"

        tb = threading.Thread(
            target=_worker, args=("b", approval_b, notified_b), daemon=True
        )
        tb.start()
        # The second call must be queueing behind the first, not yet showing
        # its own prompt. This is the actual bug: without the fix, the
        # second call notifies immediately, giving the user two overlapping
        # Allow/Deny prompts (or, at the tool-executor level, the second
        # tool proceeding without ever asking at all).
        time.sleep(0.3)
        assert not notified_b.is_set(), (
            "second approval notified while the first was still pending — "
            "prompts overlapped instead of queueing"
        )

        # Resolve ONLY the first (FIFO default) via the real production path.
        approval_mod.resolve_gateway_approval(SESSION, "deny")
        ta.join(timeout=5)
        assert results["a"]["choice"] == "deny"

        # The second must now proceed and notify.
        assert notified_b.wait(timeout=5), "second call never notified after first cleared"
        approval_mod.resolve_gateway_approval(SESSION, "deny")
        tb.join(timeout=5)
        assert results["b"]["choice"] == "deny"
        assert not ta.is_alive() and not tb.is_alive()

    def test_unrelated_session_is_never_delayed(self, monkeypatch):
        """A pending approval in session A must not delay session B at all —
        this is what keeps a genuinely unrelated task from waiting on
        someone else's decision."""
        monkeypatch.setattr(approval_mod, "_get_approval_timeout", lambda: 300)
        approval_a = {
            "command": "rm -rf /tmp/a", "description": "a",
            "pattern_key": "ka", "pattern_keys": ["ka"],
        }
        approval_other = {
            "command": "rm -rf /tmp/o", "description": "o",
            "pattern_key": "ko", "pattern_keys": ["ko"],
        }
        notified_a = threading.Event()
        notified_other = threading.Event()

        def _worker(session, data, notified):
            approval_mod._await_gateway_decision(session, lambda _d: notified.set(), data)

        ta = threading.Thread(
            target=_worker, args=(SESSION, approval_a, notified_a), daemon=True
        )
        ta.start()
        assert notified_a.wait(timeout=5)

        t_other = threading.Thread(
            target=_worker,
            args=("unrelated-session-79719", approval_other, notified_other),
            daemon=True,
        )
        t_other.start()
        assert notified_other.wait(timeout=5), (
            "an unrelated session's approval was delayed by a different session's pending prompt"
        )

        approval_mod.resolve_gateway_approval(SESSION, "deny")
        approval_mod.resolve_gateway_approval("unrelated-session-79719", "deny")
        ta.join(timeout=5)
        t_other.join(timeout=5)

