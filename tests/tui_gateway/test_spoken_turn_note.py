"""A turn that arrived by voice is shaped for the ear.

The desktop's hands-free voice chat sends ``prompt.submit`` with
``voice: true``; the TUI's voice chat is the backend voice-mode flag. Either
way the runner prepends ``SPOKEN_TURN_NOTE`` to the MODEL INPUT only — the
persisted user message stays the clean transcript (same enrichment channel as
the speech-interrupted note). Contract pinned here:

* the latch is consumed by the turn it was set for and never leaks into the
  next one (an early exit included);
* a voice turn that lands mid-turn keeps its mark on the queued envelope and
  is still shaped when the drain finally runs it;
* ``prompt.submit`` latches right before the run, not at submit time;
* the note reaches the model and not the transcript, for text and for
  content-part messages.
"""

from __future__ import annotations

import threading
import types

import pytest

from tools.tts_streaming import SPOKEN_TURN_NOTE
from tui_gateway import server


class _InlineThread:
    def __init__(self, target=None, daemon=None, args=(), kwargs=None, **_ignored):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)

    def is_alive(self):
        return False

    def join(self, timeout=None):
        return None


def _session(agent=None, **extra):
    return {
        "agent": agent if agent is not None else types.SimpleNamespace(),
        "session_key": "session-key",
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "transport": None,
        "attached_images": [],
        "image_counter": 0,
        "cols": 80,
        "slash_worker": None,
        "show_reasoning": False,
        "tool_progress_mode": "all",
        "inflight_turn": None,
        **extra,
    }


@pytest.fixture()
def turn_env(monkeypatch, tmp_path):
    """Neutralize the turn pipeline's environment-heavy side paths (mirrors
    tests/tui_gateway/test_auto_continue.py)."""
    monkeypatch.setattr(server, "_robo_home", tmp_path)
    monkeypatch.setattr(server, "_emit", lambda event, sid, payload=None: None)
    monkeypatch.setattr(server.threading, "Thread", _InlineThread)
    monkeypatch.setattr(server, "_wire_callbacks", lambda sid: None)
    monkeypatch.setattr(server, "_sync_agent_model_with_config", lambda sid, session: None)
    monkeypatch.setattr(server, "_session_cwd", lambda session: str(tmp_path))
    monkeypatch.setattr(server, "_register_session_cwd", lambda session: None)
    monkeypatch.setattr(server, "_tts_stream_begin", lambda: None)
    monkeypatch.setattr(server, "_sync_session_key_after_compress", lambda *a, **k: None)
    monkeypatch.setattr(server, "_get_usage", lambda agent: {})
    monkeypatch.setattr(server, "_voice_mode_enabled", lambda: False)
    monkeypatch.setattr(server, "_voice_cfg_dict", lambda: {})


def _agent(seen: list, persisted: list | None = None, reasoning_seen: list | None = None):
    agent = types.SimpleNamespace(session_id="session-key", clear_interrupt=lambda: None)
    agent.reasoning_config = {"enabled": True, "effort": "high"}

    def _run(message, **kwargs):
        seen.append(message)
        if persisted is not None:
            persisted.append(kwargs.get("persist_user_message"))
        if reasoning_seen is not None:
            reasoning_seen.append(agent.reasoning_config)
        return {"final_response": "done"}

    agent.run_conversation = _run
    return agent


# ── The latch ──────────────────────────────────────────────────────────


def test_latch_is_consumed_by_the_turn_it_was_set_for(monkeypatch):
    monkeypatch.setattr(server, "_voice_mode_enabled", lambda: False)
    session = _session(_spoken_turn=True)

    assert server._spoken_turn(session) is True
    assert "_spoken_turn" not in session
    assert server._spoken_turn(session) is False


def test_tui_voice_mode_counts_as_spoken(monkeypatch):
    monkeypatch.setattr(server, "_voice_mode_enabled", lambda: True)
    assert server._spoken_turn(_session()) is True

    monkeypatch.setattr(server, "_voice_mode_enabled", lambda: (_ for _ in ()).throw(RuntimeError("no voice")))
    assert server._spoken_turn(_session()) is False


def test_early_exit_still_consumes_the_latch(turn_env):
    """A run that bails on a stale queue generation must not hand its note to
    whatever turn runs next."""
    seen: list = []
    session = _session(agent=_agent(seen), running=True, _spoken_turn=True, _queued_prompt_generation=2)

    server._run_prompt_submit("rid", "sid", session, "stale", queued_prompt_generation=1)

    assert seen == []
    assert "_spoken_turn" not in session


# ── Busy sessions: the mark rides the queued envelope ───────────────────


def test_enqueue_marks_a_spoken_turn_and_keeps_it_through_a_merge():
    session = _session()
    server._enqueue_prompt(session, "typed", "ws-1")
    assert "voice" not in session["queued_prompt"]

    server._enqueue_prompt(session, "spoken", "ws-1", voice=True)
    assert session["queued_prompt"] == {"text": "typed\n\nspoken", "transport": "ws-1", "voice": True}

    session = _session()
    server._enqueue_prompt(session, "spoken", "ws-1", voice=True)
    server._enqueue_prompt(session, "with picture", "ws-1", image_paths=["/tmp/c.png"])
    assert session["queued_prompt"]["voice"] is True
    assert "voice" not in session["queued_prompts"][0]


def test_busy_submit_queues_a_spoken_turn_with_its_mark(monkeypatch):
    monkeypatch.setattr(server, "_load_busy_input_mode", lambda: "queue")
    monkeypatch.setattr(server, "_emit_mid_turn_user_echo", lambda *a, **k: None)
    session = _session(running=True)

    resp = server._handle_busy_submit("r1", "sid", session, "how are you", "ws-1", voice=True)

    assert resp["result"] == {"status": "queued"}
    assert session["queued_prompt"]["voice"] is True


