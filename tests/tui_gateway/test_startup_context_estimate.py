"""The status bar's context gauge is there at "ready", not one turn later.

``_get_usage`` only reports context occupancy from the provider's real
prompt-token count, so before the first reply the TUI showed no ``39k/1m
[███] 4%`` and no ``System Prompt — N chars``. The agent-build thread now
estimates the request the first turn will make and re-announces
``session.info`` with the gauge flagged ``context_estimated``; the first real
reply replaces it.
"""

import threading
import types

from tui_gateway import server


def _session(agent=None, **extra):
    return {
        "agent": agent,
        "session_key": "session-key",
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "attached_images": [],
        **extra,
    }


def _agent(prompt_parts=None, tools=None, ctx_len=1_000_000, last_prompt=0):
    parts = prompt_parts if prompt_parts is not None else {
        "stable": "You are Robo.",
        "context": "Workspace: /repo",
        "volatile": "Skills: none",
    }
    return types.SimpleNamespace(
        model="deepseek-v4-pro",
        tools=tools if tools is not None else [
            {"type": "function", "function": {"name": "terminal", "description": "run", "parameters": {}}}
        ],
        context_compressor=types.SimpleNamespace(
            context_length=ctx_len, last_prompt_tokens=last_prompt, compression_count=0
        ),
        _build_system_prompt_parts=lambda: parts,
        _cached_system_prompt="",
    )


def _capture(monkeypatch):
    emitted = []
    monkeypatch.setattr(server, "_emit", lambda event, sid, payload=None: emitted.append((event, sid, payload)))
    monkeypatch.setattr(server, "_session_info", lambda agent, session=None: {"usage": server._session_usage_snapshot(session), "system_prompt": ""})
    return emitted


def test_seed_estimates_the_first_request_and_reannounces_session_info(monkeypatch):
    emitted = _capture(monkeypatch)
    agent = _agent()
    session = _session(agent=agent)
    server._sessions["sid"] = session
    try:
        assert server._seed_startup_context_estimate("sid", session, agent) is True
    finally:
        server._sessions.pop("sid", None)

    est = session["_startup_context_estimate"]
    assert est["context_used"] > 0
    assert est["context_max"] == 1_000_000
    assert est["system_prompt"] == "You are Robo.\n\nWorkspace: /repo\n\nSkills: none"
    # The prompt is never cached on the agent — the first turn builds its own.
    assert agent._cached_system_prompt == ""
    assert [e[0] for e in emitted] == ["session.info"]
    usage = emitted[0][2]["usage"]
    assert usage["context_estimated"] is True
    assert usage["context_used"] == est["context_used"]
    assert usage["context_max"] == 1_000_000
    assert usage["context_percent"] == 0  # a few hundred tokens of a 1M window rounds to 0


def test_estimate_counts_tools_and_resumed_history(monkeypatch):
    _capture(monkeypatch)
    bare = _agent(tools=[])
    bare_session = _session(agent=bare)
    server._sessions["sid"] = bare_session
    try:
        server._seed_startup_context_estimate("sid", bare_session, bare)
    finally:
        server._sessions.pop("sid", None)

    heavy = _agent(tools=[{"type": "function", "function": {"name": f"tool{i}", "description": "x" * 400, "parameters": {}}} for i in range(20)])
    heavy_session = _session(agent=heavy, history=[{"role": "user", "content": "hello " * 500}])
    server._sessions["sid"] = heavy_session
    try:
        server._seed_startup_context_estimate("sid", heavy_session, heavy)
    finally:
        server._sessions.pop("sid", None)

    assert heavy_session["_startup_context_estimate"]["context_used"] > bare_session["_startup_context_estimate"]["context_used"]


def test_snapshot_prefers_the_real_count_once_a_turn_ran():
    agent = _agent(last_prompt=39_200)
    session = _session(agent=agent, _startup_context_estimate={"context_used": 5, "context_max": 1_000_000, "system_prompt": "x"})

    usage = server._session_usage_snapshot(session)

    assert usage["context_used"] == 39_200
    assert usage["context_estimated"] is False  # explicit, so a merging client retires the estimate


def test_snapshot_without_estimate_keeps_the_gauge_unknown():
    agent = _agent()
    usage = server._session_usage_snapshot(_session(agent=agent))
    assert "context_used" not in usage
    assert "context_estimated" not in usage


