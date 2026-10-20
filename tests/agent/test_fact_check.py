"""Fact check (agent/fact_check.py): Robo checks the model's answer against
sources with its own research and proposes a correction when they disagree.

Covers the pure pieces (settings, skip rules, claim extraction, the research
loop over fake tools, the apply/keep decision), the approval-plumbing guards
(a correction's "session" never becomes a command bypass; a declined
correction never halts the turn), the gateway wording, and the real
conversation loop end to end with a patched model.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent import fact_check as fc
from agent.fact_check import (
    Claim,
    FactCheckResult,
    FactCheckSettings,
    Verdict,
    build_approval_payload,
    build_correction_nudge,
    build_keep_note,
    decide_apply,
    extract_claims,
    parse_json_object,
    research_claims,
    run_fact_check,
    should_skip,
    status_line,
)


@pytest.fixture(autouse=True)
def _fresh_session_state():
    fc._session_auto_apply.clear()
    yield
    fc._session_auto_apply.clear()


def _settings(**kw) -> FactCheckSettings:
    return FactCheckSettings(**kw)


def _claim(n=1, text="Python 3.12 was released in 2022", check="web"):
    return Claim(index=n, text=text, check=check)


def _contradicted(claim=None, finding="Python 3.12.0 was released on 2 October 2023.",
                  source="https://www.python.org/downloads/release/python-3120/"):
    claim = claim or _claim()
    return Verdict(claim=claim, verdict="contradicted", finding=finding, source=source)


def _result(*verdicts, sources=1) -> FactCheckResult:
    r = FactCheckResult(claims=[v.claim for v in verdicts], verdicts=list(verdicts))
    r.sources = sources
    return r


# ── Settings and enablement ───────────────────────────────────────────────


class TestSettings:
    def test_env_override_wins_over_config(self, monkeypatch):
        monkeypatch.setenv("ROBO_FACT_CHECK", "0")
        assert fc.fact_check_enabled({"fact_check": {"enabled": True}}) is False
        monkeypatch.setenv("ROBO_FACT_CHECK", "1")
        assert fc.fact_check_enabled({"fact_check": {"enabled": False}}) is True

    def test_config_default_is_on(self, monkeypatch):
        monkeypatch.delenv("ROBO_FACT_CHECK", raising=False)
        assert fc.fact_check_enabled({}) is True
        assert fc.fact_check_enabled({"fact_check": {"enabled": False}}) is False

    def test_defaults_match_default_config(self):
        from robo_cli.config_defaults import DEFAULT_CONFIG

        section = DEFAULT_CONFIG["fact_check"]
        s = FactCheckSettings.load({"fact_check": section})
        assert s.apply == section["apply"]
        assert s.max_claims == section["max_claims"]
        assert s.max_steps == section["max_steps"]
        assert s.timeout_seconds == float(section["timeout_seconds"])
        assert s.min_answer_words == section["min_answer_words"]
        assert "fact_check" in DEFAULT_CONFIG["auxiliary"]

    def test_ceilings_and_bad_values(self):
        s = FactCheckSettings.load({"fact_check": {
            "apply": "whatever", "max_claims": 999, "max_steps": "x",
            "timeout_seconds": 1e9, "min_answer_words": -5,
        }})
        assert s.apply == "ask"
        assert s.max_claims == fc._MAX_CLAIMS_CEILING
        assert s.max_steps == 8
        assert s.timeout_seconds == fc._MAX_TIMEOUT_CEILING
        assert s.min_answer_words == 1


class TestSkipRules:
    def test_runs_for_a_normal_answer(self):
        agent = SimpleNamespace()
        assert should_skip(agent, "word " * 20, _settings()) == ""

    def test_once_per_turn(self):
        agent = SimpleNamespace(_fact_check_done=True)
        assert should_skip(agent, "word " * 20, _settings())

    def test_a_session_that_opted_out_is_never_checked(self):
        # The gateway sets this for a desktop Team seat (the team verifies its
        # own answers); the flag outlives the per-turn `_fact_check_done` reset.
        agent = SimpleNamespace(_fact_check_disabled=True, _fact_check_done=False)
        assert should_skip(agent, "word " * 20, _settings()) == "disabled for this session"
        assert run_fact_check(agent, "word " * 20, [{"role": "user", "content": "q"}]) is None
        assert getattr(agent, "_fact_check_done", False) is False

    def test_internal_agents_are_never_checked(self):
        # The self-improvement review fork and the curator: their summary is
        # never shown, and a correction prompt for it would land in the real chat.
        assert should_skip(SimpleNamespace(_memory_write_origin="background_review"), "word " * 20, _settings()) == "internal agent"
        assert should_skip(SimpleNamespace(_persist_disabled=True), "word " * 20, _settings()) == "internal agent"
        assert should_skip(SimpleNamespace(suppress_status_output=True), "word " * 20, _settings()) == "internal agent"

    def test_unattended_surfaces_are_never_checked(self, monkeypatch):
        # A program on the API or a webhook cannot answer a correction prompt;
        # a batch run has no reader; a cron job has a time budget of its own.
        for platform in ("api_server", "webhook", "msgraph_webhook", "batch", "cron", "API_SERVER"):
            assert should_skip(SimpleNamespace(platform=platform), "word " * 20, _settings()).startswith(
                ("unattended", "cron")
            ), platform
        # Interactive surfaces are checked.
        for platform in ("cli", "tui", "desktop", "telegram", "discord", "slack", ""):
            assert should_skip(SimpleNamespace(platform=platform), "word " * 20, _settings()) == "", platform
        # A cron turn delivered through a chat platform carries that platform
        # on the agent; the cron context still wins.
        monkeypatch.setenv("ROBO_CRON_SESSION", "1")
        assert should_skip(SimpleNamespace(platform="telegram"), "word " * 20, _settings()) == "cron"

    def test_a_quiet_agent_with_no_status_channel_is_a_detached_task(self):
        assert should_skip(SimpleNamespace(quiet_mode=True, status_callback=None), "word " * 20, _settings()) == (
            "no surface to report on"
        )
        # Quiet but with a status channel (the desktop / TUI gateway) is checked;
        # so is a loud CLI agent with no channel.
        assert should_skip(SimpleNamespace(quiet_mode=True, status_callback=lambda k, t=None: None), "word " * 20, _settings()) == ""
        assert should_skip(SimpleNamespace(quiet_mode=False, status_callback=None), "word " * 20, _settings()) == ""

    def test_subagents_and_short_answers_skip(self):
        assert should_skip(SimpleNamespace(_delegate_depth=1), "word " * 20, _settings())
        assert should_skip(SimpleNamespace(), "short answer", _settings(min_answer_words=12))
        assert should_skip(SimpleNamespace(), "", _settings())


# ── Claim extraction ──────────────────────────────────────────────────────


class TestExtractClaims:
    def test_parses_fenced_json_and_caps(self):
        payload = {"claims": [
            {"text": "A", "check": "web"},
            {"text": "B", "check": "code"},
            {"text": "C", "check": "nonsense"},
        ]}
        aux = MagicMock(return_value="```json\n" + json.dumps(payload) + "\n```")
        claims = extract_claims("q", "a " * 20, _settings(max_claims=2), aux=aux)
        assert [(c.index, c.text, c.check) for c in claims] == [(1, "A", "web"), (2, "B", "code")]
        # Untrusted framing and the budget reach the model.
        sent = aux.call_args[0][0]
        assert "UNTRUSTED" in sent[0]["content"]
        assert "at most 2" in sent[1]["content"]

    def test_unknown_check_defaults_to_web_and_blanks_dropped(self):
        aux = MagicMock(return_value=json.dumps({"claims": [{"text": "", "check": "web"}, {"text": "X", "check": "??"}]}))
        claims = extract_claims("q", "a", _settings(), aux=aux)
        assert len(claims) == 1 and claims[0].check == "web"

    def test_garbage_or_failure_means_nothing_to_check(self):
        assert extract_claims("q", "a", _settings(), aux=MagicMock(return_value="no json here")) == []
        assert extract_claims("q", "a", _settings(), aux=MagicMock(side_effect=RuntimeError("down"))) == []

    def test_parse_json_object_tolerates_prose(self):
        assert parse_json_object('Sure: {"action": "done", "verdicts": []} — ok') == {"action": "done", "verdicts": []}
        assert parse_json_object("[1, 2]") is None
        assert parse_json_object("") is None


# ── Research loop ─────────────────────────────────────────────────────────


class _FakeTools:
    """A scripted auxiliary model plus a recording tool dispatcher."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []
        self.convos = []

    def aux(self, messages, **_kw):
        self.convos.append([dict(m) for m in messages])
        if not self.turns:
            raise RuntimeError("script exhausted")
        turn = self.turns.pop(0)
        return turn if isinstance(turn, str) else json.dumps(turn)

    def dispatch(self, name, args, task_id):
        self.calls.append((name, args, task_id))
        if name == "web_search":
            return json.dumps({"results": [{"url": "https://www.python.org/downloads/release/python-3120/", "snippet": "Release Date: Oct. 2, 2023"}]})
        if name == "read_file":
            return "PORT = 8080\n"
        return "ok"


