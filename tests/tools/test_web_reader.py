"""Tests for the built-in page reader (web_extract with no API key).

Every request goes to an in-process ``httpx.MockTransport`` — no network.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from tools import web_reader


PRODUCT_PAGE = """<!doctype html>
<html><head>
<meta charset="utf-8">
<title>Arlo Pro 5S 2K Camera | Arlo Store</title>
<meta name="description" content="Wire-free 2K security camera.">
<script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
  {"@type": "WebPage", "name": "Arlo Pro 5S"},
  {"@type": "Product", "name": "Arlo Pro 5S 2K", "brand": {"@type": "Brand", "name": "Arlo"},
   "sku": "VMC4060P",
   "offers": {"@type": "Offer", "price": "179.99", "priceCurrency": "USD",
              "availability": "https://schema.org/InStock",
              "seller": {"@type": "Organization", "name": "Arlo"}},
   "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.3", "reviewCount": "1234"}}
]}
</script>
<script>var secret = "<p>not page text</p>";</script>
<style>.price { color: red }</style>
</head>
<body>
<header><nav><a href="/">Home</a> <a href="/shop">Shop</a></nav></header>
<div id="cookie-banner">We use cookies. <button>Accept</button></div>
<main>
  <h1>Arlo Pro 5S 2K</h1>
  <p>The best <b>wire-free</b> camera &amp; more.
  <p>See the <a href="/specs">full specs</a>.
  <ul><li>2K HDR video<li>Dual-band Wi-Fi<ul><li>2.4 GHz</li><li>5 GHz</li></ul></li></ul>
  <table>
    <tr><th>Spec</th><th>Value</th></tr>
    <tr><td>Resolution</td><td>2K</td></tr>
    <tr><td>Battery</td><td>up to 8 months</td></tr>
  </table>
  <p style="display:none">Hidden promo text</p>
  <p>Arlo Pro 5S records sharp 2K HDR video with colour night vision and an integrated
  spotlight, and its battery lasts for months between charges on a typical schedule.</p>
