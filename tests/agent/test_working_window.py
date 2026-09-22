"""``context.working_window`` — Robo's 2M working window ceiling."""
from __future__ import annotations

import pytest

from agent import model_metadata as mm


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # Force the static table path: resolution must not touch the network here.
    monkeypatch.setattr(mm, "_resolve_model_context_length",
                        lambda model, **kw: {"ten-m": 10_000_000, "two-m": 2_097_152, "one-m": 1_000_000,
                                             "small": 200_000}.get(model, 256_000))
    yield


def test_default_ceiling_is_two_million(monkeypatch):
    monkeypatch.setattr(mm, "_configured_working_window", lambda: mm.DEFAULT_WORKING_WINDOW)
    assert mm.DEFAULT_WORKING_WINDOW == 2_000_000
    assert mm.get_model_context_length("ten-m") == 2_000_000
    assert mm.get_model_context_length("two-m") == 2_000_000
    assert mm.get_model_context_length("one-m") == 1_000_000
    assert mm.get_model_context_length("small") == 200_000


def test_explicit_override_wins_over_ceiling(monkeypatch):
    monkeypatch.setattr(mm, "_configured_working_window", lambda: 2_000_000)
    monkeypatch.setattr(mm, "_resolve_model_context_length", lambda model, **kw: kw.get("config_context_length") or 1)
    assert mm.get_model_context_length("proxy", config_context_length=2_000_000) == 2_000_000
    assert mm.get_model_context_length("proxy", config_context_length=5_000_000) == 5_000_000


def test_zero_disables_ceiling(monkeypatch):
    monkeypatch.setattr(mm, "_configured_working_window", lambda: 0)
    assert mm.get_model_context_length("ten-m") == 10_000_000


def test_config_default_and_static_entries():
    from robo_cli.config_defaults import DEFAULT_CONFIG
    assert DEFAULT_CONFIG["context"]["working_window"] == 2_000_000
    assert DEFAULT_CONFIG["approvals"]["interactive_timeout"] == 0
    assert DEFAULT_CONFIG["approvals"]["deny_stops_turn"] is True
    assert DEFAULT_CONFIG["display"]["busy_input_mode"] == "interrupt"
    assert DEFAULT_CONFIG["reverse_engineering"]["backend"] == "auto"
    assert mm.DEFAULT_CONTEXT_LENGTHS["gemini-1.5-pro"] >= 2_000_000
    assert mm.DEFAULT_CONTEXT_LENGTHS["grok-4-fast"] == 2_000_000
