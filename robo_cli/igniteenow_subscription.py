"""Compatibility shim — Ignitee Now Portal has been removed as a provider option.

This module used to report which tool capabilities were unlocked by a Ignitee Now
Portal subscription. Ignitee Now is no longer offered anywhere in Robo, so every
check here honestly reports "not available" / "not managed by Ignitee Now" rather
than performing any real Ignitee Now-specific logic.

This exists so the files that still import from here continue to work
without every one of them needing an individual rewrite in the same pass —
each one already has its own non-Ignitee Now fallback path (a direct env-var
check, a plugin-registered provider, etc.) that it falls through to once
this reports nothing is available via Ignitee Now. That fallback behavior is
exactly what real users without a Ignitee Now subscription already saw before this
module existed in its original form, so this is not a change in behavior
for anyone who wasn't using Ignitee Now.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class _ToolFeatureStatus:
    """Per-toolset availability. Always unavailable-via-Ignitee Now; `available`
    reflects only whether *this shim* found it configured some other way,
    which it never does — real availability is each caller's own
    non-Ignitee Now fallback check, not this shim's job."""
    available: bool = False
    managed_by_igniteenow: bool = False
    current_provider: Optional[str] = None
    direct_override: bool = False


# Some callers import this same shape under a different historical name.
IgniteeNowFeatureState = _ToolFeatureStatus


class _AlwaysUnavailableFeatures:
    """`.features.get(any_key)` always returns a safely-unavailable status,
    for toolset keys this shim was never told about in advance."""
    def get(self, key: str, default: Any = None) -> _ToolFeatureStatus:
        return _ToolFeatureStatus()

    def __getitem__(self, key: str) -> _ToolFeatureStatus:
        return _ToolFeatureStatus()


@dataclass
class _AccountInfo:
    logged_in: bool = False
    paid_service_access: Optional[bool] = False
    tool_gateway_entitled: bool = False

    def tool_gateway_entitled_for(self, *_a, **_kw) -> bool:
        return False


@dataclass
class IgniteeNowSubscriptionFeatures:
    """Same public shape the real implementation had. Every field defaults
    to "nothing is available via Ignitee Now" — see module docstring."""
    features: _AlwaysUnavailableFeatures = field(default_factory=_AlwaysUnavailableFeatures)
    account_info: _AccountInfo = field(default_factory=_AccountInfo)
    igniteenow_auth_present: bool = False

    def __getattr__(self, name: str) -> _ToolFeatureStatus:
        # Any attribute this shim wasn't explicitly given (e.g. direct
        # attribute access like `.web` instead of `.features.get("web")`)
        # degrades to the same safely-unavailable status rather than
        # raising AttributeError.
        return _ToolFeatureStatus()


# Empty on purpose — no managed feature is covered by a (nonexistent) Ignitee Now
# subscription anymore. `.get(x)` on an empty dict safely returns None,
# matching how callers already handle "this feature has no coverage entry".
MANAGED_FEATURE_COVERAGE_CATEGORY: dict = {}


def get_igniteenow_subscription_features(config: dict = None, *, force_fresh: bool = False) -> IgniteeNowSubscriptionFeatures:
    """Always returns the safely-unavailable feature set. See module docstring."""
    return IgniteeNowSubscriptionFeatures()


def apply_igniteenow_managed_defaults(*_args, **_kwargs) -> set:
    """Nothing to apply — there is no managed Ignitee Now configuration to default to.

    Returns the same shape the real implementation returned: the SET of
    toolset keys that were auto-configured (always empty here). The first
    fork stub returned ``False``, which ``robo tools`` / the setup wizard
    iterate (``for ts_key in sorted(auto_configured)``) — every fresh install
    crashed with ``TypeError: 'bool' object is not iterable`` at the end of
    tool selection.
    """
    return set()


def prompt_enable_tool_gateway(*_args, **_kwargs) -> None:
    """No-op — the Tool Gateway was a Ignitee Now-subscription feature."""
    return None


def ensure_igniteenow_portal_access(*_args, **_kwargs) -> bool:
    """Always False — there is no Ignitee Now Portal to check access against."""
    return False


def _local_browser_runnable() -> bool:
    """Genuinely generic check (not Ignitee Now-specific) — is the agent-browser
    CLI actually installed and runnable."""
    import shutil
    return shutil.which("agent-browser") is not None


def _has_agent_browser() -> bool:
    """Alias kept for callers using the older name."""
    return _local_browser_runnable()
