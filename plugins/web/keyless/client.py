"""Free public web search and page fetching — no API key.

Four services offer anonymous free tiers built for AI agents: Exa and Parallel
(hosted MCP endpoints), Firecrawl (its cloud API without an auth header) and
Keenable (public endpoints that take an app name). Each is rate-limited, so
requests rotate round-robin across them and move to the next one when a
service is busy or fails.

Privacy: no user identifiers are sent. Parallel gets a random per-process
``session_id`` (its rate limiting needs one); Keenable gets the app name.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

EXA_MCP_URL = "https://mcp.exa.ai/mcp"
PARALLEL_MCP_URL = "https://search.parallel.ai/mcp"
FIRECRAWL_API_URL = "https://api.firecrawl.dev"
KEENABLE_API_URL = "https://api.keenable.ai"
APP_NAME = "robo-agent"

SEARCH_TIMEOUT_SECS = 20.0
FETCH_TIMEOUT_SECS = 45.0
# Every service here caps a search at 20 results.
SEARCH_LIMIT_CAP = 20
# Stop trying further services for page reads after this long.
FETCH_BUDGET_SECS = 90.0

_SESSION_ID = uuid.uuid4().hex

RING: Tuple[str, ...] = ("exa", "parallel", "firecrawl", "keenable")
_ring_lock = threading.Lock()
_ring_cursor = int(_SESSION_ID, 16) % len(RING)


class KeylessError(RuntimeError):
    """A free-tier call failed: transport, HTTP status, rate limit or tool error."""


_RATE_LIMIT_MARKERS = (
    "rate limit", "rate-limit", "ratelimit", "too many requests", "429", "quota", "slow down",
)


def is_rate_limited(message: str) -> bool:
    return any(marker in (message or "").lower() for marker in _RATE_LIMIT_MARKERS)


# ─── HTTP / MCP plumbing ─────────────────────────────────────────────────────


def _body_text(response: httpx.Response) -> str:
    """Decode with the declared charset, else UTF-8.

    JSON-RPC and SSE bodies are UTF-8 by spec, but ``text/event-stream`` often
    carries no charset; guessing Latin-1 there garbles non-English results.
    """
    content_type = response.headers.get("content-type", "")
    match = re.search(r"charset=([\w.:-]+)", content_type, re.IGNORECASE)
    encoding = match.group(1) if match else "utf-8"
    try:
        return response.content.decode(encoding, errors="replace")
    except LookupError:
        return response.content.decode("utf-8", errors="replace")


def _request(method: str, url: str, *, timeout: float, **kwargs: Any) -> httpx.Response:
    headers = {"User-Agent": APP_NAME, **kwargs.pop("headers", {})}
    try:
        response = httpx.request(method, url, headers=headers, timeout=timeout, **kwargs)
    except httpx.HTTPError as exc:
        raise KeylessError(f"request failed: {type(exc).__name__}: {exc}") from exc
    if response.status_code >= 400:
        detail = _body_text(response).strip()[:300]
        raise KeylessError(f"HTTP {response.status_code}" + (f": {detail}" if detail else ""))
    return response


def _json(response: httpx.Response) -> Any:
    try:
        return json.loads(_body_text(response))
    except ValueError as exc:
        raise KeylessError(f"unexpected response: {exc}") from exc


def parse_mcp_body(body: str) -> str:
    """The first text item of an MCP ``tools/call`` result.

    Handles plain JSON bodies and SSE ``data:`` frames (split on CR, LF or CRLF
    only — ``str.splitlines`` also splits on U+2028 and friends, which occur
    inside real page text). JSON-RPC errors and ``isError`` results raise.
    """

    def _from_payload(payload: str) -> Optional[str]:
        payload = payload.strip()
        if not payload.startswith("{"):
            return None
        data = json.loads(payload)
        error = data.get("error")
        if error:
            raise KeylessError(str(error.get("message") if isinstance(error, dict) else error))
        result = data.get("result") or {}
        texts = [c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict)]
        if result.get("isError"):
            raise KeylessError(" ".join(t for t in texts if t) or "tool call failed")
        return next((str(t) for t in texts if t), "")

    stripped = body.strip()
    candidates = [stripped] if stripped.startswith("{") else []
    candidates += [line[len("data: "):] for line in re.split(r"\r\n|\r|\n", body) if line.startswith("data: ")]
    saw_envelope = False
    for candidate in candidates:
        try:
            text = _from_payload(candidate)
        except json.JSONDecodeError:
            continue
        if text:
            return text
        saw_envelope = saw_envelope or text == ""
    raise KeylessError("response contained no text" if saw_envelope else "unrecognized response")


def mcp_call(url: str, tool: str, arguments: Dict[str, Any], *, timeout: float) -> str:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    response = _request(
        "POST", url, timeout=timeout, json=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
    )
    return parse_mcp_body(_body_text(response))


def _hit(title: Any, url: Any, description: Any, position: int) -> Dict[str, Any]:
    return {"title": str(title or ""), "url": str(url or ""), "description": str(description or ""), "position": position}


def _page(url: str, title: Any, content: Any) -> Dict[str, Any]:
    text = str(content or "")
    return {"url": url, "title": str(title or ""), "content": text, "raw_content": text, "metadata": {"sourceURL": url}}


def _page_error(url: str, error: str) -> Dict[str, Any]:
    return {"url": url, "title": "", "content": "", "error": error}


# ─── Exa ─────────────────────────────────────────────────────────────────────

_EXA_LABELS = ("Title:", "URL:", "Highlights:", "Published:", "Author:", "Text:")


def parse_exa_results(text: str, limit: int) -> List[Dict[str, Any]]:
    """Exa's ``---``-separated ``Title:/URL:/Published:/Highlights:`` blocks."""
    hits: List[Dict[str, Any]] = []
    for block in text.split("\n---\n"):
        title = url = ""
        highlights: List[str] = []
        in_highlights = False
        for line in (raw.strip() for raw in block.splitlines()):
            if line.startswith("Title:"):
                title = line[len("Title:"):].strip()
            elif line.startswith("URL:"):
                url = line[len("URL:"):].strip()
            elif in_highlights and line and not line.startswith(_EXA_LABELS):
                highlights.append(line)
            if line.startswith(_EXA_LABELS):
                in_highlights = line.startswith(("Highlights:", "Text:"))
        if url:
            hits.append(_hit(title, url, " ".join(highlights), len(hits) + 1))
        if len(hits) >= limit:
            break
    return hits