ALL_TOOLS = {n: object() for n in ("web_search", "web_extract", "search_files", "read_file")}


class TestResearchClaims:
    def test_search_then_verdict(self):
        fake = _FakeTools([
            {"action": "web_search", "query": "python 3.12 release date"},
            {"action": "done", "verdicts": [{"claim": 1, "verdict": "contradicted",
                                             "finding": "Released 2 October 2023.",
                                             "source": "https://www.python.org/downloads/release/python-3120/"}]},
        ])
        result = research_claims([_claim()], "when was 3.12 released", _settings(),
                                 tools=ALL_TOOLS, task_id="t1", aux=fake.aux, dispatch=fake.dispatch)
        assert fake.calls == [("web_search", {"query": "python 3.12 release date", "limit": 5}, "t1")]
        assert result.steps == 1
        assert result.sources == 1
        assert [v.verdict for v in result.verdicts] == ["contradicted"]
        assert result.contradicted[0].finding == "Released 2 October 2023."
        # The tool result went back wrapped as untrusted evidence.
        last_user = fake.convos[-1][-1]
        assert last_user["role"] == "user" and last_user["content"].startswith('<result action="web_search">')

    def test_code_claims_use_file_tools_only(self):
        fake = _FakeTools([
            {"action": "read_file", "path": "settings.py"},
            {"action": "done", "verdicts": [{"claim": 1, "verdict": "confirmed", "finding": "PORT = 8080", "source": "settings.py"}]},
        ])
        result = research_claims([_claim(text="settings.py sets PORT to 8080", check="code")], "q",
                                 _settings(), tools=ALL_TOOLS, cwd="/proj", aux=fake.aux, dispatch=fake.dispatch)
        system = fake.convos[0][0]["content"]
        assert "read_file" in system and "search_files" in system
        assert "web_search" not in system
        assert "/proj" in system
        assert fake.calls[0][0] == "read_file" and fake.calls[0][1] == {"path": "settings.py", "limit": 400}
        assert result.confirmed and result.sources == 1

    def test_web_tool_not_offered_when_unavailable(self):
        fake = _FakeTools([{"action": "web_search", "query": "x"}, {"action": "done", "verdicts": []}])
        result = research_claims([_claim()], "q", _settings(), tools={"read_file": object()},
                                 aux=fake.aux, dispatch=fake.dispatch)
        # No tool can settle a web claim → nothing dispatched, everything unverified.
        assert fake.calls == []
        assert result.skipped_reason == "no research tools"
        assert [v.verdict for v in result.verdicts] == ["unverified"]

    def test_research_tools_limited_to_the_agents_own(self):
        from agent.fact_check import available_research_tools

        with patch("tools.registry.registry.get_entry", side_effect=lambda n: SimpleNamespace(check_fn=None)):
            assert set(available_research_tools(["read_file", "terminal"])) == {"read_file"}
            assert available_research_tools([]) == {}
            assert set(available_research_tools(None)) == set(fc._RESEARCH_TOOLS)

    def test_unavailable_tool_is_dropped(self):
        from agent.fact_check import available_research_tools

        def entry(name):
            return SimpleNamespace(check_fn=(lambda: False) if name == "web_search" else None)

        with patch("tools.registry.registry.get_entry", side_effect=entry):
            assert "web_search" not in available_research_tools(None)
            assert "read_file" in available_research_tools(None)

    def test_malformed_action_is_bounced_not_dispatched(self):
        fake = _FakeTools([
            {"action": "web_extract", "urls": ["ftp://nope"]},
            {"action": "teleport"},
            {"action": "done", "verdicts": []},
        ])
        result = research_claims([_claim()], "q", _settings(), tools=ALL_TOOLS, aux=fake.aux, dispatch=fake.dispatch)
        assert fake.calls == [] and result.steps == 0
        bounced = [m["content"] for m in fake.convos[-1] if m["role"] == "user" and "malformed" in m["content"]]
        assert len(bounced) == 2

    def test_max_steps_stops_the_loop(self):
        fake = _FakeTools([{"action": "web_search", "query": f"q{i}"} for i in range(10)])
        result = research_claims([_claim()], "q", _settings(max_steps=3), tools=ALL_TOOLS,
                                 aux=fake.aux, dispatch=fake.dispatch)
        assert result.steps == 3
        assert [v.verdict for v in result.verdicts] == ["unverified"]

    def test_deadline_and_interrupt_stop_the_loop(self):
        fake = _FakeTools([{"action": "web_search", "query": "q"}] * 5)
        result = research_claims([_claim()], "q", _settings(), tools=ALL_TOOLS, aux=fake.aux,
                                 dispatch=fake.dispatch, deadline=time.monotonic() - 1)
        assert result.steps == 0
        fake = _FakeTools([{"action": "web_search", "query": "q"}] * 5)
        result = research_claims([_claim()], "q", _settings(), tools=ALL_TOOLS, aux=fake.aux,
                                 dispatch=fake.dispatch, is_interrupted=lambda: True)
        assert result.steps == 0 and result.verdicts[0].verdict == "unverified"

    def test_contradicted_without_finding_is_unverified(self):
        fake = _FakeTools([{"action": "done", "verdicts": [
            {"claim": 1, "verdict": "contradicted", "finding": ""},
            {"claim": 7, "verdict": "confirmed"},
            {"claim": "x", "verdict": "confirmed"},
        ]}])
        result = research_claims([_claim()], "q", _settings(), tools=ALL_TOOLS, aux=fake.aux, dispatch=fake.dispatch)
        assert [v.verdict for v in result.verdicts] == ["unverified"]
        assert result.contradicted == []

    def test_aux_failure_fails_open(self):
        fake = _FakeTools([])
        result = research_claims([_claim()], "q", _settings(), tools=ALL_TOOLS, aux=fake.aux, dispatch=fake.dispatch)
        assert [v.verdict for v in result.verdicts] == ["unverified"]

    def test_non_json_reply_gets_one_nudge_then_gives_up(self):
        fake = _FakeTools(["I think it's fine", "still prose", "more prose"])
        result = research_claims([_claim()], "q", _settings(), tools=ALL_TOOLS, aux=fake.aux, dispatch=fake.dispatch)
        assert result.verdicts[0].verdict == "unverified"
        assert len(fake.convos) <= 3


