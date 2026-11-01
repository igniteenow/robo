"""Evidence-claims gate (agent/judgment.py) — detector, turn evidence, nudge,
and the conversation-loop wiring.

The suite-wide conftest pins ``ROBO_EVIDENCE_CLAIMS=0``; the loop tests here
opt back in.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.judgment import (
    build_evidence_claim_nudge,
    find_completion_claim,
    is_runner_command,
    turn_evidence,
    turn_start_index,
)


# ---------------------------------------------------------------------------
# Claim detector
# ---------------------------------------------------------------------------

CLAIMS = [
    "All tests pass.",
    "The test suite is green and the lint is clean.",
    "I ran the tests and they pass.",
    "Both test suites are passing now.",
    "Tests pass locally.",
    "12 passed in 3.2s.",
    "I've verified that the fix works.",
    "Build succeeds and typecheck passes.",
    "Done — the existing tests still pass.",
    "I re-ran the full suite: 240 passed.",
    "Everything is wired up and the linter is clean.",
]

NOT_CLAIMS = [
    "The tests should pass once you install the dependency.",
    "Please run the tests to confirm.",
    "I need to make the tests pass before merging.",
    "Tests pass except for two failures in auth.",
    "12 passed, 3 failed.",
    "I haven't run the tests yet.",
    "Earlier the tests passed; nothing changed since.",
    "Let me run the test suite now.",
    "You can run `npm test` to check.",
    "The tests didn't pass.",
    "I'll run the tests next.",
    "Here is the summary of the changes.",
    "The build is likely fine but I could not verify it.",
    "We want all tests green before release.",
    "Make sure the tests pass.",
    "Expected: tests pass after the dependency bump.",
    "```\n12 passed\n```",
    "I printed the count and the event fired.",
    "Wait for the tests to pass in CI.",
    "",
]


@pytest.mark.parametrize("text", CLAIMS)
def test_detects_completion_claims(text):
    assert find_completion_claim(text) is not None, text


@pytest.mark.parametrize("text", NOT_CLAIMS)
def test_ignores_hedges_failures_instructions_and_quotes(text):
    assert find_completion_claim(text) is None, text


def test_returns_the_claiming_sentence_only():
    text = "I changed the parser.\nAll tests pass.\nLet me know if you want more."
    assert find_completion_claim(text) == "All tests pass."


# ---------------------------------------------------------------------------
# Runner commands
# ---------------------------------------------------------------------------

RUNNERS = [
    "pytest tests/x.py -q",
    "cd ui-tui && npm run check",
    "npm test",
    "uv run pytest -k foo",
    "scripts/run_tests.sh tests/agent/test_x.py",
    "cargo test",
    "go test ./...",
    "npx vitest run src/a.test.ts",
    "ruff check .",
    "make test",
    "python -m pytest tests",
    "FOO=1 pytest",
    "tsc --noEmit",
    "./gradlew test",
    "dotnet test",
    "uvx ruff@0.15.10 check .",
    'cd /x && FOO=bar BAR="a b" timeout 600 npm run build',
    "sudo -E make check",
    "pytest tests 2>&1 | tail -20",
]

NOT_RUNNERS = [
    "ls -la",
    "git status",
    "cat tests/test_x.py",
    "grep -rn pytest .",
    "echo tests pass",
    "python main.py",
    "npm install",
    "pip install pytest",
    "npm run dev",
    "sed -n 1,20p build.log",
    "rm -rf build",
    "echo 'npm test'",
    "ls scripts/run_tests.sh",
    "",
]


@pytest.mark.parametrize("command", RUNNERS)
def test_runner_commands(command):
    assert is_runner_command(command), command


@pytest.mark.parametrize("command", NOT_RUNNERS)
def test_non_runner_commands(command):
    assert not is_runner_command(command), command


# ---------------------------------------------------------------------------
# Turn evidence + nudge
# ---------------------------------------------------------------------------


def _call(call_id, name, **args):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _tool(call_id, payload):
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(payload)}


def _turn(*tail, user="run the tests"):
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "older request"},
        {"role": "assistant", "content": "older answer"},
        {"role": "user", "content": user},
        *tail,
    ]


def test_turn_start_index_skips_synthetic_user_nudges():
    messages = _turn(
        {"role": "assistant", "content": "All tests pass."},
        {"role": "user", "content": "[System: verify]", "_verification_stop_synthetic": True},
    )
    assert turn_start_index(messages) == 3


def test_passing_runner_is_evidence():
    messages = _turn(
        {"role": "assistant", "content": "Running the tests.", "tool_calls": [_call("c1", "terminal", command="pytest -q")]},
        _tool("c1", {"output": "12 passed", "exit_code": 0, "error": None}),
    )
    evidence = turn_evidence(messages)
    assert evidence["tool_calls"] == 1
    assert evidence["runner_passed"] == 1
    assert build_evidence_claim_nudge("All tests pass.", messages) is None


def test_ledger_record_is_evidence_even_for_an_unknown_command():
    messages = _turn(
        {"role": "assistant", "content": "", "tool_calls": [_call("c1", "terminal", command="./verify.sh")]},
        _tool("c1", {"output": "ok", "exit_code": 0, "error": None, "verification_evidence": {"status": "passed"}}),
    )
    assert turn_evidence(messages)["ledger_passed"] is True
    assert build_evidence_claim_nudge("Everything is verified and the tests pass.", messages) is None


def test_failed_runner_with_pass_claim_nudges_and_names_the_command():
    messages = _turn(
        {"role": "assistant", "content": "", "tool_calls": [_call("c1", "terminal", command="npm test")]},
        _tool("c1", {"output": "2 failing", "exit_code": 1, "error": None}),
    )
    nudge = build_evidence_claim_nudge("All tests pass now.", messages)
    assert nudge is not None
    assert "`npm test`" in nudge
    assert "did not exit successfully" in nudge
    assert "All tests pass now." in nudge


def test_no_runner_with_pass_claim_nudges():
    messages = _turn(
        {"role": "assistant", "content": "", "tool_calls": [_call("c1", "read_file", path="a.py")]},
        _tool("c1", {"content": "x = 1"}),
    )
    nudge = build_evidence_claim_nudge("I ran the tests and they pass.", messages)
    assert nudge is not None
    assert "no test, lint, type-check or build command ran" in nudge


def test_background_launch_is_not_evidence():
    messages = _turn(
        {"role": "assistant", "content": "", "tool_calls": [_call("c1", "terminal", command="pytest", background=True)]},
        _tool("c1", {"output": "Background process started", "pid": 4242, "exit_code": 0, "error": None}),
    )
    assert turn_evidence(messages)["runner_passed"] == 0
    assert build_evidence_claim_nudge("Tests pass.", messages) is not None


def test_plain_conversational_turn_is_never_nudged():
    messages = _turn(user="did the tests pass earlier?")
    assert build_evidence_claim_nudge("Yes — all tests pass.", messages) is None


def test_no_claim_no_nudge():
    messages = _turn(
        {"role": "assistant", "content": "", "tool_calls": [_call("c1", "read_file", path="a.py")]},
        _tool("c1", {"content": "x = 1"}),
    )
    assert build_evidence_claim_nudge("I read the file; the parser lives in a.py.", messages) is None


def test_evidence_only_counts_this_turn():
    messages = [
        {"role": "user", "content": "run tests"},
        {"role": "assistant", "content": "", "tool_calls": [_call("c0", "terminal", command="pytest")]},
        _tool("c0", {"output": "12 passed", "exit_code": 0, "error": None}),
        {"role": "assistant", "content": "12 passed."},
        {"role": "user", "content": "now refactor the parser"},
        {"role": "assistant", "content": "", "tool_calls": [_call("c1", "patch", path="p.py")]},
        _tool("c1", {"success": True}),
    ]
    assert build_evidence_claim_nudge("Refactored; all tests still pass.", messages) is not None


def test_malformed_tool_payloads_are_ignored():
    messages = _turn(
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "terminal", "arguments": "{not json"}}, "nonsense"]},
        {"role": "tool", "tool_call_id": "c1", "content": "plain text, not json"},
        {"role": "tool", "tool_call_id": "zzz", "content": [{"type": "text", "text": "{}"}]},
    )
    evidence = turn_evidence(messages)
    assert evidence["tool_calls"] == 1
    assert evidence["runner_passed"] == 0


# ---------------------------------------------------------------------------
# Conversation-loop wiring
# ---------------------------------------------------------------------------


def _response(content, finish_reason="stop"):
    message = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        model="test/model",
        usage=None,
    )


@pytest.fixture
def agent(tmp_path, monkeypatch):
    from run_agent import AIAgent

    monkeypatch.setenv("ROBO_HOME", str(tmp_path / ".robo"))
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        instance = AIAgent(
            session_id="judgment-test",
            api_key="test-key",
            base_url="https://example.invalid/v1",
            provider="openai-compat",
            model="test/model",
            max_iterations=3,
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
    instance._cached_system_prompt = "stable test prompt"
    instance._session_db = None
    instance._session_json_enabled = False
    instance.save_trajectories = False
    instance.compression_enabled = False
    instance._cleanup_task_resources = lambda *_a, **_kw: None
    instance._save_trajectory = lambda *_a, **_kw: None
    return instance


def _run(agent, answers, monkeypatch, *, nudge="[System: show the evidence]", enabled="1"):
    monkeypatch.setenv("ROBO_EVIDENCE_CLAIMS", enabled)
    monkeypatch.setenv("ROBO_VERIFY_ON_STOP", "1")
    calls = iter(answers)
    seen_prompts: list[list[dict]] = []

    def model_call(api_kwargs):
        seen_prompts.append([dict(m) for m in api_kwargs.get("messages", [])])
        return _response(next(calls))

    agent._interruptible_api_call = model_call
    agent._handle_max_iterations = MagicMock(return_value="budget summary")
    with (
        patch("agent.verification_stop.build_verify_on_stop_nudge", return_value=None),
        patch("agent.judgment.build_evidence_claim_nudge", return_value=nudge) as gate,
        patch("robo_cli.plugins.invoke_hook", return_value=[]),
    ):
        result = agent.run_conversation("run the tests and report")
    return result, gate, seen_prompts


def test_loop_asks_once_then_accepts_the_revised_answer(agent, monkeypatch):
    result, gate, prompts = _run(agent, ["All tests pass.", "I ran pytest: 12 passed, 0 failed."], monkeypatch)

    assert result["final_response"] == "I ran pytest: 12 passed, 0 failed."
    assert result["completed"] is True
    # Checked on the first answer only — one follow-up per turn.
    assert gate.call_count == 1
    # The second model call saw the nudge as the latest user message.
    assert prompts[1][-1]["role"] == "user"
    assert prompts[1][-1]["content"] == "[System: show the evidence]"
    # The nudge is scaffolding and is stripped from the returned history; the
    # attempted answer is real content and stays.
    roles = [m["role"] for m in result["messages"]]
    assert roles == ["user", "assistant", "assistant"]
    assert result["messages"][1]["content"] == "All tests pass."
    assert not any(m.get("_verification_stop_synthetic") for m in result["messages"])


def test_loop_counts_toward_the_shared_verification_budget(agent, monkeypatch):
    _run(agent, ["All tests pass.", "I ran pytest: 12 passed."], monkeypatch)
    assert agent._evidence_claim_nudges == 1
    assert agent._verification_stop_nudges == 1


def test_loop_skips_when_disabled(agent, monkeypatch):
    result, gate, _ = _run(agent, ["All tests pass."], monkeypatch, enabled="0")
    assert result["final_response"] == "All tests pass."
    assert gate.call_count == 0


def test_loop_skips_on_messaging_surfaces(agent, monkeypatch):
    monkeypatch.setenv("ROBO_EVIDENCE_CLAIMS", "1")
    monkeypatch.setenv("ROBO_VERIFY_ON_STOP", "1")
    agent._interruptible_api_call = lambda _kwargs: _response("All tests pass.")
    agent._handle_max_iterations = MagicMock(return_value="budget summary")
    with (
        patch("agent.verification_stop.build_verify_on_stop_nudge", return_value=None),
        patch("agent.judgment.on_messaging_surface", return_value=True),
        patch("agent.judgment.build_evidence_claim_nudge", return_value="[System: nudge]") as gate,
        patch("robo_cli.plugins.invoke_hook", return_value=[]),
    ):
        result = agent.run_conversation("run the tests")
    assert result["final_response"] == "All tests pass."
    assert gate.call_count == 0


def test_loop_runs_even_when_verify_on_stop_is_switched_off(agent, monkeypatch):
    # Many installs have agent.verify_on_stop: false (its migration turned it
    # off). This gate is far narrower and keeps working there.
    monkeypatch.setenv("ROBO_EVIDENCE_CLAIMS", "1")
    monkeypatch.setenv("ROBO_VERIFY_ON_STOP", "0")
    answers = iter(["All tests pass.", "I ran pytest: 12 passed."])
    agent._interruptible_api_call = lambda _kwargs: _response(next(answers))
    agent._handle_max_iterations = MagicMock(return_value="budget summary")
    with (
        patch("agent.judgment.on_messaging_surface", return_value=False),
        patch("agent.judgment.build_evidence_claim_nudge", return_value="[System: nudge]") as gate,
        patch("robo_cli.plugins.invoke_hook", return_value=[]),
    ):
        result = agent.run_conversation("run the tests")
    assert result["final_response"] == "I ran pytest: 12 passed."
    assert gate.call_count == 1


def test_messaging_surface_detection_fails_closed_to_local():
    from agent.judgment import on_messaging_surface

    with patch("gateway.session_context.session_is_messaging_surface", side_effect=RuntimeError("x")):
        assert on_messaging_surface() is False


def test_loop_fails_open_when_the_gate_raises(agent, monkeypatch):
    monkeypatch.setenv("ROBO_EVIDENCE_CLAIMS", "1")
    monkeypatch.setenv("ROBO_VERIFY_ON_STOP", "1")
    agent._interruptible_api_call = lambda _kwargs: _response("All tests pass.")
    agent._handle_max_iterations = MagicMock(return_value="budget summary")
    with (
        patch("agent.verification_stop.build_verify_on_stop_nudge", return_value=None),
        patch("agent.judgment.build_evidence_claim_nudge", side_effect=RuntimeError("boom")),
        patch("robo_cli.plugins.invoke_hook", return_value=[]),
    ):
        result = agent.run_conversation("run the tests")
    assert result["final_response"] == "All tests pass."
    assert result["completed"] is True
