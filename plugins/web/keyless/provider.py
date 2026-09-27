"""Free web search and page reading — the no-key default.

Search rotates across the anonymous free tiers of Exa, Parallel, Firecrawl
and Keenable (:mod:`plugins.web.keyless.client`), then tries DuckDuckGo when
all four fail and the DuckDuckGo provider is available. Page reading starts with
Robo's own reader (:mod:`tools.web_reader`, a direct fetch that sends the URL
nowhere else) and hands only the pages it could not read — bot checks,
JavaScript-only pages, refused requests — to the free hosted readers.

Picked automatically when no search API key is set up; a configured key or an
explicit ``web.backend`` always wins. Turn it off with
``web.keyless_fallback: false`` in config.yaml.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


def keyless_enabled() -> bool:
    """``web.keyless_fallback`` from config.yaml; on unless set to false."""
    try:
        from tools.web_tools import _load_web_config

        value = _load_web_config().get("keyless_fallback", True)
    except Exception:  # noqa: BLE001 — config layer optional; default on
        return True
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return value is not False


def _interrupted() -> bool:
    try:
        from tools.interrupt import is_interrupted

        return is_interrupted()
    except Exception:  # noqa: BLE001
        return False


def _search_duckduckgo_instead(query: str, limit: int, failed: Dict[str, Any]) -> Dict[str, Any]:
    """Last resort once every free service has failed: DuckDuckGo, when its
    provider is installed (or can install itself). Without this a search
    ended in an error even though DuckDuckGo was right there."""
    try:
        from agent.web_search_registry import get_provider

        duckduckgo = get_provider("ddgs")
        available = duckduckgo is not None and duckduckgo.is_available()
    except Exception as exc:  # noqa: BLE001 — a broken fallback must not hide the real error
        logger.debug("DuckDuckGo fallback unavailable: %s", exc)
        return failed
    if not available:
        return failed

    logger.info("All free search services failed; trying DuckDuckGo for %r", query)
    try:
        fallback = duckduckgo.search(query, limit)
    except Exception as exc:  # noqa: BLE001
        fallback = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    if fallback.get("success") and (fallback.get("data") or {}).get("web"):
        return fallback
    reason = fallback.get("error") or "it found nothing either"
    return {"success": False, "error": f"{failed.get('error', 'Search failed.')} DuckDuckGo was tried too: {reason}"}


class KeylessWebProvider(WebSearchProvider):
    """Search and extract with no API key."""

    @property
    def name(self) -> str:
        return "keyless"

    @property
    def display_name(self) -> str:
        return "Free web search (no key)"

    def is_available(self) -> bool:
        return keyless_enabled()

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        from plugins.web.keyless import client

        result = client.search(query, limit, interrupted=_interrupted)
        if result.get("success") or _interrupted():
            return result
        return _search_duckduckgo_instead(query, limit, result)

    async def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        from plugins.web.keyless import client
        from tools.web_reader import RETRY_ELSEWHERE, read_pages

        results = await read_pages(urls)
        retry = [i for i, result in enumerate(results) if result.pop(RETRY_ELSEWHERE, False)]
        if not retry:
            return results

        logger.info("Handing %d page(s) the built-in reader could not read to the free hosted readers", len(retry))
        hosted = await asyncio.to_thread(client.fetch, [results[i]["url"] for i in retry])
        for i, page in zip(retry, hosted):
            ours = results[i]
            if page.get("error"):
                if ours.get("error"):
                    ours["error"] = f"{ours['error']} The free hosted readers could not open it either ({page['error']})."
                continue
            # A thin page we did read is replaced only by a fuller one.
            if ours.get("error") or len(page.get("content", "")) > len(ours.get("content", "")):
                if not page.get("title"):
                    page["title"] = ours.get("title", "")
                results[i] = page
        return results

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Free web search (no key)",
            "badge": "free · no key",
            "tag": "Rotates across the free tiers of Exa, Parallel, Firecrawl and Keenable, then DuckDuckGo; Robo reads pages itself first",
            "env_vars": [],
        }