# ── Decision ──────────────────────────────────────────────────────────────


class TestDecideApply:
    def test_nothing_contradicted_keeps(self):
        confirmed = Verdict(claim=_claim(), verdict="confirmed", finding="yes", source="s")
        ask = MagicMock()
        assert decide_apply(_result(confirmed), _settings(), session_key="k", ask=ask) == "keep"
        ask.assert_not_called()

    def test_auto_applies_without_asking(self):
        ask = MagicMock()
        assert decide_apply(_result(_contradicted()), _settings(apply="auto"), session_key="k", ask=ask) == "apply"
        ask.assert_not_called()

    def test_nobody_to_ask_keeps(self):
        assert decide_apply(_result(_contradicted()), _settings(), session_key="k", ask=None) == "keep"

    @pytest.mark.parametrize("choice,expected", [("once", "apply"), ("deny", "keep"), ("timeout", "keep"), ("", "keep")])
    def test_choice_maps(self, choice, expected):
        ask = MagicMock(return_value=choice)
        assert decide_apply(_result(_contradicted()), _settings(), session_key="k", ask=ask) == expected
        payload = ask.call_args[0][0]
        assert payload["kind"] == "correction"
        assert payload["halt_on_deny"] is False
        assert payload["choices"] == ["once", "session", "deny"]
        assert payload["allow_permanent"] is False
        assert "Python 3.12 was released in 2022" in payload["command"]
        assert "2 October 2023" in payload["command"]
        assert "1 statement" in payload["description"]

    def test_session_allow_persists_for_that_session_only(self):
        ask = MagicMock(return_value="session")
        assert decide_apply(_result(_contradicted()), _settings(), session_key="k1", ask=ask) == "apply"
        ask2 = MagicMock()
        assert decide_apply(_result(_contradicted()), _settings(), session_key="k1", ask=ask2) == "apply"
        ask2.assert_not_called()
        ask3 = MagicMock(return_value="deny")
        assert decide_apply(_result(_contradicted()), _settings(), session_key="k2", ask=ask3) == "keep"
        ask3.assert_called_once()
        fc.clear_session("k1")
        assert fc.corrections_allowed_for_session("k1") is False

    def test_ask_raising_keeps(self):
        ask = MagicMock(side_effect=RuntimeError("surface gone"))
        assert decide_apply(_result(_contradicted()), _settings(), session_key="k", ask=ask) == "keep"