def exa_search(query: str, limit: int) -> List[Dict[str, Any]]:
    text = mcp_call(EXA_MCP_URL, "web_search_exa", {"query": query, "numResults": limit}, timeout=SEARCH_TIMEOUT_SECS)
    return parse_exa_results(text, limit)


def exa_fetch(urls: List[str]) -> List[Dict[str, Any]]:
    pages = []
    for url in urls:
        try:
            text = mcp_call(EXA_MCP_URL, "web_fetch_exa", {"urls": [url]}, timeout=FETCH_TIMEOUT_SECS)
        except KeylessError as exc:
            pages.append(_page_error(url, str(exc)))
            continue
        titles = (
            line[2:].strip() if line.startswith("# ") else line[len("Title:"):].strip()
            for line in (raw.strip() for raw in text.splitlines())
            if line.startswith(("# ", "Title:"))
        )
        pages.append(_page(url, next(titles, ""), text))
    return pages


# ─── Parallel ────────────────────────────────────────────────────────────────


def parallel_search(query: str, limit: int) -> List[Dict[str, Any]]:
    text = mcp_call(
        PARALLEL_MCP_URL, "web_search",
        {"objective": query, "search_queries": [query], "session_id": _SESSION_ID},
        timeout=SEARCH_TIMEOUT_SECS,
    )
    try:
        results = json.loads(text).get("results") or []
    except (ValueError, AttributeError) as exc:
        raise KeylessError(f"unexpected response: {exc}") from exc
    return [
        _hit(r.get("title"), r.get("url"), " ".join(r.get("excerpts") or []), i + 1)
        for i, r in enumerate(results[:limit])
        if isinstance(r, dict)
    ]


