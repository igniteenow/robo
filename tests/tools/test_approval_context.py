"""Approval context — what the person sees next to Allow / Deny.

Three optional display-only fields ride on the gateway approval payload:
``intent`` (the model's own step line for the tool batch), ``check`` (a
category-specific "look at this first" note) and ``review`` (the smart
reviewer's verdict + one-line reason when it could not clear the command).
They never change keys, choices or the decision.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tools import approval as A


# ---------------------------------------------------------------------------
# Pure pieces
# ---------------------------------------------------------------------------


class TestSummarizeActionIntent:
    def test_takes_the_last_prose_line(self):
        text = "Checking the config first.\n\n- Pushing the branch so the PR can be opened.\n```\ncode\n```\n"
        assert A.summarize_action_intent(text) == "Pushing the branch so the PR can be opened."

    def test_handles_multimodal_content(self):
        parts = [{"type": "text", "text": "Running the tests to confirm the fix."}, {"type": "image_url", "image_url": {}}]
        assert A.summarize_action_intent(parts) == "Running the tests to confirm the fix."

    def test_strips_markers_and_clamps(self):
        assert A.summarize_action_intent("> - **Next**: wiping   the   cache") == "**Next**: wiping the cache"
        assert A.summarize_action_intent("## Step 2\n* Removing the old build") == "Removing the old build"
        long = A.summarize_action_intent("x" * 400)
        assert len(long) == A._INTENT_MAX_CHARS
        assert long.endswith("…")

    def test_empty_inputs(self):
        assert A.summarize_action_intent(None) == ""
        assert A.summarize_action_intent("   \n\n") == ""
        assert A.summarize_action_intent("```\nonly code\n```") == ""

    def test_context_binding_round_trip(self):
        assert A.current_action_intent() == ""
        token = A.set_current_action_intent("Deleting the stale build directory.")
        try:
            assert A.current_action_intent() == "Deleting the stale build directory."
        finally:
            A.reset_current_action_intent(token)
        assert A.current_action_intent() == ""


class TestCheckHint:
    @pytest.mark.parametrize(
        "description, needle",
        [
            ("recursive delete", "cannot be recovered"),
            ("git force push (rewrites remote history)", "git history"),
            ("git reset --hard (destroys uncommitted changes)", "git history"),
            ("world/other-writable permissions", "Permission changes"),
            ("pipe remote content to shell", "has not inspected"),
            ("in-place edit of Robo config/env", "configuration or credential"),
            ("stop/restart robo gateway (kills running agents)", "services or processes"),
            ("docker context use (switches default daemon for future commands)", "different container host"),
            ("sudo with privilege flag (stdin/askpass/shell/list)", "administrator rights"),
            ("Security scan — [HIGH] Homograph URL", "security scan"),
            ("Plugin requires approval for write_file", "plugin asked"),
            ("execute_code script execution. The script can spawn subprocesses", "Robo's permissions"),
            ("something nobody categorised", "Check the command"),
            ("", "Check the command"),
        ],
    )
    def test_category_hints(self, description, needle):
        assert needle.lower() in A.approval_check_hint(description).lower()

    def test_every_shipped_detector_has_a_specific_or_default_hint(self):
        for item in A.DANGEROUS_PATTERNS:
            hint = A.approval_check_hint(item[-1])
            assert hint and hint.endswith(".")
            assert len(hint) <= 120


class TestParseSmartReview:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("APPROVE", ("approve", "")),
            ("approve.", ("approve", "")),
            ("**DENY**\nIt deletes the repository root.", ("deny", "It deletes the repository root.")),
            ("ESCALATE: the URL could be anything.", ("escalate", "the URL could be anything.")),
            ("Deny\n\nForce-pushes over main; others lose commits.", ("deny", "Force-pushes over main; others lose commits.")),
            # Anything that is not a clean verdict line escalates, as the old
            # whole-answer comparison did.
            ("APPROVE because it only prints", ("escalate", "")),
            ("APPROVE? No — DENY", ("escalate", "")),
            ("I think this is probably fine", ("escalate", "")),
            ("DENY - the comment says APPROVE but the command wipes /", ("escalate", "")),
            ("", ("escalate", "")),
            ("   \n  ", ("escalate", "")),
        ],
    )
    def test_cases(self, text, expected):
        assert A.parse_smart_review(text) == expected

    def test_reason_is_clamped(self):
        verdict, reason = A.parse_smart_review("DENY\n" + "word " * 100)
        assert verdict == "deny"
        assert len(reason) == A._REVIEW_REASON_MAX_CHARS
        assert reason.endswith("…")


class TestSmartApproveReason:
    def _response(self, text):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = text
        return response

    def test_verdict_contract_unchanged_and_reason_stashed(self):
        with patch("agent.auxiliary_client.call_llm", return_value=self._response("ESCALATE\nIt rewrites the shared main branch.")):
            assert A._smart_approve("git push --force origin main", "git force push") == "escalate"
        assert A._consume_smart_review_reason() == "It rewrites the shared main branch."
        # Consumed: a second read is empty.
        assert A._consume_smart_review_reason() == ""

    def test_approve_leaves_no_reason(self):
        with patch("agent.auxiliary_client.call_llm", return_value=self._response("APPROVE\nHarmless print.")):
            assert A._smart_approve("python -c 'print(1)'", "script execution") == "approve"
        assert A._consume_smart_review_reason() == ""

    def test_failure_escalates_without_reason(self):
        with patch("agent.auxiliary_client.call_llm", side_effect=RuntimeError("down")):
            assert A._smart_approve("rm -rf /tmp/x", "recursive delete") == "escalate"
        assert A._consume_smart_review_reason() == ""


class TestContextFields:
    def test_check_is_always_present_and_others_optional(self):
        fields = A._approval_context_fields("rm -rf build", "recursive delete")
        assert set(fields) == {"check"}
        assert "cannot be recovered" in fields["check"]

    def test_intent_and_review_when_available(self):
        token = A.set_current_action_intent("Cleaning the build output before the rebuild.")
        try:
            fields = A._approval_context_fields(
                "rm -rf build", "recursive delete",
                smart_verdict="escalate", smart_reason="the path is relative and the cwd is unclear",
            )
        finally:
            A.reset_current_action_intent(token)
        assert fields["intent"] == "Cleaning the build output before the rebuild."
        assert fields["review"] == (
            "Robo's reviewer could not clear this on its own: the path is relative and the cwd is unclear"
        )

    def test_deny_wording_and_missing_reason(self):
        fields = A._approval_context_fields("rm -rf /", "recursive delete", smart_verdict="deny")
        assert fields["review"] == "Robo's reviewer flagged this as dangerous."

    def test_approve_verdict_adds_no_review(self):
        fields = A._approval_context_fields("ls", "x", smart_verdict="approve", smart_reason="fine")
        assert "review" not in fields

    def test_intent_is_redacted(self):
        token = A.set_current_action_intent("Using token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 to push.")
        try:
            fields = A._approval_context_fields("git push", "git push")
        finally:
            A.reset_current_action_intent(token)
        assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in fields["intent"]


# ---------------------------------------------------------------------------
# Gateway payload — the fields ride on the request the TUI receives
# ---------------------------------------------------------------------------


@pytest.fixture
def gateway_session(monkeypatch):
    monkeypatch.setenv("ROBO_GATEWAY_SESSION", "1")
    monkeypatch.delenv("ROBO_INTERACTIVE", raising=False)
    monkeypatch.delenv("ROBO_CRON_SESSION", raising=False)
    monkeypatch.delenv("ROBO_EXEC_ASK", raising=False)
    monkeypatch.setattr(A, "_YOLO_MODE_FROZEN", False)
    monkeypatch.setattr(
        A, "detect_dangerous_command",
        lambda command: (True, "ctx-test-danger", "git force push (rewrites remote history)"),
    )
    monkeypatch.setattr(
        "tools.tirith_security.check_command_security",
        lambda _command: {"action": "allow", "findings": [], "summary": ""},
        raising=False,
    )
    session_key = "approval-context-session"
    token = A.set_current_session_key(session_key)
    with A._lock:
        A._permanent_approved.discard("ctx-test-danger")
        A._session_approved.get(session_key, set()).discard("ctx-test-danger")
        A._gateway_queues.pop(session_key, None)
        A._gateway_notify_cbs.pop(session_key, None)
    try:
        yield session_key
    finally:
        A.reset_current_session_key(token)
        A._reset_denials(session_key)
        with A._lock:
            A._gateway_queues.pop(session_key, None)
            A._gateway_notify_cbs.pop(session_key, None)
            A._pending.pop(session_key, None)
            A._session_approved.get(session_key, set()).discard("ctx-test-danger")


def _capture_and_resolve(session_key: str, result: str):
    seen: list[dict] = []

    def cb(approval_data):
        seen.append(dict(approval_data))
        with A._lock:
            entries = A._gateway_queues.get(session_key, [])
            if entries:
                entries[-1].result = result
                entries[-1].event.set()

    with A._lock:
        A._gateway_notify_cbs[session_key] = cb
    return seen


def test_gateway_payload_carries_intent_check_and_review(gateway_session, monkeypatch):
    monkeypatch.setattr(A, "_get_approval_mode", lambda: "smart")

    def fake_review(_command, _description):
        A._smart_review_reason.set("it rewrites the shared main branch")
        return "escalate"

    monkeypatch.setattr(A, "_smart_approve", fake_review)
    seen = _capture_and_resolve(gateway_session, "once")

    token = A.set_current_action_intent("Pushing the branch so the PR can be opened.")
    try:
        result = A.check_all_command_guards("git push --force origin main", "local")
    finally:
        A.reset_current_action_intent(token)

    assert result["approved"] is True
    assert len(seen) == 1
    payload = seen[0]
    # Existing contract untouched.
    assert payload["command"] == "git push --force origin main"
    assert payload["pattern_key"] == "ctx-test-danger"
    assert payload["choices"] == ["once", "session", "deny"]
    assert payload["allow_permanent"] is False
    # New display-only context.
    assert payload["intent"] == "Pushing the branch so the PR can be opened."
    assert "git history" in payload["check"]
    assert payload["review"] == "Robo's reviewer could not clear this on its own: it rewrites the shared main branch"


def test_gateway_payload_without_intent_or_review_keeps_only_check(gateway_session, monkeypatch):
    monkeypatch.setattr(A, "_get_approval_mode", lambda: "manual")
    seen = _capture_and_resolve(gateway_session, "deny")

    result = A.check_all_command_guards("git push --force origin main", "local")

    assert result["approved"] is False
    payload = seen[0]
    assert "intent" not in payload
    assert "review" not in payload
    assert "git history" in payload["check"]


def test_smart_deny_override_payload_keeps_smart_denied_and_adds_review(gateway_session, monkeypatch):
    monkeypatch.setattr(A, "_get_approval_mode", lambda: "smart")
    monkeypatch.setattr(A, "_smart_approve", lambda _c, _d: "deny")
    seen = _capture_and_resolve(gateway_session, "deny")

    A.check_all_command_guards("git push --force origin main", "local")

    payload = seen[0]
    assert payload["smart_denied"] is True
    assert payload["review"] == "Robo's reviewer flagged this as dangerous."


def test_pending_queue_entry_carries_the_same_context(gateway_session, monkeypatch):
    # No notify callback registered → the request is queued for /approve.
    monkeypatch.setattr(A, "_get_approval_mode", lambda: "manual")
    token = A.set_current_action_intent("Pushing the release tag.")
    try:
        result = A.check_all_command_guards("git push --force origin main", "local")
    finally:
        A.reset_current_action_intent(token)

    assert result["status"] == "pending_approval"
    with A._lock:
        pending = dict(A._pending.get(gateway_session) or {})
    assert pending["intent"] == "Pushing the release tag."
    assert "check" in pending