class TestWording:
    def test_nudge_lists_findings_and_asks_for_a_revision(self):
        text = build_correction_nudge(_result(_contradicted()))
        assert "[Fact check]" in text
        assert "You said: Python 3.12 was released in 2022" in text
        assert "Source says: Python 3.12.0 was released on 2 October 2023." in text
        assert "https://www.python.org/downloads/release/python-3120/" in text
        assert "correct those files too" in text

    def test_keep_note_and_status_line(self):
        r = _result(_contradicted(), sources=3)
        note = build_keep_note(r)
        assert note.startswith("🔎 Fact check — kept as written")
        assert "2 October 2023" in note and "python.org" in note
        assert status_line(r) == "🔎 Checked 1 statement against 3 sources: 1 contradicted"
        r2 = _result(Verdict(claim=_claim(), verdict="confirmed"), Verdict(claim=_claim(2, "B"), verdict="unverified"), sources=2)
        assert status_line(r2) == "🔎 Checked 2 statements against 2 sources: confirmed, 1 unsettled"
        r3 = _result(Verdict(claim=_claim()), sources=0)
        assert status_line(r3) == "🔎 Checked 1 statement: could not be settled"


# ── Approval plumbing guards ──────────────────────────────────────────────


class TestApprovalGuards:
    def test_session_on_a_correction_never_enables_command_bypass(self):
        from tools import approval as ap

        key = "fact-check-guard-session"
        ap.disable_session_yolo(key) if hasattr(ap, "disable_session_yolo") else None
        entry = ap._ApprovalEntry(build_approval_payload(_result(_contradicted())))
        with ap._lock:
            ap._gateway_queues[key] = [entry]
        try:
            assert ap.resolve_gateway_approval(key, "session") == 1
            assert entry.result == "session"
            assert ap.is_session_yolo_enabled(key) is False
        finally:
            ap.disable_session_yolo(key)

    def test_session_on_a_command_still_enables_bypass(self):
        from tools import approval as ap

        key = "fact-check-guard-command"
        entry = ap._ApprovalEntry({"command": "rm -rf build", "description": "d", "pattern_key": "rm"})
        with ap._lock:
            ap._gateway_queues[key] = [entry]
        try:
            assert ap.resolve_gateway_approval(key, "session") == 1
            assert ap.is_session_yolo_enabled(key) is True
        finally:
            ap.disable_session_yolo(key)

    def test_declined_correction_does_not_halt_the_turn(self, monkeypatch):
        from tools import approval as ap

        key = "fact-check-no-halt"
        halted = []
        seen = {}

        def notify(data):
            seen.update(data)
            threading.Timer(0.05, lambda: ap.resolve_gateway_approval(key, "deny")).start()

        ap.register_gateway_notify(key, notify, wait_forever=True, halt_on_deny=True,
                                   on_halt=lambda reason, data: halted.append(reason))
        monkeypatch.setattr(ap, "_fire_approval_hook", lambda *a, **k: None)
        try:
            outcome = ap._await_gateway_decision(key, notify, build_approval_payload(_result(_contradicted())), surface="fact_check")
        finally:
            ap.unregister_gateway_notify(key)
        assert outcome["resolved"] is True and outcome["choice"] == "deny"
        assert seen["kind"] == "correction"
        assert halted == []

    def test_declined_command_still_halts(self, monkeypatch):
        from tools import approval as ap

        key = "fact-check-halt-command"
        halted = []

        def notify(_data):
            threading.Timer(0.05, lambda: ap.resolve_gateway_approval(key, "deny")).start()

        ap.register_gateway_notify(key, notify, wait_forever=True, halt_on_deny=True,
                                   on_halt=lambda reason, data: halted.append(reason))
        monkeypatch.setattr(ap, "_fire_approval_hook", lambda *a, **k: None)
        try:
            ap._await_gateway_decision(key, notify, {"command": "rm -rf x", "description": "d", "pattern_key": "rm", "pattern_keys": ["rm"]})
        finally:
            ap.unregister_gateway_notify(key)
        assert halted == ["denied"]


