"""A message typed while tools run must reach the model now, not after the batch.

``AIAgent.redirect()`` used to degrade to ``steer()`` whenever
``_executing_tools`` was set, so the correction only rode on the last tool
result once the whole batch finished. In ``interrupt`` mode it now cancels
the running batch cooperatively and queues the text as a real redirect that
the conversation loop applies on the next iteration; ``redirect`` mode keeps
the gentle behaviour.
"""
from __future__ import annotations

import threading

import pytest

import run_agent
from run_agent import AIAgent


def _agent(mode: str, monkeypatch) -> AIAgent:
    a = object.__new__(AIAgent)
    a._executing_tools = True
    a._interrupt_requested = False
    a._interrupt_message = None
    a._pending_redirect = None
    a._pending_redirect_lock = threading.Lock()
    a._pending_steer = None
    a._pending_steer_lock = threading.Lock()
    a._model_request_active = threading.Event()
    a._execution_thread_id = threading.get_ident()
    a._interrupt_thread_signal_pending = False
    a._tool_worker_threads = set()
    a._tool_worker_threads_lock = threading.Lock()
    a._active_children = []
    a._active_children_lock = threading.Lock()
    a.api_mode = "chat_completions"
    monkeypatch.setattr(AIAgent, "_busy_correction_interrupts_tools", lambda self: mode != "redirect")
    return a


@pytest.fixture(autouse=True)
def _clean_interrupt_flag():
    yield
    run_agent._set_interrupt(False, threading.get_ident())


def test_interrupt_mode_cancels_batch_and_queues_redirect(monkeypatch):
    a = _agent("interrupt", monkeypatch)
    child_calls = []

    class Child:
        def interrupt(self, msg=None):
            child_calls.append(msg)

    a._active_children.append(Child())
    assert a.redirect("actually, use the other config") is True
    assert a._pending_redirect == "actually, use the other config"
    assert a._interrupt_requested is True
    assert a._pending_steer is None
    assert a._has_pending_redirect()
    assert child_calls  # delegated children are cancelled with the batch
    from tools.interrupt import is_interrupted
    assert is_interrupted()  # the running tool sees the cancellation


def test_second_correction_concatenates(monkeypatch):
    a = _agent("interrupt", monkeypatch)
    assert a.redirect("first") and a.redirect("second")
    assert "first" in a._pending_redirect and "[Additional user correction]" in a._pending_redirect
    assert a._pending_redirect.endswith("second")


def test_hard_stop_in_flight_rejects_redirect(monkeypatch):
    a = _agent("interrupt", monkeypatch)
    a._interrupt_requested = True  # /stop already fired, no redirect queued
    assert a.redirect("hello") is False


def test_redirect_mode_keeps_gentle_steer(monkeypatch):
    a = _agent("redirect", monkeypatch)
    assert a.redirect("gentle") is True
    assert a._pending_steer == "gentle"
    assert a._pending_redirect is None
    assert a._interrupt_requested is False


def test_loop_top_applies_redirect_and_clears_interrupt(monkeypatch):
    """Simulate the conversation loop's top-of-iteration handling."""
    a = _agent("interrupt", monkeypatch)
    a.thinking_callback = None
    a.redirect("go left")
    cleared = []
    monkeypatch.setattr(AIAgent, "clear_interrupt", lambda self, preserve_redirect=False: cleared.append(preserve_redirect) or True)
    text = a._drain_pending_redirect()
    assert text == "go left"
    if a._interrupt_requested:
        a.clear_interrupt()
    assert cleared == [False]
