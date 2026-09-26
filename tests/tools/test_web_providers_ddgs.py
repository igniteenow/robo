"""Tests for the DuckDuckGo (ddgs) web search provider.

Covers:
- DDGSWebSearchProvider.is_available() — reflects package importability
- DDGSWebSearchProvider.search() — happy path, missing package, runtime error
- Result normalization (title, url, description, position)
- Process-isolated timeout / interrupt / GIL-hold / reap (#68096)
- _is_backend_available("ddgs") / _get_backend() integration
- web_extract falls back to the built-in page reader when ddgs is active
- Parallel searches share a few slots; repeat searches reuse results
"""
from __future__ import annotations

import json
import sys
import time
import types

import pytest

from tests.tools.conftest import register_all_web_providers


def _install_fake_ddgs(monkeypatch, *, text_results=None, text_raises=None, text_sleep=None):
    """Install a stub ``ddgs`` module in sys.modules for the duration of a test.

    ``text_results``: iterable of dicts to yield from DDGS().text(...).
    ``text_raises``: if set, DDGS().text raises this exception instead.
    ``text_sleep``: if set, DDGS().text blocks for this many seconds before
        yielding — simulates a hung/slow search for the timeout test.
    """
    import time as _time

    fake = types.ModuleType("ddgs")

    class _FakeDDGS:
        def __init__(self, **kwargs):
            # Accept timeout= (and any other constructor kwargs) — the provider
            # now passes DDGS(timeout=10).
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_a):
            return False
        def text(self, query, max_results=5):
            if text_sleep is not None:
                _time.sleep(text_sleep)
            if text_raises is not None:
                raise text_raises
            for hit in (text_results or []):
                yield hit

    fake.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake)
    return fake


def _force_inprocess_search(monkeypatch, prov):
    """Route bounded search through the in-process helper.

    Happy-path unit tests install a fake ``ddgs`` in the parent interpreter;
    spawn workers would not see that fake. Isolation behavior is covered by
    dedicated process tests below.
    """
    monkeypatch.setattr(
        prov,
        "_run_ddgs_search_bounded",
        lambda query, safe_limit: prov._run_ddgs_search(query, safe_limit),
        raising=True,
    )


# ---------------------------------------------------------------------------
# DDGSWebSearchProvider unit tests
# ---------------------------------------------------------------------------


class TestDDGSProviderIsConfigured:
    def test_configured_when_package_importable(self, monkeypatch):
        _install_fake_ddgs(monkeypatch)
        # Drop any cached ``plugins.web.ddgs.provider`` so is_configured re-imports ddgs fresh
        monkeypatch.delitem(sys.modules, "plugins.web.ddgs.provider", raising=False)
        from plugins.web.ddgs.provider import DDGSWebSearchProvider
        assert DDGSWebSearchProvider().is_available() is True


    def test_implements_web_search_provider(self):
        from agent.web_search_provider import WebSearchProvider
        from plugins.web.ddgs.provider import DDGSWebSearchProvider
        assert issubclass(DDGSWebSearchProvider, WebSearchProvider)


