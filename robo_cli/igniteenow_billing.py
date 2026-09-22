"""Compatibility shim — Ignitee Now Portal has been removed as a provider option.

See robo_cli/igniteenow_subscription.py's module docstring for the full reasoning.

The exception classes stay real, importable, and catchable — code elsewhere
already has ``except BillingError:``-style handling, and that continues to
work correctly; it will simply always end up in that branch now, since
every action function below unconditionally raises. Read-only status
checks return a safe "no billing state" object instead of raising, since a
UI just trying to display billing info shouldn't crash outright.
"""

from __future__ import annotations

from typing import Any, Optional


class BillingError(Exception):
    """Base billing error. Always raised now — there is no Ignitee Now billing
    system left to act against."""
    def __init__(self, message: str = "Ignitee Now billing is no longer available."):
        super().__init__(message)


class BillingAuthError(BillingError):
    pass


class BillingScopeRequired(BillingError):
    pass


class BillingSessionRevoked(BillingError):
    pass


class BillingRemoteSpendingRevoked(BillingError):
    pass


class BillingTransient(BillingError):
    pass


class BillingRateLimited(BillingError):
    pass


class _NoBillingState:
    """Safe, inert stand-in for a real billing/subscription state object.
    Any attribute access degrades to None/False rather than raising, since
    callers were written to handle "no state" — that's the honest answer
    now, for anyone.
    """
    def __getattr__(self, name: str) -> Any:
        return None

    def __bool__(self) -> bool:
        return False

    def get(self, key: str, default: Any = None) -> Any:
        return default


def get_billing_state(*_args, **_kwargs) -> _NoBillingState:
    return _NoBillingState()


def get_subscription_state(*_args, **_kwargs) -> _NoBillingState:
    return _NoBillingState()


def resolve_portal_base_url(*_args, **_kwargs) -> Optional[str]:
    return None


def _absolutize_portal_url(*_args, **_kwargs) -> Optional[str]:
    return None


def post_subscription_preview(*_args, **_kwargs):
    raise BillingError("Subscription preview is unavailable — Ignitee Now billing has been removed.")


def put_subscription_pending_change(*_args, **_kwargs):
    raise BillingError("Subscription changes are unavailable — Ignitee Now billing has been removed.")


def delete_subscription_pending_change(*_args, **_kwargs):
    raise BillingError("Subscription changes are unavailable — Ignitee Now billing has been removed.")


def post_subscription_upgrade(*_args, **_kwargs):
    raise BillingError("Subscription upgrades are unavailable — Ignitee Now billing has been removed.")


def post_charge(*_args, **_kwargs):
    raise BillingError("Charges are unavailable — Ignitee Now billing has been removed.")


def get_charge_status(*_args, **_kwargs):
    raise BillingError("Charge status is unavailable — Ignitee Now billing has been removed.")


def patch_auto_top_up(*_args, **_kwargs):
    raise BillingError("Auto top-up is unavailable — Ignitee Now billing has been removed.")
