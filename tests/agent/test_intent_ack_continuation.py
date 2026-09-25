"""Intent-ack continuation gate + detector behavior.

Covers the config-driven generalization of the codex intent-ack continuation
(issue #27881): the historical ``codex_responses``-only path is byte-stable
under the default ``"auto"`` mode, while an explicit ``true``/model-list opt-in
extends the "you announced an action but called no tool — keep going" nudge to
every api_mode and relaxes the codebase/workspace requirement so general
autonomous workflows ("I'll run a health check on the server") are caught.

These are invariant assertions about how the mode string and the detector
gates relate, not snapshots of the marker lists.
"""

from types import SimpleNamespace
from typing import Union

from agent.agent_runtime_helpers import (
    intent_ack_continuation_enabled,
    intent_ack_continuation_mode,
    looks_like_codex_intermediate_ack,
)


def _agent(
    mode: Union[str, bool, list] = "auto",
    api_mode="chat_completions",
    model="anthropic/claude-sonnet-4",
):
    # _strip_think_blocks is a no-op for these plain-text fixtures.
    a = SimpleNamespace(
        _intent_ack_continuation=mode,
        api_mode=api_mode,
        model=model,
        _strip_think_blocks=lambda c: c,
    )
    # The forwarder AIAgent exposes; should_nudge_intent_ack goes through it
    # so a stubbed detector stays in charge.
    a._looks_like_codex_intermediate_ack = (
        lambda user_message, assistant_content, messages, require_workspace=True: looks_like_codex_intermediate_ack(
            a, user_message, assistant_content, messages, require_workspace
        )
    )
    return a


# The reporter's exact repro (#27881): server-ops task, no filesystem reference.
REPRO_USER = (
    "check the current status of the server, grab the latest error logs, "
    "and let me know if there's anything critical"
)
REPRO_ACK = "I will start by running a health check command on the server to see its current status."

# The codex-coding case the detector was originally built for.
CODE_USER = "review the codebase in /app"
CODE_ACK = "Let me inspect the repository files first."


# ── mode resolution ────────────────────────────────────────────────────────




def test_true_is_all_api_modes():
    for am in ("chat_completions", "anthropic", "codex_responses"):
        assert intent_ack_continuation_mode(_agent(True, am)) == "all"
    for s in ("true", "always", "yes", "on", "ON"):
        assert intent_ack_continuation_mode(_agent(s, "chat_completions")) == "all"








def test_missing_attr_defaults_to_auto():
    bare = SimpleNamespace(api_mode="chat_completions", model="x", _strip_think_blocks=lambda c: c)
    assert intent_ack_continuation_mode(bare) == "off"
    bare_codex = SimpleNamespace(api_mode="codex_responses", model="x", _strip_think_blocks=lambda c: c)
    assert intent_ack_continuation_mode(bare_codex) == "codex_only"


def test_enabled_is_mode_not_off():
    assert intent_ack_continuation_enabled(_agent(True, "chat_completions")) is True
    assert intent_ack_continuation_enabled(_agent("auto", "codex_responses")) is True
    assert intent_ack_continuation_enabled(_agent("auto", "chat_completions")) is False
    assert intent_ack_continuation_enabled(_agent(False, "codex_responses")) is False


# ── detector: workspace requirement ─────────────────────────────────────────




