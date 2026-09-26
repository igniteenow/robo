"""Free no-key web search and page reading (plugins/web/keyless).

Every vendor call is answered by a fake ``httpx.request`` — no network.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from plugins.web.keyless import client
from plugins.web.keyless.provider import KeylessWebProvider


def _response(status: int = 200, *, body: str = "", json_body=None, content_type: str = "application/json", raw: bytes = None):
    if json_body is not None:
        body = json.dumps(json_body)
    content = raw if raw is not None else body.encode("utf-8")
    return httpx.Response(status, content=content, headers={"content-type": content_type})


def _mcp_text(text: str, *, sse: bool = False) -> httpx.Response:
    envelope = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}}, ensure_ascii=False)
    if sse:
        return _response(raw=f"event: message\ndata: {envelope}\n\n".encode("utf-8"), content_type="text/event-stream")
    return _response(body=envelope)


@pytest.fixture
def served(monkeypatch):
    """Route ``httpx.request`` in the client to ``routes[(method, url)]``."""
    routes = {}
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        route = routes.get((method, url))
        if route is None:
            raise httpx.ConnectError(f"no route for {method} {url}")
        return route(kwargs) if callable(route) else route

    monkeypatch.setattr(client.httpx, "request", fake_request)
    return routes, calls


@pytest.fixture
def ring_from_start(monkeypatch):
    """Make the rotation start at the first service for this test."""
    monkeypatch.setattr(client, "_ring_cursor", 0)


class TestMcpBody:
    def test_sse_and_plain_json(self):
        envelope = json.dumps({"result": {"content": [{"type": "text", "text": "hello"}]}})
        assert client.parse_mcp_body(f"event: message\ndata: {envelope}\n\n") == "hello"
        assert client.parse_mcp_body(envelope) == "hello"

    @pytest.mark.parametrize("terminator", ["\r", "\r\n"])
    def test_sse_frames_split_on_every_line_terminator(self, terminator):
        envelope = json.dumps({"result": {"content": [{"type": "text", "text": "ok"}]}})
        assert client.parse_mcp_body(f"event: message{terminator}data: {envelope}{terminator}") == "ok"

    def test_errors_raise(self):
        with pytest.raises(client.KeylessError, match="rate limit"):
            client.parse_mcp_body(json.dumps({"error": {"code": -32000, "message": "rate limit"}}))
        with pytest.raises(client.KeylessError, match="boom"):
            client.parse_mcp_body(json.dumps({"result": {"isError": True, "content": [{"type": "text", "text": "boom"}]}}))
        with pytest.raises(client.KeylessError, match="no text"):
            client.parse_mcp_body(json.dumps({"result": {"content": []}}))
        with pytest.raises(client.KeylessError, match="unrecognized"):
            client.parse_mcp_body("<html>nope</html>")

    def test_charsetless_event_stream_is_utf8(self, served):
        routes, _ = served
        title = "光伏发电站组件清洗与性能监测规范"
        routes[("POST", client.EXA_MCP_URL)] = _mcp_text(f"Title: {title}\nURL: https://x.example", sse=True)

        assert client.exa_search(title, 5)[0]["title"] == title


class TestServices:
    def test_exa_search_parses_blocks(self, served):
        routes, calls = served
        routes[("POST", client.EXA_MCP_URL)] = _mcp_text(
            "Title: First\nURL: https://a.example\nPublished: N/A\nHighlights:\nsome highlight\nmore\n"
            "\n---\n"
            "Title: Second\nURL: https://b.example\nHighlights:\nother\n",
            sse=True,
        )

        hits = client.exa_search("cameras", 5)

        assert hits == [
            {"title": "First", "url": "https://a.example", "description": "some highlight more", "position": 1},
            {"title": "Second", "url": "https://b.example", "description": "other", "position": 2},
        ]
        payload = calls[0][2]["json"]
        assert payload["params"] == {"name": "web_search_exa", "arguments": {"query": "cameras", "numResults": 5}}
        assert calls[0][2]["headers"]["User-Agent"] == client.APP_NAME

    def test_parallel_search_uses_excerpts_and_sends_no_identity(self, served):
        routes, calls = served
        routes[("POST", client.PARALLEL_MCP_URL)] = _mcp_text(json.dumps({"results": [
            {"url": "https://a", "title": "A", "excerpts": ["x", "y"]},
            {"url": "https://b", "title": "B", "excerpts": []},
        ]}))

        hits = client.parallel_search("q", 5)

        assert hits[0] == {"title": "A", "url": "https://a", "description": "x y", "position": 1}
        arguments = calls[0][2]["json"]["params"]["arguments"]
        assert set(arguments) == {"objective", "search_queries", "session_id"}

    def test_firecrawl_search_without_an_auth_header(self, served):
        routes, calls = served
        routes[("POST", f"{client.FIRECRAWL_API_URL}/v2/search")] = _response(json_body={
            "success": True, "data": {"web": [{"url": "https://f", "title": "F", "description": "d"}]},
        })

        assert client.firecrawl_search("q", 3) == [{"title": "F", "url": "https://f", "description": "d", "position": 1}]
        assert "Authorization" not in calls[0][2]["headers"]

    def test_keenable_search_names_the_app(self, served):
        routes, calls = served
        routes[("POST", f"{client.KEENABLE_API_URL}/v1/search/public")] = _response(json_body={
            "results": [{"url": "https://k", "title": "K", "snippet": "s"}],
        })

        assert client.keenable_search("q", 3)[0]["url"] == "https://k"
        assert calls[0][2]["headers"]["X-Keenable-Title"] == client.APP_NAME

    def test_http_errors_become_keyless_errors(self, served):
        routes, _ = served
        routes[("POST", client.EXA_MCP_URL)] = _response(429, body="Too Many Requests", content_type="text/plain")

        with pytest.raises(client.KeylessError, match="HTTP 429"):
            client.exa_search("q", 5)

    def test_parallel_fetch_reports_pages_it_dropped(self, served):
        routes, _ = served
        routes[("POST", client.PARALLEL_MCP_URL)] = _mcp_text(json.dumps({
            "results": [{"url": "https://a", "title": "A", "full_content": "page a"}],
        }))

        pages = client.parallel_fetch(["https://a", "https://gone"])

        assert pages[0]["content"] == "page a"
        assert pages[1]["url"] == "https://gone" and "no content" in pages[1]["error"]


class TestRotation:
    def _vendors(self, monkeypatch, outcomes):
        """Replace each service's search with a scripted outcome."""
        tried = []
        for vendor, outcome in outcomes.items():
            def fake(query, limit, _vendor=vendor, _outcome=outcome):
                tried.append(_vendor)
                if isinstance(_outcome, Exception):
                    raise _outcome
                return _outcome
            monkeypatch.setattr(client, f"{vendor}_search", fake)
        return tried

    def test_consecutive_searches_start_at_different_services(self, monkeypatch, ring_from_start):
        hit = [{"title": "T", "url": "https://t", "description": "", "position": 1}]
        tried = self._vendors(monkeypatch, {v: hit for v in client.RING})

        for _ in client.RING:
            client.search("q")

        assert tried == list(client.RING)

    def test_a_busy_service_hands_over_to_the_next(self, monkeypatch, ring_from_start):
        hit = [{"title": "T", "url": "https://p", "description": "", "position": 1}]
        tried = self._vendors(monkeypatch, {
            "exa": client.KeylessError("HTTP 429: rate limit"),
            "parallel": hit,
            "firecrawl": hit,
            "keenable": hit,
        })

        result = client.search("q")

        assert result == {"success": True, "data": {"web": hit}}
        assert tried == ["exa", "parallel"]

    def test_no_results_also_moves_on(self, monkeypatch, ring_from_start):
        hit = [{"title": "T", "url": "https://p", "description": "", "position": 1}]
        tried = self._vendors(monkeypatch, {"exa": [], "parallel": hit, "firecrawl": hit, "keenable": hit})

        assert client.search("q")["success"] is True
        assert tried == ["exa", "parallel"]

    def test_all_busy_says_so_and_how_to_fix_it(self, monkeypatch, ring_from_start):
        self._vendors(monkeypatch, {v: client.KeylessError("HTTP 429") for v in client.RING})

        result = client.search("q")

        assert result["success"] is False
        assert result["error"].startswith("All free search services are busy right now")
        assert "robo tools" in result["error"]

    def test_nothing_found_anywhere(self, monkeypatch, ring_from_start):
        self._vendors(monkeypatch, {v: [] for v in client.RING})

        assert client.search("q")["error"].startswith("The free search services found nothing")

    def test_limit_is_capped(self, monkeypatch, ring_from_start):
        seen = []
        monkeypatch.setattr(client, "exa_search", lambda q, limit: seen.append(limit) or [{"url": "https://x"}])

        client.search("q", limit=100)

        assert seen == [client.SEARCH_LIMIT_CAP]

    def test_fetch_offers_unread_pages_to_the_next_service(self, monkeypatch, ring_from_start):
        asked = []

        def exa(urls):
            asked.append(("exa", list(urls)))
            return [client._page(u, "A", "page a") if u == "https://a" else client._page_error(u, "HTTP 403") for u in urls]

        def parallel(urls):
            asked.append(("parallel", list(urls)))
            return [client._page(u, "B", "page b") for u in urls]

        monkeypatch.setattr(client, "exa_fetch", exa)
        monkeypatch.setattr(client, "parallel_fetch", parallel)

        pages = client.fetch(["https://a", "https://b"])

        assert [p["content"] for p in pages] == ["page a", "page b"]
        assert asked == [("exa", ["https://a", "https://b"]), ("parallel", ["https://b"])]
        assert pages[1]["metadata"]["reader"] == "parallel"

    def test_fetch_gives_up_after_its_time_budget(self, monkeypatch, ring_from_start):
        monkeypatch.setattr(client, "FETCH_BUDGET_SECS", -1)

        [page] = client.fetch(["https://a"])

        assert page["error"] == "not tried"