class TestDDGSProviderSearch:
    def test_happy_path_normalizes_results(self, monkeypatch):
        _install_fake_ddgs(monkeypatch, text_results=[
            {"title": "A", "href": "https://a.example.com", "body": "desc A"},
            {"title": "B", "href": "https://b.example.com", "body": "desc B"},
            {"title": "C", "href": "https://c.example.com", "body": "desc C"},
        ])
        import plugins.web.ddgs.provider as prov
        _force_inprocess_search(monkeypatch, prov)

        result = prov.DDGSWebSearchProvider().search("q", limit=5)

        assert result["success"] is True
        web = result["data"]["web"]
        assert len(web) == 3
        assert web[0] == {"title": "A", "url": "https://a.example.com", "description": "desc A", "position": 1}
        assert web[2]["position"] == 3


    def test_empty_results(self, monkeypatch):
        _install_fake_ddgs(monkeypatch, text_results=[])
        import plugins.web.ddgs.provider as prov
        _force_inprocess_search(monkeypatch, prov)

        result = prov.DDGSWebSearchProvider().search("nothing", limit=5)
        assert result["success"] is True
        assert result["data"]["web"] == []

    @pytest.mark.live_system_guard_bypass
    def test_hung_search_times_out_and_returns_failure(self, monkeypatch):
        """#36776 / #68096: a hung worker must be bounded by the wall-clock
        timeout and reaped — even when the child never returns to Python."""
        _install_fake_ddgs(monkeypatch)
        import plugins.web.ddgs.provider as prov

        monkeypatch.setattr(prov, "_test_hook", "sleep", raising=True)
        monkeypatch.setattr(prov, "_SEARCH_TIMEOUT_SECS", 0.4, raising=True)
        monkeypatch.setattr(prov, "_TERMINATE_GRACE_SECS", 0.5, raising=True)
        monkeypatch.setattr("tools.interrupt.is_interrupted", lambda: False)

        start = time.monotonic()
        result = prov.DDGSWebSearchProvider().search("hangs forever", limit=5)
        elapsed = time.monotonic() - start

        assert result["success"] is False
        assert "timed out" in result["error"].lower()
        assert elapsed < 5.0, f"search did not return promptly ({elapsed:.1f}s)"
        _assert_worker_reaped(prov)

    def test_fast_search_not_affected_by_timeout_wrapper(self, monkeypatch):
        """Happy-path guard: the timeout wrapper must not break a normal,
        fast search — results flow through unchanged."""
        _install_fake_ddgs(
            monkeypatch,
            text_results=[{"title": "T", "href": "https://e.com", "body": "B"}],
        )
        import plugins.web.ddgs.provider as prov
        _force_inprocess_search(monkeypatch, prov)

        result = prov.DDGSWebSearchProvider().search("q", limit=5)
        assert result["success"] is True
        assert result["data"]["web"][0]["url"] == "https://e.com"
        assert result["data"]["web"][0]["title"] == "T"


# ---------------------------------------------------------------------------
# Process isolation (#68096)
# ---------------------------------------------------------------------------


def _assert_worker_reaped(prov) -> None:
    """Assert the last DDGS worker process has exited."""
    proc = prov._last_worker_proc
    assert proc is not None, "expected a DDGS worker process to have been started"
    assert proc.poll() is not None, (
        f"DDGS worker still alive (pid={proc.pid}, returncode={proc.returncode})"
    )


@pytest.mark.live_system_guard_bypass
class TestDDGSProcessIsolation:
    def test_gil_holding_worker_times_out_and_is_reaped(self, monkeypatch):
        """#68096: parent deadline still fires when the child holds its GIL."""
        _install_fake_ddgs(monkeypatch)
        import plugins.web.ddgs.provider as prov

        monkeypatch.setattr(prov, "_test_hook", "gil", raising=True)
        monkeypatch.setattr(prov, "_SEARCH_TIMEOUT_SECS", 0.5, raising=True)
        monkeypatch.setattr(prov, "_TERMINATE_GRACE_SECS", 0.5, raising=True)
        monkeypatch.setattr("tools.interrupt.is_interrupted", lambda: False)

        start = time.monotonic()
        result = prov.DDGSWebSearchProvider().search("gil hold", limit=5)
        elapsed = time.monotonic() - start

        assert result["success"] is False
        assert "timed out" in result["error"].lower()
        assert elapsed < 5.0, f"GIL-hold search did not time out promptly ({elapsed:.1f}s)"
        _assert_worker_reaped(prov)

    def test_interrupt_terminates_worker_promptly(self, monkeypatch):
        """TUI/gateway interrupt must kill the DDGS child before the deadline."""
        _install_fake_ddgs(monkeypatch)
        import plugins.web.ddgs.provider as prov

        # Flip interrupt after the first poll so the wait loop observes it.
        calls = {"n": 0}

        def _interrupt_after_poll():
            calls["n"] += 1
            return calls["n"] >= 2

        monkeypatch.setattr(prov, "_test_hook", "sleep", raising=True)
        monkeypatch.setattr(prov, "_SEARCH_TIMEOUT_SECS", 30, raising=True)
        monkeypatch.setattr(prov, "_TERMINATE_GRACE_SECS", 0.5, raising=True)
        monkeypatch.setattr("tools.interrupt.is_interrupted", _interrupt_after_poll)

        start = time.monotonic()
        result = prov.DDGSWebSearchProvider().search("interrupt me", limit=5)
        elapsed = time.monotonic() - start

        assert result["success"] is False
        assert "interrupted" in result["error"].lower()
        assert elapsed < 5.0, f"interrupt did not return promptly ({elapsed:.1f}s)"
        _assert_worker_reaped(prov)


    def test_no_orphan_after_successful_search(self, monkeypatch):
        _install_fake_ddgs(monkeypatch)
        import plugins.web.ddgs.provider as prov

        monkeypatch.setattr(prov, "_test_hook", "empty", raising=True)
        monkeypatch.setattr("tools.interrupt.is_interrupted", lambda: False)

        result = prov.DDGSWebSearchProvider().search("q", limit=5)
        assert result["success"] is True
        _assert_worker_reaped(prov)

