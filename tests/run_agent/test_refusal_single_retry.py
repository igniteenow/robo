"""An explanation-less refusal is re-issued once before it is surfaced.

Seen in the field: the first message of a session ("Hey!") came back from a
messages-API endpoint with ``stop_reason="refusal"`` and no text at all, and
the identical message answered normally a moment later. A refusal that says
nothing is usually an automated provider-side filter rather than the
model's own answer, so the turn loop gives it exactly one more attempt. A
refusal that carries the model's explanation, or one that a configured
fallback can take over, is handled exactly as before.
"""

import sys
import types
from types import SimpleNamespace

sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda *a, **k: None))
sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))
sys.modules.setdefault("fal_client", types.SimpleNamespace())

import run_agent


class _FakeAnthropicClient:
    def close(self):
        pass


def _make_agent(monkeypatch, responses):
    """An Anthropic-messages agent whose API calls return ``responses`` in order."""
    monkeypatch.setattr(run_agent, "get_tool_definitions", lambda **kwargs: [{
        "type": "function",
        "function": {"name": "t", "description": "t", "parameters": {"type": "object", "properties": {}}},
    }])
    monkeypatch.setattr(run_agent, "check_toolset_requirements", lambda: {})
    monkeypatch.setattr(
        "agent.anthropic_adapter.build_anthropic_client",
        lambda k, b=None, **kwargs: _FakeAnthropicClient(),
    )
    queue = list(responses)
    calls = []

    def _next_response(_kwargs):
        calls.append(_kwargs)
        if not queue:
            raise AssertionError("the request was issued more often than expected")
        return queue.pop(0)

    class _A(run_agent.AIAgent):
        def __init__(self, *a, **kw):
            kw.update(skip_context_files=True, skip_memory=True, max_iterations=4)
            super().__init__(*a, **kw)
            self._cleanup_task_resources = self._persist_session = lambda *a, **k: None
            self._save_trajectory = lambda *a, **k: None
            self.statuses = []
            self._emit_status = self.statuses.append

        def run_conversation(self, msg, conversation_history=None, task_id=None):
            self._interruptible_api_call = _next_response
            self._disable_streaming = True
            return super().run_conversation(msg, conversation_history=conversation_history, task_id=task_id)

    agent = _A(
        model="deepseek-v4-pro",
        api_key="test-key",
        base_url="http://localhost:1234/v1",
        provider="anthropic",
        api_mode="anthropic_messages",
    )
    return agent, calls


def _usage():
    return SimpleNamespace(input_tokens=10, output_tokens=2)


def _refusal(text=None):
    content = [SimpleNamespace(type="text", text=text)] if text else []
    return SimpleNamespace(content=content, stop_reason="refusal", usage=_usage(), model="deepseek-v4-pro")


def _answer(text):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=_usage(),
        model="deepseek-v4-pro",
    )


def test_unexplained_messages_api_refusal_is_retried_once_and_recovers(monkeypatch):
    agent, calls = _make_agent(monkeypatch, [_refusal(), _answer("Hey! How can I help you today?")])

    result = agent.run_conversation("Hey!")

    assert len(calls) == 2
    assert result["completed"] is True
    assert result["final_response"] == "Hey! How can I help you today?"
    # A retry that succeeds is silent, and the refused attempt leaves nothing
    # behind in the transcript.
    assert not any("declined" in s for s in agent.statuses)
    assert [m["role"] for m in result["messages"]] == ["user", "assistant"]


def test_unexplained_messages_api_refusal_is_surfaced_after_one_retry(monkeypatch):
    agent, calls = _make_agent(monkeypatch, [_refusal(), _refusal()])

    result = agent.run_conversation("Hey!")

    assert len(calls) == 2
    assert result["completed"] is False
    assert result["failed"] is True
    assert "content_policy_blocked" in result["error"]
    assert "The model returned no explanation." in result["final_response"]
    # The user is told a second attempt was made.
    assert any("tried once more" in s for s in agent.statuses)


def test_explained_refusal_is_never_retried(monkeypatch):
    agent, calls = _make_agent(monkeypatch, [_refusal("I can't help with that request.")])

    result = agent.run_conversation("do something disallowed")

    assert len(calls) == 1
    assert result["failed"] is True
    assert "I can't help with that request." in result["final_response"]


def test_configured_fallback_still_goes_first(monkeypatch):
    """With a fallback pending, the refusal goes to the fallback chain as
    before instead of being re-sent to the model that refused."""
    agent, calls = _make_agent(monkeypatch, [_refusal()])
    monkeypatch.setattr(agent, "_has_pending_fallback", lambda: True)
    activations = []
    monkeypatch.setattr(agent, "_try_activate_fallback", lambda *a, **k: activations.append(1) and False)

    result = agent.run_conversation("Hey!")

    assert len(calls) == 1
    assert activations == [1]
    assert result["failed"] is True
