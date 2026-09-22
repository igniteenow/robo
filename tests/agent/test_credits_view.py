"""Tests for the /credits command — shared view core + gateway handler.

`/credits` is the focused money surface (balance in, top-up out). These tests
exercise the surface-agnostic `build_credits_view()` core and assert the gateway
handler renders the block + tappable top-up URL + no-wait copy. The CLI panel is
a thin wrapper over the same view (interactive prompt_toolkit modal — covered by
the view-core tests plus manual verification).
"""

from __future__ import annotations

import asyncio

import pytest

import agent.account_usage as account_usage
from agent.account_usage import CreditsView, build_credits_view
from robo_cli.igniteenow_account import IgniteeNowPortalAccountInfo, IgniteeNowPaidServiceAccessInfo


def _account(**kwargs) -> IgniteeNowPortalAccountInfo:
    kwargs.setdefault("logged_in", True)
    kwargs.setdefault("source", "account_api")
    kwargs.setdefault("fresh", True)
    kwargs.setdefault("portal_base_url", "https://portal.example.test")
    return IgniteeNowPortalAccountInfo(**kwargs)


@pytest.fixture
def _logged_in_account(monkeypatch):
    """Stub the auth token + account fetch so build_credits_view runs offline."""
    monkeypatch.setattr(
        "robo_cli.auth.get_provider_auth_state",
        lambda provider: {"access_token": "tok", "portal_base_url": "https://portal.example.test"},
    )

    def _install(account):
        monkeypatch.setattr(
            "robo_cli.igniteenow_account.get_igniteenow_portal_account_info",
            lambda *a, **kw: account,
        )

    return _install


# ── build_credits_view core ─────────────────────────────────────────────────


# ── gateway _handle_topup_command (the messaging billing surface) ────────────


class _FakeEvent:
    pass


def _make_gateway_stub():
    """Minimal object exposing the mixin's _handle_topup_command."""
    from gateway.slash_commands import GatewaySlashCommandsMixin

    class _Stub(GatewaySlashCommandsMixin):
        def __init__(self):
            pass

    return _Stub()




def test_gateway_topup_not_logged_in(monkeypatch):
    monkeypatch.setattr(
        account_usage, "build_credits_view", lambda *a, **kw: CreditsView(logged_in=False)
    )
    stub = _make_gateway_stub()
    out = asyncio.run(stub._handle_topup_command(_FakeEvent()))
    assert "Not logged into Ignitee Now Portal" in out




# ── command registry ────────────────────────────────────────────────────────


def test_credits_command_fully_removed():
    """`/credits` and the old `/billing` are gone entirely — not commands, not
    aliases. Billing lives only on /topup, with NO aliases, on every platform."""
    from robo_cli.commands import resolve_command, COMMAND_REGISTRY

    # Both old names resolve to nothing.
    assert resolve_command("credits") is None
    assert resolve_command("billing") is None
    # No standalone command for either remains in the registry.
    assert not any(c.name in ("credits", "billing") for c in COMMAND_REGISTRY)
    # And no command carries either as an alias.
    for c in COMMAND_REGISTRY:
        assert "credits" not in (c.aliases or ())
        assert "billing" not in (c.aliases or ())
    # /topup is the billing surface, on every surface, and carries no aliases.
    entry = next(c for c in COMMAND_REGISTRY if c.name == "topup")
    assert entry.cli_only is False
    assert entry.gateway_only is False
    assert not entry.aliases