# ---------------------------------------------------------------------------
# Integration: _is_backend_available / _get_backend / check_web_api_key
# ---------------------------------------------------------------------------


class TestDDGSBackendWiring:
    def test_is_backend_available_true_when_package_importable(self, monkeypatch):
        from tools import web_tools
        monkeypatch.setattr(web_tools, "_ddgs_package_importable", lambda: True)
        assert web_tools._is_backend_available("ddgs") is True


    def test_auto_detect_picks_ddgs_as_last_resort(self, monkeypatch):
        from tools import web_tools
        # With no key the free tier comes first; DuckDuckGo is the last resort
        # once it is switched off.
        monkeypatch.setattr(web_tools, "_load_web_config", lambda: {"keyless_fallback": False})
        for key in ("FIRECRAWL_API_KEY", "FIRECRAWL_API_URL", "PARALLEL_API_KEY",
                    "TAVILY_API_KEY", "EXA_API_KEY", "SEARXNG_URL", "BRAVE_SEARCH_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(web_tools, "_is_tool_gateway_ready", lambda: False)
        monkeypatch.setattr(web_tools, "_ddgs_package_importable", lambda: True)
        assert web_tools._get_backend() == "ddgs"

    def test_check_web_api_key_true_when_ddgs_configured(self, monkeypatch):
        from tools import web_tools
        monkeypatch.setattr(web_tools, "_load_web_config", lambda: {"backend": "ddgs"})
        monkeypatch.setattr(web_tools, "_ddgs_package_importable", lambda: True)
        assert web_tools.check_web_api_key() is True


# ---------------------------------------------------------------------------
# ddgs is search-only: web_extract reads pages with the built-in reader
# ---------------------------------------------------------------------------


def _extract_with(monkeypatch, config):
    """Run web_extract for one URL under ``config`` with the network stubbed."""
    import asyncio
    from tools import web_tools

    read = []

    async def fake_read_pages(urls):
        read.extend(urls)
        return [
            {"url": u, "title": "Page", "content": "page text", "raw_content": "page text", "metadata": {}}
            for u in urls
        ]

    async def _allow_ssrf(_url: str) -> bool:
        return True

    monkeypatch.setattr(web_tools, "_load_web_config", lambda: config)
    monkeypatch.setattr(web_tools, "_ddgs_package_importable", lambda: True)
    monkeypatch.setattr(web_tools, "_is_tool_gateway_ready", lambda: False)
    monkeypatch.setattr(web_tools, "async_is_safe_url", _allow_ssrf)
    monkeypatch.setattr("tools.web_reader.read_pages", fake_read_pages)
    monkeypatch.setattr("tools.interrupt.is_interrupted", lambda: False, raising=False)
    monkeypatch.setattr(
        "agent.web_search_registry._read_config_key",
        lambda *path: config.get(path[-1]) if path[0] == "web" else None,
    )

    result = json.loads(asyncio.run(web_tools.web_extract_tool(["https://example.com"])))
    return result, read


class TestDDGSExtractFallsBackToBuiltInReader:
    _register_providers = staticmethod(register_all_web_providers)

    @pytest.fixture(autouse=True)
    def _populate_web_registry(self):
        self._register_providers()
        yield
        from agent.web_search_registry import _reset_for_tests
        _reset_for_tests()

    def test_web_extract_reads_the_page_itself(self, monkeypatch):
        result, read = _extract_with(monkeypatch, {"backend": "ddgs"})

        assert read == ["https://example.com"]
        assert result["results"][0]["content"] == "page text"
        assert result["results"][0]["error"] is None

    def test_no_web_config_at_all_also_reads_the_page(self, monkeypatch):
        result, read = _extract_with(monkeypatch, {})

        assert read == ["https://example.com"]
        assert result["results"][0]["content"] == "page text"

    def test_ddgs_named_as_the_extract_backend_is_still_an_error(self, monkeypatch):
        result, read = _extract_with(monkeypatch, {"extract_backend": "ddgs"})

        assert read == []
        assert result["success"] is False
        assert "search-only" in result["error"].lower()
        assert "built-in page reader" in result["error"]


# ---------------------------------------------------------------------------
# Keyless default: ddgs installs itself on the first search
# ---------------------------------------------------------------------------


class TestDDGSInstallsOnFirstUse:
    def test_available_before_install_when_it_can_install_itself(self, monkeypatch):
        import plugins.web.ddgs.provider as prov

        monkeypatch.setattr(prov, "_ddgs_importable", lambda: False)
        monkeypatch.setattr("tools.lazy_deps.can_lazy_install", lambda feature: feature == "search.ddgs")
        assert prov.DDGSWebSearchProvider().is_available() is True

    def test_not_available_when_missing_and_lazy_installs_are_off(self, monkeypatch):
        import plugins.web.ddgs.provider as prov

        monkeypatch.setattr(prov, "_ddgs_importable", lambda: False)
        # tests/conftest.py seals lazy installs for the whole suite.
        assert prov.DDGSWebSearchProvider().is_available() is False

    def test_first_search_installs_the_pinned_package_without_prompting(self, monkeypatch):
        _install_fake_ddgs(monkeypatch, text_results=[
            {"title": "A", "href": "https://a.example.com", "body": "desc A"},
        ])
        import plugins.web.ddgs.provider as prov
        _force_inprocess_search(monkeypatch, prov)

        installed = {"done": False}
        calls = []

        def fake_ensure(feature, *, prompt=True):
            calls.append((feature, prompt))
            installed["done"] = True

        monkeypatch.setattr(prov, "_ddgs_importable", lambda: installed["done"])
        monkeypatch.setattr("tools.lazy_deps.ensure", fake_ensure)

        result = prov.DDGSWebSearchProvider().search("q", limit=5)

        assert calls == [("search.ddgs", False)]
        assert result["success"] is True
        assert result["data"]["web"][0]["url"] == "https://a.example.com"

    def test_search_explains_when_it_cannot_install(self, monkeypatch):
        import plugins.web.ddgs.provider as prov
        from tools.lazy_deps import FeatureUnavailable

        def refuse(feature, *, prompt=True):
            raise FeatureUnavailable(feature, ("ddgs==9.16.0",), "lazy installs disabled")

        monkeypatch.setattr(prov, "_ddgs_importable", lambda: False)
        monkeypatch.setattr("tools.lazy_deps.ensure", refuse)

        result = prov.DDGSWebSearchProvider().search("q", limit=5)

        assert result["success"] is False
        assert "could not be installed automatically" in result["error"]
        assert "lazy installs disabled" in result["error"]


# ---------------------------------------------------------------------------
# Parallel searches: one at a time, quick failures retried, repeats reused
# ---------------------------------------------------------------------------


@pytest.fixture
def no_pauses(monkeypatch):
    import plugins.web.ddgs.provider as prov

    monkeypatch.setattr(prov, "_ensure_ddgs_installed", lambda: None)
    monkeypatch.setattr(prov, "_QUEUED_SEARCH_GAP_SECS", 0)
    monkeypatch.setattr(prov, "_RETRY_PAUSE_SECS", 0)
    monkeypatch.setattr("tools.interrupt.is_interrupted", lambda: False)
    return prov


class TestDDGSParallelSearches:
    def test_a_burst_of_searches_runs_one_at_a_time(self, no_pauses, monkeypatch):
        import threading

        prov = no_pauses
        lock = threading.Lock()
        state = {"active": 0, "peak": 0}

        def slow_search(query, safe_limit):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.02)
            with lock:
                state["active"] -= 1
            return [{"title": query, "url": f"https://example.com/{query}", "description": "", "position": 1}]

        monkeypatch.setattr(prov, "_run_ddgs_search_bounded", slow_search)
        provider = prov.DDGSWebSearchProvider()
        results = {}

        def run(n):
            results[n] = provider.search(f"camera {n}", limit=3)

        threads = [threading.Thread(target=run, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(results) == 8 and all(r["success"] for r in results.values())
        assert state["peak"] == 1
        # The slot was handed back.
        assert prov._search_slots.acquire(blocking=False)
        prov._search_slots.release()

    def test_queued_searches_are_spaced_apart(self, no_pauses, monkeypatch):
        import threading

        prov = no_pauses
        monkeypatch.setattr(prov, "_QUEUED_SEARCH_GAP_SECS", 0.3)
        starts = []

        def search(query, safe_limit):
            starts.append(time.monotonic())
            time.sleep(0.05)
            return [{"title": "T", "url": f"https://e.com/{query}", "description": "", "position": 1}]

        monkeypatch.setattr(prov, "_run_ddgs_search_bounded", search)
        provider = prov.DDGSWebSearchProvider()
        threads = [threading.Thread(target=provider.search, args=(f"q{n}",)) for n in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        starts.sort()
        assert len(starts) == 3
        assert all(later - earlier >= 0.3 for earlier, later in zip(starts, starts[1:]))

    def test_a_search_gives_up_when_its_turn_never_comes(self, no_pauses, monkeypatch):
        import threading

        prov = no_pauses
        monkeypatch.setattr(prov, "_search_slots", threading.BoundedSemaphore(1))
        monkeypatch.setattr(prov, "_SLOT_WAIT_SECS", 0.2)
        prov._search_slots.acquire()
        try:
            result = prov.DDGSWebSearchProvider().search("q", limit=5)
        finally:
            prov._search_slots.release()

        assert result["success"] is False
        assert "busy" in result["error"]

    def test_a_fast_failure_is_retried_once(self, no_pauses, monkeypatch):
        prov = no_pauses
        outcomes = [RuntimeError("DDGSException: No results found."),
                    [{"title": "T", "url": "https://e.com", "description": "", "position": 1}]]
        calls = []

        def search(query, safe_limit):
            calls.append(query)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(prov, "_run_ddgs_search_bounded", search)

        result = prov.DDGSWebSearchProvider().search("q", limit=5)

        assert calls == ["q", "q"]
        assert result["data"]["web"][0]["url"] == "https://e.com"

    def test_a_second_fast_failure_is_reported(self, no_pauses, monkeypatch):
        prov = no_pauses
        calls = []

        def search(query, safe_limit):
            calls.append(query)
            raise RuntimeError("rate limited")

        monkeypatch.setattr(prov, "_run_ddgs_search_bounded", search)

        result = prov.DDGSWebSearchProvider().search("q", limit=5)

        assert len(calls) == 2
        assert result["success"] is False
        assert "rate limited" in result["error"]

    def test_a_timeout_is_not_retried(self, no_pauses, monkeypatch):
        prov = no_pauses
        calls = []

        def search(query, safe_limit):
            calls.append(query)
            raise TimeoutError("slow")

        monkeypatch.setattr(prov, "_run_ddgs_search_bounded", search)

        result = prov.DDGSWebSearchProvider().search("q", limit=5)

        assert calls == ["q"]
        assert "timed out" in result["error"]

    def test_the_same_search_again_reuses_the_results(self, no_pauses, monkeypatch):
        prov = no_pauses
        calls = []

        def search(query, safe_limit):
            calls.append(query)
            return [{"title": "T", "url": "https://example.com", "description": "", "position": 1}]

        monkeypatch.setattr(prov, "_run_ddgs_search_bounded", search)
        provider = prov.DDGSWebSearchProvider()

        first = provider.search("Arlo Pro 5  price", limit=5)
        second = provider.search("arlo pro 5 price", limit=5)

        assert calls == ["Arlo Pro 5  price"]
        assert second == first

    def test_empty_results_are_not_reused(self, no_pauses, monkeypatch):
        prov = no_pauses
        outcomes = [[], [{"title": "T", "url": "https://e.com", "description": "", "position": 1}]]
        monkeypatch.setattr(prov, "_run_ddgs_search_bounded", lambda query, safe_limit: outcomes.pop(0))
        provider = prov.DDGSWebSearchProvider()

        assert provider.search("q", limit=5)["data"]["web"] == []
        assert provider.search("q", limit=5)["data"]["web"][0]["url"] == "https://e.com"