class TestGatewayWording:
    def test_correction_text_names_the_replies(self):
        from gateway.run import _format_correction_approval

        text = _format_correction_approval("Answer says: X\nSource says: Y", "Correction proposed: …", "!")
        assert text.startswith("🔎 **Correction proposed")
        assert "Answer says: X" in text
        assert "`!approve`" in text and "`!approve session`" in text and "`!deny`" in text
        assert "keep the answer as written" in text


# ── Conversation loop, end to end ─────────────────────────────────────────


def _response(content="composed report"):
    message = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        model="test/model",
        usage=None,
    )


@pytest.fixture
def agent(tmp_path, monkeypatch):
    from run_agent import AIAgent

    monkeypatch.setenv("ROBO_HOME", str(tmp_path / ".robo"))
    monkeypatch.setenv("ROBO_FACT_CHECK", "1")
    monkeypatch.setenv("ROBO_VERIFY_ON_STOP", "0")
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        instance = AIAgent(
            session_id="fact-check-loop-test",
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
    instance.iteration_budget.max_total = 3
    return instance


def _run(agent, answers, *, result, decision):
    calls = []

    def model_call(api_kwargs):
        calls.append([dict(m) for m in api_kwargs["messages"]])
        return next(answers)

    agent._interruptible_api_call = model_call
    with (
        patch("agent.fact_check.run_fact_check", return_value=result) as run_fc,
        patch("agent.fact_check.gate_decision", return_value=decision) as gate,
        patch("robo_cli.plugins.has_hook", return_value=False),
        patch("robo_cli.plugins.invoke_hook", return_value=[]),
    ):
        out = agent.run_conversation("when was python 3.12 released, in one paragraph")
    return out, calls, run_fc, gate


def test_allowed_correction_revises_the_answer(agent):
    emitted = []
    agent.interim_assistant_callback = lambda text, **kw: emitted.append(text)
    answers = iter([_response("It was released in 2022."), _response("Corrected (python.org): it was released on 2 October 2023.")])

    out, calls, run_fc, gate = _run(agent, answers, result=_result(_contradicted()), decision="apply")

    assert out["final_response"] == "Corrected (python.org): it was released on 2 October 2023."
    assert out["completed"] is True
    run_fc.assert_called_once()
    gate.assert_called_once()
    # The first attempt reached the UI as an interim message.
    assert emitted == ["It was released in 2022."]
    # The second model call saw the attempt and the findings, user-role, last.
    second = calls[1]
    assert second[-2]["role"] == "assistant" and second[-2]["content"] == "It was released in 2022."
    assert second[-1]["role"] == "user" and "[Fact check]" in second[-1]["content"]
    assert "2 October 2023" in second[-1]["content"]
    # The nudge is scaffolding: stripped from the returned history; the
    # candidate stays (it is real content), collapsed under the final answer.
    roles = [m["role"] for m in out["messages"]]
    assert "user" not in roles[1:]
    assert not any(m.get("_fact_check_synthetic") for m in out["messages"])
    assert out["messages"][-1]["content"] == "Corrected (python.org): it was released on 2 October 2023."


def test_kept_answer_gets_the_note_and_no_second_call(agent):
    answers = iter([_response("It was released in 2022, as far as I know."), _response("unexpected")])

    out, calls, run_fc, _gate = _run(agent, answers, result=_result(_contradicted()), decision="keep")

    assert len(calls) == 1
    assert out["final_response"].startswith("It was released in 2022, as far as I know.")
    assert "🔎 Fact check — kept as written on your request." in out["final_response"]
    assert "2 October 2023" in out["final_response"]
    # The footer is display-only: the persisted assistant message is the answer as written.
    assert out["messages"][-1]["content"] == "It was released in 2022, as far as I know."


def test_nothing_contradicted_passes_straight_through(agent):
    answers = iter([_response("It was released on 2 October 2023."), _response("unexpected")])
    confirmed = Verdict(claim=_claim(), verdict="confirmed", finding="yes", source="s")

    out, calls, _run_fc, gate = _run(agent, answers, result=_result(confirmed), decision="apply")

    assert len(calls) == 1
    gate.assert_not_called()
    assert out["final_response"] == "It was released on 2 October 2023."


def test_check_failure_fails_open(agent):
    answers = iter([_response("It was released in 2022."), _response("unexpected")])
    calls = []

    def model_call(api_kwargs):
        calls.append(1)
        return next(answers)

    agent._interruptible_api_call = model_call
    with (
        patch("agent.fact_check.run_fact_check", side_effect=RuntimeError("provider down")),
        patch("robo_cli.plugins.has_hook", return_value=False),
        patch("robo_cli.plugins.invoke_hook", return_value=[]),
    ):
        out = agent.run_conversation("when was python 3.12 released, in one paragraph")
    assert len(calls) == 1
    assert out["final_response"] == "It was released in 2022."
    assert out["completed"] is True


def test_disabled_by_env_never_runs(agent, monkeypatch):
    monkeypatch.setenv("ROBO_FACT_CHECK", "0")
    answers = iter([_response("It was released in 2022.")])
    out, calls, run_fc, _gate = _run(agent, answers, result=_result(_contradicted()), decision="apply")
    run_fc.assert_not_called()
    assert out["final_response"] == "It was released in 2022."


def test_one_check_per_turn_and_state_resets_next_turn(agent):
    """The revised answer is not checked again (no loop), and the next
    turn starts fresh."""
    answers = iter([_response("attempt"), _response("revised"), _response("next turn answer")])
    calls = []

    def model_call(api_kwargs):
        calls.append(1)
        return next(answers)

    agent._interruptible_api_call = model_call

    with (
        patch("agent.fact_check.run_fact_check", return_value=_result(_contradicted())) as run_fc,
        patch("agent.fact_check.gate_decision", return_value="apply"),
        patch("robo_cli.plugins.has_hook", return_value=False),
        patch("robo_cli.plugins.invoke_hook", return_value=[]),
    ):
        first = agent.run_conversation("first question, long enough to be checked")
        assert first["final_response"] == "revised"
        # The attempt was checked; the revised answer was not (the gate
        # itself enforces one check per turn, not only the checker).
        assert run_fc.call_count == 1
        assert agent._fact_check_done is True
        run_fc.return_value = None
        second = agent.run_conversation("second question, long enough to be checked",
                                        conversation_history=first["messages"])
    assert second["final_response"] == "next turn answer"
    # Fresh turn: the gate ran again.
    assert run_fc.call_count == 2


def test_step_narration_flag_from_config(tmp_path, monkeypatch):
    from run_agent import AIAgent

    monkeypatch.setenv("ROBO_HOME", str(tmp_path / ".robo"))
    for value, expected in ((None, True), (False, False), (True, True)):
        cfg = {"agent": {}} if value is None else {"agent": {"step_narration": value}}
        with (
            patch("run_agent.get_tool_definitions", return_value=[]),
            patch("run_agent.check_toolset_requirements", return_value={}),
            patch("run_agent.OpenAI"),
            patch("robo_cli.config.load_config", return_value=cfg),
            patch("robo_cli.config.load_config_readonly", return_value=cfg),
        ):
            a = AIAgent(model="test/model", api_key="k", base_url="https://example.invalid/v1",
                        quiet_mode=True, skip_context_files=True, skip_memory=True)
        assert a._step_narration_guidance is expected


def test_real_research_over_the_registry_keeps_and_footnotes_when_nobody_can_be_asked(agent, tmp_path, monkeypatch):
    """End to end with the real tool registry: the auxiliary model is scripted,
    everything else is real — claim extraction, a read_file call through
    registry.dispatch against a real file, the verdict, the decision (no
    surface to ask → keep) and the footer."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "settings.py").write_text("PORT = 8080\n", encoding="utf-8")
    monkeypatch.setenv("TERMINAL_CWD", str(project))
    monkeypatch.delenv("ROBO_INTERACTIVE", raising=False)
    monkeypatch.delenv("ROBO_GATEWAY_SESSION", raising=False)

    agent.valid_tool_names = ["read_file", "search_files", "terminal"]
    agent._interruptible_api_call = lambda _kwargs: _response(
        "The server listens on port 9090, which settings.py sets in PORT. Nothing else needs changing today."
    )

    script = iter([
        json.dumps({"claims": [{"text": "settings.py sets PORT to 9090", "check": "code"}]}),
        json.dumps({"action": "read_file", "path": str(project / "settings.py")}),
        json.dumps({"action": "done", "verdicts": [{"claim": 1, "verdict": "contradicted",
                                                     "finding": "settings.py sets PORT = 8080.",
                                                     "source": "settings.py"}]}),
    ])
    seen = []

    def fake_call_llm(task=None, *, messages, **kw):
        seen.append((task, messages))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(script)))])

    statuses = []
    agent.status_callback = lambda kind, text: statuses.append((kind, text))

    with (
        patch("agent.auxiliary_client.call_llm", side_effect=fake_call_llm),
        patch("robo_cli.plugins.has_hook", return_value=False),
        patch("robo_cli.plugins.invoke_hook", return_value=[]),
    ):
        out = agent.run_conversation("what port does the server use, and where is it set?")

    assert [t for t, _ in seen] == ["fact_check"] * 3
    # The file really was read through the registry and fed back as evidence.
    evidence = seen[2][1][-1]["content"]
    assert evidence.startswith('<result action="read_file">') and "PORT = 8080" in evidence
    assert "🔎 Fact check — kept as written on your request." in out["final_response"]
    assert "settings.py sets PORT = 8080." in out["final_response"]
    assert out["messages"][-1]["content"].startswith("The server listens on port 9090")
    texts = [t for _k, t in statuses]
    assert any(t.startswith("🔎 Checking 1 statement in the answer") for t in texts)
    assert "🔎 Checked 1 statement against 1 source: 1 contradicted" in texts