class TestProviderExtract:
    def _reader(self, monkeypatch, results):
        async def fake_read_pages(urls):
            return [dict(r) for r in results]

        monkeypatch.setattr("tools.web_reader.read_pages", fake_read_pages)

    def _hosted(self, monkeypatch, pages):
        asked = []

        def fake_fetch(urls, **_kw):
            asked.extend(urls)
            return [pages[u] for u in urls]

        monkeypatch.setattr(client, "fetch", fake_fetch)
        return asked

    def test_pages_the_reader_read_never_leave_robo(self, monkeypatch):
        self._reader(monkeypatch, [{"url": "https://a", "title": "A", "content": "full page " * 50}])
        asked = self._hosted(monkeypatch, {})

        [page] = asyncio.run(KeylessWebProvider().extract(["https://a"]))

        assert asked == []
        assert page["title"] == "A"

    def test_a_blocked_page_is_read_by_a_hosted_reader(self, monkeypatch):
        self._reader(monkeypatch, [{"url": "https://shop", "title": "", "content": "", "error": "bot check", "retry_elsewhere": True}])
        self._hosted(monkeypatch, {"https://shop": client._page("https://shop", "Shop", "price 99")})

        [page] = asyncio.run(KeylessWebProvider().extract(["https://shop"]))

        assert page["content"] == "price 99"
        assert "error" not in page

    def test_when_everyone_fails_both_reasons_are_kept(self, monkeypatch):
        self._reader(monkeypatch, [{"url": "https://shop", "title": "", "content": "", "error": "bot check.", "retry_elsewhere": True}])
        self._hosted(monkeypatch, {"https://shop": client._page_error("https://shop", "Exa: HTTP 403")})

        [page] = asyncio.run(KeylessWebProvider().extract(["https://shop"]))

        assert page["error"].startswith("bot check.")
        assert "Exa: HTTP 403" in page["error"]
        assert "retry_elsewhere" not in page

    def test_policy_blocks_are_never_sent_elsewhere(self, monkeypatch):
        self._reader(monkeypatch, [{"url": "https://x", "title": "", "content": "", "error": "Blocked by website policy"}])
        asked = self._hosted(monkeypatch, {})

        asyncio.run(KeylessWebProvider().extract(["https://x"]))

        assert asked == []

    def test_a_thin_page_is_replaced_only_by_a_fuller_one(self, monkeypatch):
        thin = {"url": "https://app", "title": "App", "content": "Loading", "retry_elsewhere": True}
        self._reader(monkeypatch, [thin])
        self._hosted(monkeypatch, {"https://app": client._page("https://app", "", "The rendered app with real text")})

        [page] = asyncio.run(KeylessWebProvider().extract(["https://app"]))

        assert page["content"] == "The rendered app with real text"
        assert page["title"] == "App"