def parallel_fetch(urls: List[str]) -> List[Dict[str, Any]]:
    try:
        text = mcp_call(
            PARALLEL_MCP_URL, "web_fetch",
            {"urls": list(urls), "objective": "Full page content", "session_id": _SESSION_ID},
            timeout=FETCH_TIMEOUT_SECS,
        )
        data = json.loads(text)
    except (KeylessError, ValueError) as exc:
        return [_page_error(url, str(exc)) for url in urls]
    by_url: Dict[str, Dict[str, Any]] = {}
    for r in data.get("results") or []:
        if isinstance(r, dict) and r.get("url"):
            content = r.get("full_content") or r.get("content") or "\n\n".join(r.get("excerpts") or [])
            by_url[r["url"]] = _page(r["url"], r.get("title"), content)
    for e in data.get("errors") or []:
        if isinstance(e, dict) and e.get("url"):
            by_url.setdefault(e["url"], _page_error(e["url"], str(e.get("content") or e.get("error_type") or "could not read the page")))
    return [by_url.get(url) or _page_error(url, "no content returned") for url in urls]


# ─── Firecrawl ───────────────────────────────────────────────────────────────


def firecrawl_search(query: str, limit: int) -> List[Dict[str, Any]]:
    from plugins.web.firecrawl.provider import _extract_web_search_results

    response = _request("POST", f"{FIRECRAWL_API_URL}/v2/search", timeout=SEARCH_TIMEOUT_SECS, json={"query": query, "limit": limit})
    rows = _extract_web_search_results(_json(response))
    return [
        _hit(r.get("title"), r.get("url"), r.get("description") or r.get("snippet"), i + 1)
        for i, r in enumerate(rows[:limit])
    ]


def firecrawl_fetch(urls: List[str]) -> List[Dict[str, Any]]:
    from plugins.web.firecrawl.provider import _extract_scrape_payload

    pages = []
    for url in urls:
        try:
            response = _request("POST", f"{FIRECRAWL_API_URL}/v2/scrape", timeout=FETCH_TIMEOUT_SECS, json={"url": url, "formats": ["markdown"]})
            payload = _extract_scrape_payload(_json(response)) or {}
        except KeylessError as exc:
            pages.append(_page_error(url, str(exc)))
            continue
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        content = payload.get("markdown") or payload.get("html") or ""
        pages.append(_page(url, metadata.get("title"), content) if content else _page_error(url, "no content returned"))
    return pages


# ─── Keenable ────────────────────────────────────────────────────────────────


def keenable_search(query: str, limit: int) -> List[Dict[str, Any]]:
    response = _request(
        "POST", f"{KEENABLE_API_URL}/v1/search/public", timeout=SEARCH_TIMEOUT_SECS,
        json={"query": query, "max_results": limit}, headers={"X-Keenable-Title": APP_NAME},
    )
    results = (_json(response) or {}).get("results") or []
    return [
        _hit(r.get("title"), r.get("url"), r.get("snippet") or r.get("description"), i + 1)
        for i, r in enumerate(results[:limit])
        if isinstance(r, dict)
    ]


def keenable_fetch(urls: List[str]) -> List[Dict[str, Any]]:
    pages = []
    for url in urls:
        try:
            response = _request(
                "GET", f"{KEENABLE_API_URL}/v1/fetch/public", timeout=FETCH_TIMEOUT_SECS,
                params={"url": url}, headers={"X-Keenable-Title": APP_NAME},
            )
            data = _json(response) or {}
        except KeylessError as exc:
            pages.append(_page_error(url, str(exc)))
            continue
        content = data.get("content") or ""
        pages.append(_page(url, data.get("title"), content) if content else _page_error(url, "no content returned"))
    return pages