def test_drain_hands_the_mark_to_the_run(monkeypatch):
    latched: list = []

    def _run(_rid, _sid, session, text, **_kwargs):
        latched.append((text, session.get("_spoken_turn")))
        session["running"] = False

    monkeypatch.setattr(server, "_run_prompt_submit", _run)
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda _session: False)

    session = _session(queued_prompt={"text": "spoken", "transport": None, "voice": True})
    assert server._drain_queued_prompt("r1", "sid", session) is True
    session = _session(queued_prompt={"text": "typed", "transport": None})
    assert server._drain_queued_prompt("r1", "sid", session) is True

    assert latched == [("spoken", True), ("typed", False)]


# ── prompt.submit latches right before the run ─────────────────────────


@pytest.mark.parametrize("voice", [True, False])
def test_prompt_submit_latches_the_flag_for_the_run(monkeypatch, voice):
    latched: list = []
    session = _session(agent=None, agent_ready=threading.Event())
    server._sessions["voice-latch"] = session
    monkeypatch.setattr(server, "_load_cfg", lambda: {})
    monkeypatch.setattr(server, "_ensure_session_db_row", lambda _session: None)
    monkeypatch.setattr(server, "_persist_branch_seed", lambda _session: None)
    monkeypatch.setattr(server, "_start_agent_build", lambda _sid, _session: None)
    monkeypatch.setattr(server, "_wait_agent_for_prompt", lambda _session, _rid, _sid: None)
    monkeypatch.setattr(
        server,
        "_run_prompt_submit",
        lambda rid, sid, session, text: latched.append((text, session.get("_spoken_turn"))),
    )
    monkeypatch.setattr(server.threading, "Thread", _InlineThread)

    try:
        resp = server.handle_request(
            {
                "id": "voice-turn",
                "method": "prompt.submit",
                "params": {"session_id": "voice-latch", "text": "tell me about yourself", "voice": voice},
            }
        )
    finally:
        server._sessions.pop("voice-latch", None)

    assert resp["result"] == {"status": "streaming"}
    assert latched == [("tell me about yourself", voice)]


# ── The note reaches the model, never the transcript ────────────────────


def test_spoken_turn_note_is_model_input_only(turn_env):
    seen: list = []
    persisted: list = []
    session = _session(agent=_agent(seen, persisted), running=True, _spoken_turn=True)

    server._run_prompt_submit("rid", "sid", session, "tell me about yourself")

    assert seen == [f"{SPOKEN_TURN_NOTE}\n\ntell me about yourself"]
    # The agent persists the transcript from persist_user_message: clean.
    assert persisted == ["tell me about yourself"]
    assert "_spoken_turn" not in session


def test_typed_turn_is_untouched(turn_env):
    seen: list = []
    session = _session(agent=_agent(seen), running=True)

    server._run_prompt_submit("rid", "sid", session, "tell me about yourself")

    assert seen == ["tell me about yourself"]


def test_tui_voice_chat_shapes_every_turn(turn_env, monkeypatch):
    monkeypatch.setattr(server, "_voice_mode_enabled", lambda: True)
    seen: list = []
    session = _session(agent=_agent(seen), running=True)

    server._run_prompt_submit("rid", "sid", session, "what time is it")

    assert seen == [f"{SPOKEN_TURN_NOTE}\n\nwhat time is it"]


# ── A spoken turn answers fast: reasoning off for that turn only ─────────


def test_spoken_turn_runs_with_reasoning_off_and_restores_the_model_setting(turn_env):
    seen: list = []
    reasoning_seen: list = []
    agent = _agent(seen, reasoning_seen=reasoning_seen)
    session = _session(agent=agent, running=True, _spoken_turn=True)

    server._run_prompt_submit("rid", "sid", session, "what is the capital of france")

    assert reasoning_seen == [{"enabled": False}]
    assert agent.reasoning_config == {"enabled": True, "effort": "high"}


def test_typed_turn_keeps_the_model_reasoning(turn_env):
    reasoning_seen: list = []
    agent = _agent([], reasoning_seen=reasoning_seen)
    session = _session(agent=agent, running=True)

    server._run_prompt_submit("rid", "sid", session, "think hard about this")

    assert reasoning_seen == [{"enabled": True, "effort": "high"}]


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("low", {"enabled": True, "effort": "low"}),
        (False, {"enabled": False}),
        ("inherit", {"enabled": True, "effort": "high"}),
        ("", {"enabled": True, "effort": "high"}),
        ("bogus", {"enabled": True, "effort": "high"}),
    ],
)
def test_voice_reasoning_effort_is_configurable(turn_env, monkeypatch, configured, expected):
    monkeypatch.setattr(server, "_voice_cfg_dict", lambda: {"reasoning_effort": configured})
    reasoning_seen: list = []
    agent = _agent([], reasoning_seen=reasoning_seen)
    session = _session(agent=agent, running=True, _spoken_turn=True)

    server._run_prompt_submit("rid", "sid", session, "hello")

    assert reasoning_seen == [expected]
    assert agent.reasoning_config == {"enabled": True, "effort": "high"}


def test_override_is_restored_even_when_the_turn_raises(turn_env):
    agent = _agent([])

    def _boom(message, **kwargs):
        raise RuntimeError("provider down")

    agent.run_conversation = _boom
    session = _session(agent=agent, running=True, _spoken_turn=True)

    server._run_prompt_submit("rid", "sid", session, "hello")

    assert agent.reasoning_config == {"enabled": True, "effort": "high"}


def test_override_skips_agents_without_a_reasoning_config():
    agent = types.SimpleNamespace()
    assert server._spoken_turn_reasoning_override(agent) is None