</main>
<footer>Copyright 2026 Arlo</footer>
</body></html>
"""


def _serve(monkeypatch, routes, *, safe=lambda url: True, policy=lambda url: None):
    """Point the reader at ``routes``: {url: httpx.Response | callable(request)}."""
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        route = routes.get(url)
        if route is None:
            return httpx.Response(404, text="missing")
        if callable(route):
            result = route(request)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        return route

    async def is_safe(url: str) -> bool:
        return safe(url)

    monkeypatch.setattr(
        web_reader,
        "_make_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    monkeypatch.setattr(web_reader, "async_is_safe_url", is_safe)
    monkeypatch.setattr(web_reader, "check_website_access", policy)
    return seen


def _html(body: str, status: int = 200, charset: str = "utf-8") -> httpx.Response:
    return httpx.Response(
        status,
        content=body.encode(charset),
        headers={"content-type": f"text/html; charset={charset}"},
    )


def _read(urls):
    return asyncio.run(web_reader.read_pages(urls))


class TestProductPages:
    def test_reads_the_real_price_stock_and_rating(self, monkeypatch):
        _serve(monkeypatch, {"https://shop.test/arlo": _html(PRODUCT_PAGE)})

        [page] = _read(["https://shop.test/arlo"])

        assert page.get("error") is None
        assert page["title"] == "Arlo Pro 5S 2K Camera | Arlo Store"
        content = page["content"]
        assert "## Key facts (from the page's structured data)" in content
        assert "- **Arlo Pro 5S 2K**" in content
        assert "Price: 179.99 USD (in stock, sold by Arlo)" in content
        assert "Rating: 4.3/5 from 1234 reviews" in content
        # Facts come before the body so a truncated page still keeps them.
        assert content.index("179.99 USD") < content.index("# Arlo Pro 5S 2K\n")

    def test_keeps_the_page_and_drops_site_chrome(self, monkeypatch):
        _serve(monkeypatch, {"https://shop.test/arlo": _html(PRODUCT_PAGE)})

        content = _read(["https://shop.test/arlo"])[0]["content"]

        assert "The best wire-free camera & more." in content
        assert "See the [full specs](https://shop.test/specs)." in content
        assert "- 2K HDR video\n- Dual-band Wi-Fi\n  - 2.4 GHz\n  - 5 GHz" in content
        assert "| Spec | Value |\n| --- | --- |\n| Resolution | 2K |" in content
        for gone in ("Home", "We use cookies", "Copyright", "Hidden promo", "not page text", "color: red"):
            assert gone not in content

    def test_price_range_across_sellers(self, monkeypatch):
        page = """<html><head><title>Cam</title><script type="application/ld+json">
        {"@type": "Product", "name": "Cam X",
         "offers": {"@type": "AggregateOffer", "lowPrice": 149, "highPrice": 199,
                    "priceCurrency": "USD", "offerCount": 4}}
        </script></head><body><p>Cam X details.</p></body></html>"""
        _serve(monkeypatch, {"https://shop.test/x": _html(page)})

        content = _read(["https://shop.test/x"])[0]["content"]

        assert "Price: 149 USD – 199 USD (4 offers)" in content

    def test_price_from_meta_tags_when_there_is_no_json_ld(self, monkeypatch):
        page = """<html><head><title>Cam</title>
        <meta property="product:price:amount" content="89.00">
        <meta property="product:price:currency" content="EUR">
        </head><body><p>A camera.</p></body></html>"""
        _serve(monkeypatch, {"https://shop.test/m": _html(page)})

        assert "Price (page metadata): 89.00 EUR" in _read(["https://shop.test/m"])[0]["content"]

    def test_price_from_microdata(self, monkeypatch):
        page = """<html><head><title>Cam</title></head><body>
        <div itemscope itemtype="https://schema.org/Product"><span itemprop="name">Cam</span>
        <span itemprop="price" content="59.99">$59.99</span>
        <meta itemprop="priceCurrency" content="USD"></div></body></html>"""
        _serve(monkeypatch, {"https://shop.test/md": _html(page)})

        assert "Price (page markup): 59.99 USD" in _read(["https://shop.test/md"])[0]["content"]

    def test_listing_page_names_each_product_with_its_link(self, monkeypatch):
        items = [
            {"@type": "ListItem", "position": i, "item": {
                "@type": "Product", "name": f"Camera {i}", "url": f"https://shop.test/c{i}",
                "offers": {"@type": "Offer", "price": f"{i}9.99", "priceCurrency": "USD"}}}
            for i in (1, 2)
        ]
        page = (
            "<html><head><title>Cameras</title><script type='application/ld+json'>"
            + json.dumps({"@type": "ItemList", "itemListElement": items})
            + "</script></head><body><p>All cameras.</p></body></html>"
        )
        _serve(monkeypatch, {"https://shop.test/list": _html(page)})

        content = _read(["https://shop.test/list"])[0]["content"]

        assert "- **Camera 1**\n  - Price: 19.99 USD\n  - Link: https://shop.test/c1" in content
        assert "- **Camera 2**\n  - Price: 29.99 USD\n  - Link: https://shop.test/c2" in content

    def test_article_date_and_author(self, monkeypatch):
        page = """<html><head><title>Best cameras</title><script type="application/ld+json">
        {"@type": "NewsArticle", "headline": "Best cameras", "datePublished": "2026-08-01",
         "author": [{"@type": "Person", "name": "Sam Lee"}]}</script></head>
        <body><article><h1>Best cameras</h1><p>""" + ("Long review text. " * 60) + """</p></article>
        <aside>Related links</aside></body></html>"""
        _serve(monkeypatch, {"https://news.test/best": _html(page)})

        content = _read(["https://news.test/best"])[0]["content"]

        assert "Published: 2026-08-01 · By: Sam Lee" in content
        assert "Related links" not in content


class TestRedirectsAndSafety:
    def test_follows_redirects_and_says_where_it_landed(self, monkeypatch):
        _serve(monkeypatch, {
            "https://short.test/a": httpx.Response(301, headers={"location": "https://shop.test/arlo"}),
            "https://shop.test/arlo": _html(PRODUCT_PAGE),
        })

        [page] = _read(["https://short.test/a"])

        assert page["url"] == "https://short.test/a"
        assert page["metadata"]["final_url"] == "https://shop.test/arlo"
        assert "(Opened https://shop.test/arlo)" in page["content"]

    def test_redirect_into_a_private_network_is_blocked(self, monkeypatch):
        seen = _serve(
            monkeypatch,
            {"https://evil.test/": httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})},
            safe=lambda url: "169.254" not in url,
        )

        [page] = _read(["https://evil.test/"])

        assert "private or internal network" in page["error"]
        assert seen == ["https://evil.test/"]

    def test_redirect_to_a_blocklisted_site_is_blocked(self, monkeypatch):
        def policy(url):
            if "blocked.test" in url:
                return {"host": "blocked.test", "rule": "blocked.test", "source": "config",
                        "message": "Blocked by website policy"}
            return None

        seen = _serve(
            monkeypatch,
            {"https://ok.test/": httpx.Response(302, headers={"location": "https://blocked.test/page"})},
            policy=policy,
        )

        [page] = _read(["https://ok.test/"])

        assert page["error"] == "Blocked by website policy"
        assert page["blocked_by_policy"]["rule"] == "blocked.test"
        assert seen == ["https://ok.test/"]

    def test_endless_redirects_stop(self, monkeypatch):
        _serve(monkeypatch, {"https://loop.test/": httpx.Response(302, headers={"location": "https://loop.test/"})})

        assert "Too many redirects" in _read(["https://loop.test/"])[0]["error"]

    def test_non_web_scheme_redirect_is_refused(self, monkeypatch):
        _serve(monkeypatch, {"https://x.test/": httpx.Response(302, headers={"location": "file:///etc/passwd"})})

        assert "Only http and https" in _read(["https://x.test/"])[0]["error"]


class TestPagesThatCannotBeRead:
    def test_refused_request_points_at_the_browser(self, monkeypatch):
        _serve(monkeypatch, {"https://www.shop.test/p": _html("<html><body>Forbidden</body></html>", status=403)})

        error = _read(["https://www.shop.test/p"])[0]["error"]

        assert "www.shop.test refused the built-in reader (HTTP 403)" in error
        assert "another site" in error

    def test_bot_check_page_is_reported_not_returned(self, monkeypatch):
        page = """<html><head><title>Amazon.com</title></head><body>
        <h4>Enter the characters you see below</h4>
        <p>Sorry, we just need to make sure you're not a robot.</p></body></html>"""
        _serve(monkeypatch, {"https://www.amazon.test/dp/1": _html(page)})

        error = _read(["https://www.amazon.test/dp/1"])[0]["error"]

        assert "showed a bot check" in error
        assert "another site" in error

    def test_javascript_only_page_says_so(self, monkeypatch):
        page = "<html><head><title>App</title></head><body><div id='root'></div><script>boot()</script></body></html>"
        _serve(monkeypatch, {"https://app.test/": _html(page)})

        assert "built by JavaScript" in _read(["https://app.test/"])[0]["error"]

    def test_not_found(self, monkeypatch):
        _serve(monkeypatch, {})

        assert _read(["https://gone.test/x"])[0]["error"] == "Page not found (HTTP 404)."

    def test_images_are_not_pages(self, monkeypatch):
        _serve(monkeypatch, {"https://x.test/a.png": httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})})

        assert "image/png" in _read(["https://x.test/a.png"])[0]["error"]

    def test_slow_page_times_out(self, monkeypatch):
        async def slow(_request):
            await asyncio.sleep(5)
            return _html(PRODUCT_PAGE)

        _serve(monkeypatch, {"https://slow.test/": slow})
        monkeypatch.setattr(web_reader, "PAGE_TIMEOUT_SECS", 0.2)

        assert "took longer than" in _read(["https://slow.test/"])[0]["error"]

    def test_one_bad_page_does_not_sink_the_others(self, monkeypatch):
        _serve(monkeypatch, {
            "https://a.test/": _html(PRODUCT_PAGE),
            "https://b.test/": _html("<html><body>no</body></html>", status=500),
        })

        first, second = _read(["https://a.test/", "https://b.test/"])

        assert first.get("error") is None and "179.99" in first["content"]
        assert "HTTP 500" in second["error"]


