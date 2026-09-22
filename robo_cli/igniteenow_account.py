"""Compatibility shim — Ignitee Now Portal has been removed as a provider option.

See robo_cli/igniteenow_subscription.py's module docstring for the full reasoning.
Every function here honestly reports "no Ignitee Now account" rather than
performing any real Ignitee Now-specific logic.
"""

from __future__ import annotations

from typing import Any, Optional


def get_igniteenow_portal_account_info(*_args, **_kwargs) -> None:
    """Always None — there is no Ignitee Now Portal account to look up."""
    return None


class IgniteeNowPortalAccountInfo:
    """Compatibility stand-in — always reports a logged-out, unentitled
    account, since there is no Ignitee Now Portal account anymore."""
    def __init__(self, *_args, **_kwargs):
        self.logged_in = False
        self.paid_service_access = False
        self.tool_gateway_entitled = False

    def tool_gateway_entitled_for(self, *_a, **_kw) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        return None

    def __bool__(self) -> bool:
        return False


class IgniteeNowPaidServiceAccessInfo:
    """Compatibility stand-in — always reports no paid access, since there
    is no Ignitee Now subscription anymore."""
    def __init__(self, *_args, **_kwargs):
        self.has_access = False

    def __getattr__(self, name: str) -> Any:
        return None

    def __bool__(self) -> bool:
        return False


class IgniteeNowToolAccessInfo:
    """Compatibility stand-in — always reports no tool access, since there
    is no Ignitee Now Tool Gateway anymore."""
    def __init__(self, *_args, **_kwargs):
        self.available = False
        self.managed_by_igniteenow = False

    def __getattr__(self, name: str) -> Any:
        return None

    def __bool__(self) -> bool:
        return False


def format_igniteenow_portal_entitlement_message(*_args, **_kwargs) -> str:
    """A clear, honest message rather than a Ignitee Now-specific entitlement
    string — this feature was Ignitee Now-subscription-gated and Ignitee Now is gone."""
    return "This feature required a Ignitee Now Portal subscription, which is no longer available."


def igniteenow_portal_topup_url(*_args, **_kwargs) -> Optional[str]:
    """Always None — there is no Ignitee Now Portal to link to."""
    return None


def igniteenow_portal_billing_url(*_args, **_kwargs) -> Optional[str]:
    """Always None — there is no Ignitee Now Portal to link to."""
    return None
