"""Tests for agent.portal_tags — Ignitee Now Portal request tag contract."""

from __future__ import annotations






def test_igniteenow_portal_tags_contains_product_and_client():
    """Every Ignitee Now Portal request gets BOTH the product tag and the version tag."""
    from agent.portal_tags import robo_client_tag, igniteenow_portal_tags

    tags = igniteenow_portal_tags()
    assert "product=robo-engineer" in tags
    assert robo_client_tag() in tags
    assert len(tags) == 2










# ── Ambient conversation context (ContextVar) ────────────────────────────────






def test_ambient_context_set_none_clears():
    """set_conversation_context(None) publishes no tag (and coerces '')."""
    from agent.portal_tags import (
        get_conversation_context,
        igniteenow_portal_tags,
        reset_conversation_context,
        set_conversation_context,
    )

    for empty in (None, ""):
        token = set_conversation_context(empty)
        try:
            assert get_conversation_context() is None
            assert len(igniteenow_portal_tags()) == 2
        finally:
            reset_conversation_context(token)


def test_ambient_context_isolated_between_contexts():
    """Two copied Contexts (≈ two concurrent agents) don't leak into each other."""
    import contextvars

    from agent.portal_tags import (
        conversation_tag,
        igniteenow_portal_tags,
        set_conversation_context,
    )

    def _in_conversation(cid):
        set_conversation_context(cid)
        return igniteenow_portal_tags()

    tags_a = contextvars.copy_context().run(_in_conversation, "agent-a")
    tags_b = contextvars.copy_context().run(_in_conversation, "agent-b")
    assert conversation_tag("agent-a") in tags_a
    assert conversation_tag("agent-b") in tags_b
    assert conversation_tag("agent-b") not in tags_a
    # The outer (test) context stays clean.
    assert not any(t.startswith("conversation=") for t in igniteenow_portal_tags())


def test_ambient_context_propagates_via_thread_context_helper():
    """propagate_context_to_thread carries the tag onto executor workers (MoA path)."""
    from concurrent.futures import ThreadPoolExecutor

    from agent.portal_tags import (
        conversation_tag,
        igniteenow_portal_tags,
        reset_conversation_context,
        set_conversation_context,
    )
    from tools.thread_context import propagate_context_to_thread

    token = set_conversation_context("moa-root")
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            plain = ex.submit(igniteenow_portal_tags).result()
            propagated = ex.submit(
                propagate_context_to_thread(igniteenow_portal_tags)
            ).result()
    finally:
        reset_conversation_context(token)

    # Bare submit loses the ContextVar; the propagation wrapper keeps it.
    assert not any(t.startswith("conversation=") for t in plain)
    assert conversation_tag("moa-root") in propagated










def test_compress_context_preserves_ambient_context(monkeypatch):
    """In-turn compaction inherits the turn's root and restores it untouched."""
    import agent.conversation_compression as cc
    from agent.portal_tags import (
        get_conversation_context,
        reset_conversation_context,
        set_conversation_context,
    )
    from run_agent import AIAgent

    seen = {}

    def _fake_compress(agent, messages, system_message, **kwargs):
        seen["conversation"] = get_conversation_context()
        return ([], "")

    monkeypatch.setattr(cc, "compress_context", _fake_compress)

    class _Agent:
        def _conversation_root_id(self):
            # A rotated segment id must never win over the ambient root.
            return "segment-after-compaction"

    token = set_conversation_context("outer-root")
    try:
        AIAgent._compress_context(_Agent(), [], "sys")
        assert seen["conversation"] == "outer-root"
        assert get_conversation_context() == "outer-root"
    finally:
        reset_conversation_context(token)