class TestOtherContent:
    def test_json_is_pretty_printed(self, monkeypatch):
        _serve(monkeypatch, {"https://api.test/v1": httpx.Response(200, json={"price": 10, "currency": "USD"})})

        content = _read(["https://api.test/v1"])[0]["content"]

        assert json.loads(content) == {"price": 10, "currency": "USD"}
        assert "\n  " in content

    def test_plain_text(self, monkeypatch):
        _serve(monkeypatch, {"https://x.test/robots.txt": httpx.Response(200, text="User-agent: *", headers={"content-type": "text/plain"})})

        assert _read(["https://x.test/robots.txt"])[0]["content"] == "User-agent: *"

    def test_pdf_is_converted_like_read_file_does(self, monkeypatch):
        import tools.read_extract as read_extract

        converted = []

        def fake_extract(path):
            with open(path, "rb") as handle:
                converted.append((path.endswith(".pdf"), handle.read()))
            return "Page 1: Arlo Pro 5S spec sheet\n"

        monkeypatch.setattr(read_extract, "is_extractable_document", lambda path: True)
        monkeypatch.setattr(read_extract, "extract_document_text", fake_extract)
        _serve(monkeypatch, {"https://x.test/spec": httpx.Response(200, content=b"%PDF-1.7 data", headers={"content-type": "application/octet-stream"})})

        [page] = _read(["https://x.test/spec"])

        assert page["content"] == "Page 1: Arlo Pro 5S spec sheet\n"
        assert converted == [(True, b"%PDF-1.7 data")]

    def test_document_without_the_converter_explains_why(self, monkeypatch):
        import tools.read_extract as read_extract

        monkeypatch.setattr(read_extract, "is_extractable_document", lambda path: False)
        _serve(monkeypatch, {"https://x.test/a.pdf": httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"})})

        assert "document converter" in _read(["https://x.test/a.pdf"])[0]["error"]

    def test_oversized_document_is_refused(self, monkeypatch):
        monkeypatch.setattr(web_reader, "MAX_DOCUMENT_BYTES", 10)
        _serve(monkeypatch, {"https://x.test/big.pdf": httpx.Response(200, content=b"%PDF-" + b"x" * 100, headers={"content-type": "application/pdf"})})

        assert "too big to read" in _read(["https://x.test/big.pdf"])[0]["error"]

    def test_huge_page_is_cut_and_says_so(self, monkeypatch):
        monkeypatch.setattr(web_reader, "MAX_PAGE_BYTES", 4096)
        page = "<html><head><title>Long</title></head><body>" + "<p>Paragraph of text.</p>" * 2000 + "</body></html>"
        _serve(monkeypatch, {"https://x.test/long": _html(page)})

        content = _read(["https://x.test/long"])[0]["content"]

        assert "Paragraph of text." in content
        assert "only the first part was read" in content

    def test_legacy_charset_from_the_page_itself(self, monkeypatch):
        page = "<html><head><meta charset='windows-1252'><title>Caf\xe9</title></head><body><p>Cr\xe8me br\xfbl\xe9e costs \x8010.</p></body></html>"
        _serve(monkeypatch, {"https://x.test/fr": httpx.Response(200, content=page.encode("latin-1"), headers={"content-type": "text/html"})})

        [result] = _read(["https://x.test/fr"])

        assert result["title"] == "Café"
        assert "Crème brûlée costs €10." in result["content"]


class TestHtmlConversion:
    def test_deeply_nested_markup_does_not_crash(self):
        html = "<html><body>" + "<div>" * 5000 + "deep text" + "</div>" * 5000 + "</body></html>"

        page = web_reader.html_to_page(html, "https://x.test/")

        assert "deep text" in page.body

    def test_broken_json_ld_is_ignored(self):
        html = "<html><head><script type='application/ld+json'>{not json</script></head><body><p>Fine.</p></body></html>"

        page = web_reader.html_to_page(html, "https://x.test/")

        assert page.facts == []
        assert page.body == "Fine."

    def test_icon_titles_do_not_leak_into_the_page_title(self):
        html = (
            "<html><head><title>Real Title</title></head><body>"
            "<svg><title>Close</title><path d='M0'/></svg><p>Text.</p></body></html>"
        )

        page = web_reader.html_to_page(html, "https://x.test/")

        assert page.title == "Real Title"
        assert "Close" not in page.body

    def test_a_product_repeated_in_several_blocks_is_listed_once(self):
        block = '{"@type": "Product", "name": "Cam", "offers": {"@type": "Offer", "price": "10", "priceCurrency": "USD"}}'
        html = (
            f"<html><head><script type='application/ld+json'>{block}</script>"
            f"<script type='application/ld+json'>{block}</script></head><body><p>x</p></body></html>"
        )

        page = web_reader.html_to_page(html, "https://x.test/")

        assert page.facts == ["- **Cam**", "  - Price: 10 USD"]


class TestWebExtractUsesTheReader:
    def test_end_to_end_with_the_keyless_default(self, monkeypatch):
        from tests.tools.conftest import register_all_web_providers
        from agent.web_search_registry import _reset_for_tests
        from tools import web_tools

        register_all_web_providers()
        try:
            _serve(monkeypatch, {"https://shop.test/arlo": _html(PRODUCT_PAGE)})

            async def allow(_url):
                return True

            monkeypatch.setattr(web_tools, "_load_web_config", lambda: {"backend": "ddgs"})
            monkeypatch.setattr(web_tools, "_ddgs_package_importable", lambda: True)
            monkeypatch.setattr(web_tools, "async_is_safe_url", allow)
            monkeypatch.setattr("tools.interrupt.is_interrupted", lambda: False, raising=False)
            monkeypatch.setattr(
                "agent.web_search_registry._read_config_key",
                lambda *path: "ddgs" if path == ("web", "backend") else None,
            )

            result = json.loads(asyncio.run(web_tools.web_extract_tool(["https://shop.test/arlo"])))
        finally:
            _reset_for_tests()

        [page] = result["results"]
        assert page["error"] is None
        assert page["title"] == "Arlo Pro 5S 2K Camera | Arlo Store"
        assert "Price: 179.99 USD" in page["content"]


class TestSearchPointsAtPageReading:
    """web_search tells the model to open results — only when it can."""

    def _descriptions(self, monkeypatch, toolsets):
        import model_tools
        from tools import registry as registry_module
        from tools import web_tools

        monkeypatch.setattr(web_tools, "_load_web_config", lambda: {"backend": "ddgs"})
        monkeypatch.setattr(web_tools, "_ddgs_package_importable", lambda: True)
        monkeypatch.setattr(registry_module, "_check_fn_cache", {})
        model_tools._clear_tool_defs_cache()
        defs = model_tools.get_tool_definitions(enabled_toolsets=toolsets, quiet_mode=True)
        return {d["function"]["name"]: d["function"]["description"] for d in defs}

    def test_hint_is_added_when_web_extract_is_available(self, monkeypatch):
        import model_tools

        descriptions = self._descriptions(monkeypatch, ["web"])

        assert descriptions["web_search"].endswith(model_tools.WEB_SEARCH_READ_PAGES_HINT)

    def test_no_hint_when_only_search_is_enabled(self, monkeypatch):
        import model_tools

        descriptions = self._descriptions(monkeypatch, ["search"])

        assert "web_extract" not in descriptions
        assert model_tools.WEB_SEARCH_READ_PAGES_HINT not in descriptions["web_search"]
