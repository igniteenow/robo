"""Free web search + page reading with no API key — bundled, auto-loaded.

Rotates across the anonymous free tiers of Exa, Parallel, Firecrawl and
Keenable; reads pages with Robo's own reader first.
"""

from __future__ import annotations

from plugins.web.keyless.provider import KeylessWebProvider


def register(ctx) -> None:
    """Register the keyless provider with the plugin context."""
    ctx.register_web_search_provider(KeylessWebProvider())