def test_seed_is_a_noop_for_agents_without_a_prompt_builder(monkeypatch):
    emitted = _capture(monkeypatch)
    agent = types.SimpleNamespace(model="m", tools=[], context_compressor=None)
    session = _session(agent=agent)
    server._sessions["sid"] = session
    try:
        assert server._seed_startup_context_estimate("sid", session, agent) is False
    finally:
        server._sessions.pop("sid", None)
    assert "_startup_context_estimate" not in session
    assert emitted == []


def test_seed_never_raises_and_leaves_the_gauge_off_on_failure(monkeypatch):
    emitted = _capture(monkeypatch)

    def boom():
        raise RuntimeError("context file unreadable")

    agent = _agent()
    agent._build_system_prompt_parts = boom
    session = _session(agent=agent)
    server._sessions["sid"] = session
    try:
        assert server._seed_startup_context_estimate("sid", session, agent) is False
    finally:
        server._sessions.pop("sid", None)
    assert "_startup_context_estimate" not in session
    assert emitted == []


def test_seed_does_not_announce_a_session_that_was_closed_meanwhile(monkeypatch):
    emitted = _capture(monkeypatch)
    agent = _agent()
    session = _session(agent=agent)
    # Not registered in server._sessions: closed/replaced during the build.
    assert server._seed_startup_context_estimate("sid", session, agent) is False
    assert "_startup_context_estimate" in session  # computed, but not announced
    assert emitted == []


def test_session_info_shows_the_estimated_prompt_before_the_first_turn(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {})
    agent = _agent()
    session = _session(agent=agent, _startup_context_estimate={"context_used": 42, "context_max": 1_000_000, "system_prompt": "You are Robo."})
    server._sessions["sid"] = session
    try:
        info = server._session_info(agent, session)
    finally:
        server._sessions.pop("sid", None)

    assert info["system_prompt"] == "You are Robo."
    assert info["usage"]["context_estimated"] is True
    assert info["usage"]["context_used"] == 42

    # Once the agent has its real cached prompt, that wins.
    agent._cached_system_prompt = "REAL PROMPT"
    info = server._session_info(agent, session)
    assert info["system_prompt"] == "REAL PROMPT"


def test_async_seed_binds_the_session_context_and_runs_inline_under_pytest(monkeypatch):
    """The estimate must read the same cwd / context files as the first turn:
    the build thread clears the session context before it finishes, so the
    seeder binds it again (and the profile home) for its own run."""
    emitted = _capture(monkeypatch)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "inline")  # the seeder runs inline under pytest
    bound, cleared, homes = [], [], []
    monkeypatch.setattr(server, "_set_session_context", lambda key, **kw: bound.append((key, kw)) or ["tok"])
    monkeypatch.setattr(server, "_clear_session_context", lambda tokens: cleared.append(tokens))
    monkeypatch.setattr(server, "set_robo_home_override", lambda home: homes.append(("set", home)) or "h")
    monkeypatch.setattr(server, "reset_robo_home_override", lambda token: homes.append(("reset", token)))

    agent = _agent()
    session = _session(agent=agent)
    server._sessions["sid"] = session
    try:
        server._seed_startup_context_estimate_async("sid", session, "session-key", "/profiles/work")
    finally:
        server._sessions.pop("sid", None)

    assert "_startup_context_estimate" in session
    assert [e[0] for e in emitted] == ["session.info"]
    assert bound == [("session-key", {"ui_session_id": "sid"})]
    assert cleared == [["tok"]]
    assert homes == [("set", "/profiles/work"), ("reset", "h")]


def test_async_seed_skips_once_a_turn_is_running(monkeypatch):
    emitted = _capture(monkeypatch)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "inline")
    monkeypatch.setattr(server, "_set_session_context", lambda key, **kw: [])
    monkeypatch.setattr(server, "_clear_session_context", lambda tokens: None)

    session = _session(agent=_agent(), running=True)
    server._sessions["sid"] = session
    try:
        server._seed_startup_context_estimate_async("sid", session, "session-key", None)
    finally:
        server._sessions.pop("sid", None)

    assert "_startup_context_estimate" not in session
    assert emitted == []