class TestResolution:
    @pytest.fixture(autouse=True)
    def _registry(self, monkeypatch):
        from agent import web_search_registry
        from tests.tools.conftest import register_all_web_providers
        from tools import web_tools

        for key in ("TAVILY_API_KEY", "EXA_API_KEY", "PARALLEL_API_KEY", "FIRECRAWL_API_KEY",
                    "FIRECRAWL_API_URL", "SEARXNG_URL", "BRAVE_SEARCH_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        register_all_web_providers()
        web_search_registry.register_provider(KeylessWebProvider())
        self.config = {}
        monkeypatch.setattr(web_tools, "_load_web_config", lambda: self.config)
        monkeypatch.setattr(web_tools, "_ddgs_package_importable", lambda: True)
        monkeypatch.setattr(web_tools, "_ensure_web_plugins_loaded", lambda: None)
        monkeypatch.setattr(
            web_search_registry, "_read_config_key",
            lambda *path: self.config.get(path[-1]) if path[0] == "web" else None,
        )
        yield
        web_search_registry._reset_for_tests()

    def test_no_key_uses_the_free_tier_before_duckduckgo(self):
        from agent.web_search_registry import get_active_extract_provider, get_active_search_provider
        from tools import web_tools

        assert web_tools._get_backend() == "keyless"
        assert get_active_search_provider().name == "keyless"
        assert get_active_extract_provider().name == "keyless"
        assert web_tools.check_web_api_key() is True

    def test_a_key_always_wins(self, monkeypatch):
        from tools import web_tools

        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

        assert web_tools._get_backend() == "tavily"

    def test_duckduckgo_when_the_free_tier_is_switched_off(self):
        from tools import web_tools

        self.config["keyless_fallback"] = False

        assert web_tools._get_backend() == "ddgs"

    def test_an_explicit_duckduckgo_choice_is_kept_for_search(self):
        from agent.web_search_registry import get_active_extract_provider
        from tools import web_tools

        self.config["backend"] = "ddgs"

        assert web_tools._get_search_backend() == "ddgs"
        # DuckDuckGo cannot read pages, so page reading still uses the free tier.
        assert get_active_extract_provider().name == "keyless"

    def test_web_search_end_to_end(self, monkeypatch, ring_from_start):
        from tools import web_tools

        monkeypatch.setattr(client, "exa_search", lambda q, limit: [
            {"title": "Arlo", "url": "https://arlo.example", "description": "camera", "position": 1},
        ])
        monkeypatch.setattr("tools.interrupt.is_interrupted", lambda: False)

        result = json.loads(web_tools.web_search_tool("arlo camera", limit=3))

        assert result["success"] is True
        assert result["data"]["web"][0]["url"] == "https://arlo.example"