# ─── Rotation with failover ──────────────────────────────────────────────────

# Looked up by name at call time so tests can patch the module functions.
_SEARCHERS: Dict[str, str] = {vendor: f"{vendor}_search" for vendor in RING}
_FETCHERS: Dict[str, str] = {vendor: f"{vendor}_fetch" for vendor in RING}

_LABELS = {"exa": "Exa", "parallel": "Parallel", "firecrawl": "Firecrawl", "keenable": "Keenable"}


def ring_order() -> List[str]:
    """This request's service order: round-robin start, then the rest in turn."""
    global _ring_cursor
    with _ring_lock:
        start = _ring_cursor
        _ring_cursor = (_ring_cursor + 1) % len(RING)
    return list(RING[start:] + RING[:start])


def search(query: str, limit: int = 5, *, interrupted: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    """Search, starting at the next service in the rotation and moving on
    when one fails, is rate-limited or finds nothing."""
    limit = min(max(1, int(limit)), SEARCH_LIMIT_CAP)
    failures: List[str] = []
    for vendor in ring_order():
        if interrupted():
            return {"success": False, "error": "Search interrupted"}
        try:
            hits = globals()[_SEARCHERS[vendor]](query, limit)
        except KeylessError as exc:
            failures.append(f"{_LABELS[vendor]}: {exc}")
            logger.info("Free search via %s failed, trying the next service: %s", vendor, exc)
            continue
        except Exception as exc:  # noqa: BLE001 — one service's bug never ends the search
            failures.append(f"{_LABELS[vendor]}: {type(exc).__name__}: {exc}")
            logger.warning("Free search via %s raised: %s", vendor, exc)
            continue
        hits = [h for h in hits if h.get("url")]
        if hits:
            logger.info("Free search via %s: %d results for %r", vendor, len(hits), query)
            return {"success": True, "data": {"web": hits}}
        failures.append(f"{_LABELS[vendor]}: no results")
    errors = [f for f in failures if not f.endswith("no results")]
    if not errors:
        reason = "The free search services found nothing"
    elif all(is_rate_limited(f) for f in errors):
        reason = "All free search services are busy right now"
    else:
        reason = "The free search services could not be reached"
    return {"success": False, "error": f"{reason} ({'; '.join(failures)}). Try again in a minute, or add a search API key with `robo tools`."}


def fetch(urls: List[str], *, interrupted: Callable[[], bool] = lambda: False) -> List[Dict[str, Any]]:
    """Read pages through the services in rotation. A page one service cannot
    read is offered to the next, until every page is read, every service was
    tried, or ``FETCH_BUDGET_SECS`` has passed."""
    results: Dict[str, Dict[str, Any]] = {url: _page_error(url, "not tried") for url in urls}
    pending = list(dict.fromkeys(urls))
    deadline = time.monotonic() + FETCH_BUDGET_SECS
    for vendor in ring_order():
        if not pending or interrupted() or time.monotonic() > deadline:
            break
        try:
            pages = globals()[_FETCHERS[vendor]](pending)
        except Exception as exc:  # noqa: BLE001 — try the next service
            pages = [_page_error(url, f"{type(exc).__name__}: {exc}") for url in pending]
        for url, page in zip(pending, pages):
            if page.get("error") or not str(page.get("content") or "").strip():
                results[url] = _page_error(url, f"{_LABELS[vendor]}: {page.get('error') or 'empty page'}")
            else:
                page["url"] = url
                page.setdefault("metadata", {})["reader"] = vendor
                results[url] = page
        pending = [url for url in pending if results[url].get("error")]
    return [results[url] for url in urls]