def test_multipart_user_message_does_not_crash_on_workspace_path():
    """#9562: vision requests forward ``user_message`` as a multi-part list.

    The OpenAI-compat API server passes the raw ``content`` field straight
    through for vision turns, so ``user_message`` reaches the detector as
    ``[{type:"text",...}, {type:"image_url",...}]``. The ``require_workspace``
    path flattened it with ``(user_message or "").strip()`` — a truthy list
    survived and ``.strip()`` raised ``AttributeError``, killing the turn.
    The text part still has to drive workspace detection.
    """
    a = _agent("auto", "codex_responses")
    multipart = [
        {"type": "text", "text": CODE_USER},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    msgs = [{"role": "user", "content": multipart}]
    # No crash, and the text part ("review the codebase in /app") still
    # satisfies the workspace requirement so the ack fires.
    assert looks_like_codex_intermediate_ack(
        a, multipart, CODE_ACK, msgs, require_workspace=True
    )


def test_all_path_drops_workspace_requirement():
    """The #27881 fix: opted-in turns catch non-codebase intent acks."""
    a = _agent(True, "chat_completions")
    msgs = [{"role": "user", "content": REPRO_USER}]
    assert looks_like_codex_intermediate_ack(
        a, REPRO_USER, REPRO_ACK, msgs, require_workspace=False
    )


# ── detector: guardrails that hold regardless of workspace ───────────────────










# ── the nudge never overrules a user who steered the turn ─────────────────


def _nudge(agent, *, redirected: bool, user: str, reply: str, ack_count: int = 0, messages=None):
    from agent.agent_runtime_helpers import should_nudge_intent_ack

    agent.valid_tool_names = {"terminal", "web_search"}
    return should_nudge_intent_ack(
        agent,
        user_redirected_turn=redirected,
        ack_count=ack_count,
        user_message=user,
        assistant_content=reply,
        messages=messages or [],
    )


# The user's exact case: "stop" redirected the turn, the model stopped and
# politely offered to "scope it properly" later — future-ack + action verb,
# no tool call — and got a "[System: Continue now]" nudge for its trouble.
STOP_USER = "Hey can you start looking for google 100 subdomains for me please real quick"
STOP_REPLY = (
    "Stopped — nothing was started, no scans or lookups ran.\n\n"
    "If you do want to pick it up later, just tell me the actual target and "
    "what you're after, and I'll scope it properly."
)


def test_stop_reply_would_trip_the_detector_on_its_own():
    """Pin the failure: without the redirect rule this reply IS an 'intent ack'."""
    assert _nudge(_agent(True), redirected=False, user=STOP_USER, reply=STOP_REPLY) is True


def test_redirected_turn_is_never_nudged():
    assert _nudge(_agent(True), redirected=True, user=STOP_USER, reply=STOP_REPLY) is False
    # Not just for opt-in "all" mode: no mode nudges a steered turn.
    assert _nudge(_agent("auto", api_mode="codex_responses"), redirected=True, user=CODE_USER, reply=CODE_ACK) is False


def test_steered_turn_is_never_nudged_either():
    """A /steer lands on a tool result, outside the loop's redirect drain; the
    drains flag the agent (``_turn_user_steered``) and that counts the same."""
    a = _agent(True)
    a._turn_user_steered = True
    assert _nudge(a, redirected=False, user=STOP_USER, reply=STOP_REPLY) is False
    a._turn_user_steered = False
    assert _nudge(a, redirected=False, user=STOP_USER, reply=STOP_REPLY) is True


def test_tool_batch_steer_delivery_flags_the_turn():
    from agent.agent_runtime_helpers import apply_pending_steer_to_tool_results

    a = _agent(True)
    a._turn_user_steered = False
    a._pending_steer = None
    a._drain_pending_steer = lambda: "stop"
    messages = [{"role": "assistant", "content": ""}, {"role": "tool", "content": "ran"}]
    apply_pending_steer_to_tool_results(a, messages, 1)
    assert "stop" in messages[-1]["content"]
    assert a._turn_user_steered is True

    # Nothing to steer with: the flag is left alone.
    b = _agent(True)
    b._turn_user_steered = False
    b._drain_pending_steer = lambda: None
    apply_pending_steer_to_tool_results(b, list(messages), 1)
    assert b._turn_user_steered is False


def test_nudge_goes_through_the_agent_forwarder():
    """Tests elsewhere stub ``agent._looks_like_codex_intermediate_ack``; the
    decision must honour that stub rather than the module function."""
    a = _agent(True)
    seen = {}

    def fake(user_message, assistant_content, messages, require_workspace=True):
        seen["require_workspace"] = require_workspace
        return True

    a._looks_like_codex_intermediate_ack = fake
    assert _nudge(a, redirected=False, user="anything", reply="ok") is True
    assert seen["require_workspace"] is False  # mode "all" drops the workspace requirement


def test_other_gates_still_apply_when_not_redirected():
    assert _nudge(_agent(False), redirected=False, user=REPRO_USER, reply=REPRO_ACK) is False  # mode off
    assert _nudge(_agent(True), redirected=False, user=REPRO_USER, reply=REPRO_ACK, ack_count=2) is False  # cap
    assert _nudge(_agent(True), redirected=False, user=REPRO_USER, reply=REPRO_ACK) is True
    # A tool already ran this turn: the detector itself declines.
    assert (
        _nudge(_agent(True), redirected=False, user=REPRO_USER, reply=REPRO_ACK, messages=[{"role": "tool", "content": "ok"}])
        is False
    )
