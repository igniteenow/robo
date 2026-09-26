"""Built-in page reader — ``web_extract`` with no API key.

When no extract backend is set up (the keyless default pairs DuckDuckGo
search, which cannot read pages, with nothing), ``web_extract`` falls back
to this reader. It fetches each page directly and turns it into clean
Markdown for the model:

* HTML — the main content (``<main>`` / a lone ``<article>`` / the body minus
  site navigation, footers and cookie banners), with headings, lists, tables
  and links kept. The facts stores publish for search engines (schema.org
  JSON-LD, price meta tags, microdata) are pulled to the top, so a product
  page yields its real price, stock and rating even when the visible price
  is drawn by JavaScript.
* Plain text, JSON, XML and CSV — returned as text.
* PDF, Word, Excel, PowerPoint, OpenDocument, RTF and EPUB — converted by the
  same extractor ``read_file`` uses (``tools.read_extract``).

Safety matches the rest of the web tools: every hop of a redirect chain is
checked against the SSRF rules and the website blocklist, the HTTP client
pins connects to vetted IPs, and response bodies are size-capped. Pages that
answer with a bot check or need JavaScript come back as an error that points
the model at the browser tool.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple, Union
from urllib.parse import urljoin, urlsplit

from tools.url_safety import async_is_safe_url, create_ssrf_safe_async_client, redirect_target_from_response
from tools.website_policy import check_website_access

logger = logging.getLogger(__name__)

# ─── Limits ──────────────────────────────────────────────────────────────────

MAX_REDIRECTS = 8
# Web pages: big retail pages run 1–3 MB of HTML; past this the rest is
# scripts and tracking. The body is cut here and the prefix still parses.
MAX_PAGE_BYTES = 6 * 1024 * 1024
# Documents must arrive whole to be readable at all.
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
# Per-page wall clock, fetch + conversion.
PAGE_TIMEOUT_SECS = 60.0
_HTTP_TIMEOUT = {"connect": 10.0, "read": 20.0, "write": 10.0, "pool": 10.0}

# Parser guards for pathological markup. Real pages nest well under 100
# levels; deeper elements are folded into their 120th ancestor (text kept),
# which also bounds the renderer's recursion.
_MAX_DEPTH = 120
_MAX_NODES = 400_000
_MAX_LINKS = 400
_MAX_TABLE_ROWS = 300
_MAX_PRODUCTS = 25

# Browser-like request headers: many sites refuse unknown clients outright.
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/pdf;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# The browser tool may not be enabled, so the hint never assumes it is.
_BROWSER_HINT = "If a browser tool is available, open the page there; otherwise find the same facts on another site."

# ─── Content types ───────────────────────────────────────────────────────────

_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_TEXT_TYPES = frozenset({
    "application/json", "application/ld+json", "application/xml", "text/xml",
    "application/rss+xml", "application/atom+xml", "application/javascript",
    "text/javascript", "application/x-ndjson", "application/yaml", "text/yaml",
})
_DOCUMENT_TYPES = {
    "application/pdf": ".pdf",
    "application/x-pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/rtf": ".rtf",
    "text/rtf": ".rtf",
    "application/epub+zip": ".epub",
}
_DOCUMENT_EXTENSIONS = frozenset(_DOCUMENT_TYPES.values())
_GENERIC_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream", "application/download"})

# A bot check or a "turn on JavaScript" wall instead of the page. Only
# consulted for short pages — real articles mention these words too.
_BLOCK_PAGE = re.compile(
    r"captcha|are you a robot|not a robot|robot check|verify (?:that )?you(?: are|'re) (?:a )?human"
    r"|access denied|request blocked|unusual traffic|enable javascript|javascript is (?:disabled|required)"
    r"|please enable cookies|just a moment|attention required|checking your browser"
    r"|connection is secure|pardon our interruption|press (?:&|and) hold",
    re.IGNORECASE,
)
_BLOCK_PAGE_MAX_TEXT = 3000
_THIN_PAGE_TEXT = 250

# Result key set when another reader might succeed where this one did not.
# Internal: web_extract drops it before the model sees the result.
RETRY_ELSEWHERE = "retry_elsewhere"


# ─── Public entry point ──────────────────────────────────────────────────────


def _make_client() -> Any:
    """HTTP client for page fetches (patched in tests)."""
    import httpx

    return create_ssrf_safe_async_client(
        headers=_REQUEST_HEADERS,
        timeout=httpx.Timeout(**_HTTP_TIMEOUT),
        follow_redirects=False,
    )


async def read_pages(urls: List[str]) -> List[Dict[str, Any]]:
    """Read each URL and return one ``web_extract`` result dict per URL, in order.

    Result shape matches :meth:`WebSearchProvider.extract`: ``url``, ``title``,
    ``content``, ``raw_content``, ``metadata`` — or ``url``, ``title``,
    ``content`` and ``error`` for a page that could not be read.
    """
    if not urls:
        return []
    async with _make_client() as client:
        return list(await asyncio.gather(*(_read_one(client, url) for url in urls)))


async def _read_one(client: Any, url: str) -> Dict[str, Any]:
    try:
        from tools.interrupt import is_interrupted

        if is_interrupted():
            return _failure(url, "Interrupted")
    except Exception:  # noqa: BLE001 — interrupt helper is optional here
        pass
    try:
        return await asyncio.wait_for(_read(client, url), timeout=PAGE_TIMEOUT_SECS)
    except asyncio.TimeoutError:
        return _failure(url, f"The page took longer than {int(PAGE_TIMEOUT_SECS)}s to load. {_BROWSER_HINT}", retry_elsewhere=True)
    except _ReadError as exc:
        return _failure(url, str(exc), blocked_by_policy=exc.policy, retry_elsewhere=exc.retry_elsewhere)
    except Exception as exc:  # noqa: BLE001 — one bad page never sinks the batch
        logger.info("Built-in reader failed for %s: %s", url, exc)
        return _failure(url, f"Could not load the page: {_describe_error(exc)}", retry_elsewhere=True)


def _failure(
    url: str, message: str, *, blocked_by_policy: Optional[dict] = None, retry_elsewhere: bool = False
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"url": url, "title": "", "content": "", "error": message}
    if blocked_by_policy:
        result["blocked_by_policy"] = blocked_by_policy
    if retry_elsewhere:
        # A hosted reader may get through where a direct fetch did not (bot
        # checks, JavaScript pages, missing converters). Policy and
        # private-network blocks are never retried elsewhere.
        result[RETRY_ELSEWHERE] = True
    return result


def _describe_error(exc: Exception) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


class _ReadError(Exception):
    def __init__(self, message: str, *, policy: Optional[dict] = None, retry_elsewhere: bool = False):
        super().__init__(message)
        self.policy = policy
        self.retry_elsewhere = retry_elsewhere


# ─── Fetch ───────────────────────────────────────────────────────────────────


@dataclass
class _Fetched:
    url: str
    final_url: str
    status: int
    content_type: str
    charset: Optional[str]
    body: bytes
    truncated: bool


async def _check_target(url: str) -> None:
    """SSRF + website-policy gate for one hop of a fetch."""
    scheme = urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise _ReadError(f"Only http and https pages can be read (got {scheme or 'no scheme'}: {url}).")
    if not await async_is_safe_url(url):
        raise _ReadError("Blocked: URL targets a private or internal network address")
    blocked = check_website_access(url)
    if blocked:
        raise _ReadError(
            blocked["message"],
            policy={"host": blocked["host"], "rule": blocked["rule"], "source": blocked["source"]},
        )


async def _fetch(client: Any, url: str) -> _Fetched:
    current = url
    for hop in range(MAX_REDIRECTS + 1):
        if hop:
            # The first hop was vetted by web_extract before dispatch.
            await _check_target(current)
        else:
            blocked = check_website_access(current)
            if blocked:
                raise _ReadError(
                    blocked["message"],
                    policy={"host": blocked["host"], "rule": blocked["rule"], "source": blocked["source"]},
                )
        response = await client.send(client.build_request("GET", current), stream=True)
        try:
            if response.is_redirect:
                target = redirect_target_from_response(response)
                if not target:
                    raise _ReadError(f"The site sent a redirect with no destination (HTTP {response.status_code}).")
                current = target
                continue
            content_type, charset = _parse_content_type(response.headers.get("content-type", ""))
            cap = MAX_DOCUMENT_BYTES if _document_extension(content_type, str(response.url), b"") else MAX_PAGE_BYTES
            body, truncated = await _read_body(response, cap)
            return _Fetched(
                url=url,
                final_url=str(response.url),
                status=response.status_code,
                content_type=content_type,
                charset=charset,
                body=body,
                truncated=truncated,
            )
        finally:
            await response.aclose()
    raise _ReadError(f"Too many redirects (more than {MAX_REDIRECTS}).", retry_elsewhere=True)


async def _read_body(response: Any, cap: int) -> Tuple[bytes, bool]:
    chunks: List[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        room = cap - total
        if len(chunk) > room:
            chunks.append(chunk[:room])
            return b"".join(chunks), True
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), False


def _parse_content_type(header: str) -> Tuple[str, Optional[str]]:
    main, _, params = header.partition(";")
    charset = None
    for param in params.split(";"):
        key, _, value = param.partition("=")
        if key.strip().lower() == "charset":
            charset = value.strip().strip("\"'") or None
    return main.strip().lower(), charset


def _document_extension(content_type: str, url: str, body: bytes) -> Optional[str]:
    if content_type in _DOCUMENT_TYPES:
        return _DOCUMENT_TYPES[content_type]
    if content_type in _GENERIC_TYPES:
        if body.startswith(b"%PDF-"):
            return ".pdf"
        ext = os.path.splitext(urlsplit(url).path)[1].lower()
        if ext in _DOCUMENT_EXTENSIONS:
            return ext
    return None


# ─── Read one page ───────────────────────────────────────────────────────────


async def _read(client: Any, url: str) -> Dict[str, Any]:
    fetched = await _fetch(client, url)
    host = urlsplit(fetched.final_url).hostname or "The site"

    if fetched.status >= 400:
        raise _ReadError(_status_message(fetched.status, host), retry_elsewhere=fetched.status not in (404, 410))

    doc_ext = _document_extension(fetched.content_type, fetched.final_url, fetched.body[:8])
    if doc_ext:
        if fetched.truncated:
            raise _ReadError(
                f"The {doc_ext[1:].upper()} file is larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB, "
                "too big to read here."
            )
        text = await asyncio.to_thread(_document_to_text, fetched.body, doc_ext)
        title = os.path.basename(urlsplit(fetched.final_url).path) or fetched.final_url
        return _success(fetched, title, text)

    if _looks_like_html(fetched):
        page = await asyncio.to_thread(html_to_page, _decode(fetched.body, fetched.charset), fetched.final_url)
        result = _success(fetched, page.title, _page_content(page, fetched, host))
        if not page.facts and len(page.body.strip()) < _THIN_PAGE_TEXT:
            result[RETRY_ELSEWHERE] = True  # thin page: a hosted reader may render more
        return result

    if fetched.content_type.startswith("text/") or fetched.content_type in _TEXT_TYPES or fetched.content_type.endswith(("+json", "+xml")):
        text = _decode(fetched.body, fetched.charset)
        if "json" in fetched.content_type:
            text = _pretty_json(text)
        if not text.strip():
            raise _ReadError("The page is empty.", retry_elsewhere=True)
        return _success(fetched, os.path.basename(urlsplit(fetched.final_url).path), text)

    kind = fetched.content_type or "an unknown type"
    raise _ReadError(f"The link points to {kind}, which isn't a page or document that can be read as text.")


def _status_message(status: int, host: str) -> str:
    if status in (401, 403, 429, 451, 999) or status == 503:
        return f"{host} refused the built-in reader (HTTP {status}); it blocks automated visits. {_BROWSER_HINT}"
    if status in (404, 410):
        return f"Page not found (HTTP {status})."
    return f"{host} answered with an error (HTTP {status})."


def _success(fetched: _Fetched, title: str, content: str) -> Dict[str, Any]:
    return {
        "url": fetched.url,
        "title": title,
        "content": content,
        "raw_content": content,
        "metadata": {
            "final_url": fetched.final_url,
            "status": fetched.status,
            "content_type": fetched.content_type,
            "reader": "builtin",
        },
    }


def _looks_like_html(fetched: _Fetched) -> bool:
    if fetched.content_type in _HTML_TYPES:
        return True
    if fetched.content_type in _GENERIC_TYPES or fetched.content_type == "text/plain":
        head = fetched.body[:1024].lstrip().lower()
        return head.startswith((b"<!doctype html", b"<html")) or b"<body" in head
    return False


_META_CHARSET = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:\-]+)", re.IGNORECASE)


def _decode(body: bytes, charset: Optional[str]) -> str:
    if body.startswith(codecs.BOM_UTF8):
        return body[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace")
    candidates = [charset]
    match = _META_CHARSET.search(body[:4096])
    if match:
        candidates.append(match.group(1).decode("ascii", errors="ignore"))
    candidates.append("utf-8")
    for encoding in candidates:
        if not encoding:
            continue
        try:
            codecs.lookup(encoding)
        except LookupError:
            continue
        return body.decode(encoding, errors="replace")
    return body.decode("utf-8", errors="replace")


def _pretty_json(text: str) -> str:
    if len(text) > 2_000_000:
        return text
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        return text


def _document_to_text(body: bytes, ext: str) -> str:
    from tools.read_extract import ExtractionError, extract_document_text, is_extractable_document

    fd, path = tempfile.mkstemp(prefix="robo-web-", suffix=ext)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
        if not is_extractable_document(path):
            raise _ReadError(
                f"Reading {ext[1:].upper()} files needs Robo's document converter, which isn't installed "
                "here (it installs itself on first use when installs are allowed).",
                retry_elsewhere=True,
            )
        try:
            return extract_document_text(path)
        except ExtractionError as exc:
            raise _ReadError(f"Could not read the {ext[1:].upper()} file: {exc}", retry_elsewhere=True) from exc
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _page_content(page: "Page", fetched: _Fetched, host: str) -> str:
    text_len = len(page.body.strip())
    if not page.facts and text_len < _BLOCK_PAGE_MAX_TEXT and _BLOCK_PAGE.search(f"{page.title}\n{page.body[:_BLOCK_PAGE_MAX_TEXT]}"):
        raise _ReadError(f"{host} showed a bot check instead of the page. {_BROWSER_HINT}", retry_elsewhere=True)
    if not page.facts and not page.body.strip() and not page.description:
        raise _ReadError(
            f"The page has no readable text — it is probably built by JavaScript. {_BROWSER_HINT}", retry_elsewhere=True
        )

    parts: List[str] = []
    if page.title:
        parts.append(f"# {page.title}")
    if fetched.final_url != fetched.url:
        parts.append(f"(Opened {fetched.final_url})")
    if page.published:
        parts.append(page.published)
    if page.facts:
        parts.append("## Key facts (from the page's structured data)\n" + "\n".join(page.facts))
    if page.description and text_len < 500:
        parts.append(f"Summary: {page.description}")
    if page.body.strip():
        parts.append(page.body.strip())
    if text_len < _THIN_PAGE_TEXT:
        parts.append(
            "(Note: very little text came through — this page probably loads its content with "
            f"JavaScript. {_BROWSER_HINT})"
        )
    if fetched.truncated:
        parts.append(f"(Note: the page is over {MAX_PAGE_BYTES // (1024 * 1024)} MB; only the first part was read.)")
    return "\n\n".join(parts) + "\n"


# ─── HTML → Markdown ─────────────────────────────────────────────────────────


@dataclass
class Page:
    title: str = ""
    description: str = ""
    published: str = ""
    facts: List[str] = field(default_factory=list)
    body: str = ""


class _Element:
    __slots__ = ("tag", "attrs", "children", "skip")

    def __init__(self, tag: str, attrs: Dict[str, str]):
        self.tag = tag
        self.attrs = attrs
        self.children: List[Union["_Element", str]] = []
        self.skip = False

    def elements(self) -> Iterator["_Element"]:
        """Every descendant element, document order, no recursion."""
        stack = [iter(self.children)]
        while stack:
            child = next(stack[-1], None)
            if child is None:
                stack.pop()
                continue
            if isinstance(child, _Element):
                yield child
                stack.append(iter(child.children))

    def find(self, tag: str) -> Optional["_Element"]:
        return next((el for el in self.elements() if el.tag == tag), None)


_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
})
# Never rendered: code, media, embedded frames and form controls.
_SKIP_TAGS = frozenset({
    "script", "style", "noscript", "template", "svg", "math", "iframe", "canvas",
    "object", "embed", "video", "audio", "select", "option", "button", "input",
    "textarea", "datalist", "dialog", "head",
})
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_BLOCK_TAGS = frozenset({
    "address", "article", "aside", "body", "center", "details", "div", "dl", "fieldset",
    "figcaption", "figure", "footer", "form", "header", "html", "main", "nav", "p",
    "section", "summary", "caption", "legend", "hgroup",
})
_CLOSES_P = frozenset(
    {"address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset",
     "figcaption", "figure", "footer", "form", "header", "hr", "main", "nav", "ol", "p",
     "pre", "section", "table", "ul"} | set(_HEADINGS)
)
_P_SCOPE = frozenset({
    "div", "section", "article", "main", "td", "th", "li", "blockquote", "body", "table",
    "ul", "ol", "dl", "form", "header", "footer", "aside", "nav", "figure", "button",
})
_BOILERPLATE_ATTR = re.compile(
    r"(?:^|[\s_-])(?:cookie|cookies|consent|gdpr|newsletter|advert|advertisement)(?:$|[\s_-])",
    re.IGNORECASE,
)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)
_MICRODATA_PROPS = ("price", "lowPrice", "highPrice", "priceCurrency", "availability")
_WHITESPACE = re.compile(r"[ \t\r\n\f\v ​]+")
_INDENT = "\x01"
# Links are padded with spaces so adjacent ones never fuse; drop the pad
# where it lands before punctuation ("[specs](…) ." → "[specs](…).").
_SPACE_BEFORE_PUNCT = re.compile(r"(?<=\S) ([.,;:!?])(?=\s|$)")


class _TreeBuilder(HTMLParser):
    """Forgiving HTML → element tree, with the page metadata on the side."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Element("#root", {})
        self._stack: List[_Element] = [self.root]
        self._overflow = 0
        self._nodes = 0
        self.title_parts: List[str] = []
        self.meta: Dict[str, str] = {}
        self.ld_json: List[str] = []
        self.microdata: Dict[str, Union[str, _Element]] = {}
        self._ld_buffer: Optional[List[str]] = None
        self._title_done = False

    # -- structure --------------------------------------------------------

    def _close_open(self, tag: Union[str, frozenset], scope: frozenset) -> None:
        tags = {tag} if isinstance(tag, str) else tag
        for index in range(len(self._stack) - 1, 0, -1):
            current = self._stack[index].tag
            if current in tags:
                del self._stack[index:]
                return
            if current in scope:
                return

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = {name.lower(): (value or "") for name, value in attrs}
        if tag == "meta":
            self._record_meta(attributes)
        itemprop = attributes.get("itemprop", "")
        if tag == "script":
            kind = attributes.get("type", "").lower()
            self._ld_buffer = [] if "ld+json" in kind else None

        if tag in _CLOSES_P:
            self._close_open("p", _P_SCOPE - {"p"})
        if tag == "li":
            self._close_open("li", frozenset({"ul", "ol", "menu"}))
        elif tag in ("dt", "dd"):
            self._close_open(frozenset({"dt", "dd"}), frozenset({"dl"}))
        elif tag == "tr":
            self._close_open("tr", frozenset({"table", "thead", "tbody", "tfoot"}))
        elif tag in ("td", "th"):
            self._close_open(frozenset({"td", "th"}), frozenset({"tr", "table"}))
        elif tag in ("thead", "tbody", "tfoot"):
            self._close_open(frozenset({"thead", "tbody", "tfoot"}), frozenset({"table"}))

        if self._nodes >= _MAX_NODES:
            return
        element = _Element(tag, attributes)
        self._nodes += 1
        if (
            tag in _SKIP_TAGS
            or "hidden" in attributes
            or attributes.get("aria-hidden", "").lower() == "true"
            or _HIDDEN_STYLE.search(attributes.get("style", ""))
            or _BOILERPLATE_ATTR.search(f"{attributes.get('id', '')} {attributes.get('class', '')}")
        ):
            element.skip = True
        if itemprop in _MICRODATA_PROPS and itemprop not in self.microdata:
            value = attributes.get("content") or attributes.get("href") or ""
            self.microdata[itemprop] = value if value else element

        self._stack[-1].children.append(element)
        if tag in _VOID_TAGS:
            return
        if len(self._stack) >= _MAX_DEPTH:
            self._overflow += 1
            return
        self._stack.append(element)

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._ld_buffer is not None:
            self.ld_json.append("".join(self._ld_buffer))
            self._ld_buffer = None
        if tag == "title" and self.title_parts:
            self._title_done = True
        if tag in _VOID_TAGS:
            return
        if self._overflow:
            self._overflow -= 1
            return
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        current = self._stack[-1]
        if current.tag == "script":
            if self._ld_buffer is not None:
                self._ld_buffer.append(data)
            return
        if current.tag == "style":
            return
        if current.tag == "title":
            # The document title only — not the <title> of inline SVG icons.
            if not self._title_done and not any(el.tag == "svg" for el in self._stack):
                self.title_parts.append(data)
            return
        if data:
            current.children.append(data)

    # -- metadata ---------------------------------------------------------

    def _record_meta(self, attributes: Dict[str, str]) -> None:
        key = (attributes.get("property") or attributes.get("name") or attributes.get("itemprop") or "").strip().lower()
        content = attributes.get("content", "").strip()
        if key and content and key not in self.meta:
            self.meta[key] = content


def html_to_page(html: str, base_url: str) -> Page:
    """Parse HTML into a :class:`Page`: title, structured facts and Markdown body."""
    builder = _TreeBuilder()
    try:
        builder.feed(html)
        builder.close()
    except Exception as exc:  # noqa: BLE001 — keep whatever parsed before the fault
        logger.debug("HTML parse stopped early for %s: %s", base_url, exc)

    root = builder.root
    title = _clean(" ".join(builder.title_parts)) or builder.meta.get("og:title", "")
    if not title:
        first_h1 = root.find("h1")
        title = _clean(_plain_text(first_h1)) if first_h1 is not None else ""

    records = _jsonld_records(builder.ld_json)
    facts = _product_facts(records)
    if not any(line.startswith("- **") for line in facts):
        facts.extend(_meta_price_facts(builder.meta, builder.microdata))
    published = _published_line(records, builder.meta)
    description = builder.meta.get("description") or builder.meta.get("og:description", "")

    content_root, boilerplate = _pick_content_root(root)
    try:
        body = _tidy(_Renderer(base_url, boilerplate).render(content_root))
    except RecursionError:
        body = _tidy(_clean(_plain_text(content_root)))
    return Page(title=title, description=_clean(description), published=published, facts=facts, body=body)


def _pick_content_root(root: _Element) -> Tuple[_Element, frozenset]:
    body = root.find("body") or root
    for element in body.elements():
        if (element.tag == "main" or element.attrs.get("role", "").lower() == "main") and not element.skip:
            if _text_length(element) >= 200:
                return element, frozenset({"nav", "footer"})
    articles = [el for el in body.elements() if el.tag == "article" and not el.skip]
    if len(articles) == 1 and _text_length(articles[0]) >= 500:
        return articles[0], frozenset({"nav", "footer"})
    return body, frozenset({"nav", "footer", "aside"})


def _text_length(element: _Element) -> int:
    total = 0
    stack: List[Union[_Element, str]] = [element]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            total += len(node.strip())
        elif not node.skip:
            stack.extend(node.children)
    return total


def _plain_text(element: Optional[_Element]) -> str:
    if element is None:
        return ""
    parts: List[str] = []
    stack: List[Union[_Element, str]] = [element]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            parts.append(node)
        elif not node.skip:
            stack.extend(reversed(node.children))
    return " ".join(parts)


def _clean(text: str) -> str:
    return _WHITESPACE.sub(" ", text or "").strip()


class _Renderer:
    """Element tree → Markdown. Depth is bounded by the parser (``_MAX_DEPTH``)."""

    def __init__(self, base_url: str, boilerplate: frozenset):
        self.base_url = base_url
        self.boilerplate = boilerplate
        self.links = 0
        self.list_depth = 0
        self.in_link = False
        self.in_cell = False

    def render(self, element: _Element) -> str:
        return "".join(self._node(child) for child in element.children)

    def _inline(self, element: _Element) -> str:
        return _clean(self.render(element).replace(_INDENT, ""))

    def _node(self, node: Union[_Element, str]) -> str:
        if isinstance(node, str):
            return _WHITESPACE.sub(" ", node)
        if node.skip:
            return ""
        tag = node.tag
        if tag in self.boilerplate or (tag == "header" and "aside" in self.boilerplate and node.find("nav") is not None):
            return ""
        if tag in _HEADINGS:
            text = self._inline(node)
            return f"\n\n{'#' * _HEADINGS[tag]} {text}\n\n" if text else ""
        if tag == "br":
            return "\n"
        if tag == "hr":
            return "\n\n---\n\n"
        if tag in ("ul", "ol", "menu"):
            return self._list(node, ordered=tag == "ol")
        if tag == "li":
            return "\n- " + self._inline(node)
        if tag == "table":
            return self._table(node)
        if tag == "pre":
            code = _plain_text_raw(node).strip("\n")
            return f"\n\n```\n{code}\n```\n\n" if code.strip() else ""
        if tag == "code":
            text = self._inline(node)
            return f"`{text}`" if text else ""
        if tag == "blockquote":
            inner = _tidy(self.render(node))
            return "\n\n" + "\n".join(f"> {line}" if line else ">" for line in inner.split("\n")) + "\n\n" if inner else ""
        if tag == "a":
            return self._link(node)
        if tag == "img":
            alt = _clean(node.attrs.get("alt", ""))
            if not alt or len(alt) < 3:
                return ""
            return f" {alt} " if self.in_link else f" [IMAGE: {alt}] "
        if tag == "dt":
            text = self._inline(node)
            return f"\n\n**{text}**\n" if text else ""
        if tag == "dd":
            return self._inline(node) + "\n"
        if tag in _BLOCK_TAGS:
            return "\n\n" + self.render(node) + "\n\n"
        return self.render(node)

    def _list(self, node: _Element, *, ordered: bool) -> str:
        self.list_depth += 1
        try:
            lines: List[str] = []
            number = 0
            for child in node.children:
                if isinstance(child, _Element) and child.tag == "li" and not child.skip:
                    number += 1
                    marker = f"{number}." if ordered else "-"
                    nested = [c for c in child.children if isinstance(c, _Element) and c.tag in ("ul", "ol")]
                    text = _clean("".join(self._node(c) for c in child.children if c not in nested).replace(_INDENT, ""))
                    if text:
                        lines.append("\n" + _INDENT * (self.list_depth - 1) + f"{marker} {text}")
                    for sub in nested:
                        lines.append(self._node(sub))
                else:
                    lines.append(self._node(child))
            if self.list_depth > 1:
                return "".join(lines)
            return "\n\n" + "".join(lines) + "\n\n"
        finally:
            self.list_depth -= 1

    def _table(self, node: _Element) -> str:
        rows: List[List[str]] = []
        header = False
        for row in _table_rows(node):
            cells = [c for c in row.children if isinstance(c, _Element) and c.tag in ("td", "th") and not c.skip]
            if not cells:
                continue
            if not rows and all(c.tag == "th" for c in cells):
                header = True
            previous, self.in_cell = self.in_cell, True
            try:
                rows.append([self._inline(c).replace("|", "\\|") for c in cells])
            finally:
                self.in_cell = previous
            if len(rows) >= _MAX_TABLE_ROWS:
                break
        rows = [r for r in rows if any(cell for cell in r)]
        if not rows:
            return ""
        if self.in_cell:
            return " " + " ; ".join(" ".join(c for c in r if c) for r in rows) + " "
        width = max(len(r) for r in rows)
        if width == 1:
            return "\n\n" + "\n".join(r[0] for r in rows) + "\n\n"
        padded = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(padded[0]) + " |", "|" + " --- |" * width]
        lines.extend("| " + " | ".join(r) + " |" for r in padded[1:])
        if not header and len(padded) > 1:
            # No header row: keep the first row as data, give the table a blank header.
            lines = ["|" + "  |" * width, "|" + " --- |" * width] + ["| " + " | ".join(r) + " |" for r in padded]
        return "\n\n" + "\n".join(lines) + "\n\n"

    def _link(self, node: _Element) -> str:
        previous, self.in_link = self.in_link, True
        try:
            text = self._inline(node)
        finally:
            self.in_link = previous
        href = node.attrs.get("href", "").strip()
        if not text:
            return ""
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")) or self.in_link or self.in_cell:
            return f" {text} "
        absolute = urljoin(self.base_url, href)
        if urlsplit(absolute).scheme not in ("http", "https"):
            return f" {text} "
        self.links += 1
        if self.links > _MAX_LINKS or absolute == text:
            return f" {text} "
        return f" [{text}]({absolute}) "


def _table_rows(table: _Element) -> Iterator[_Element]:
    for child in table.children:
        if not isinstance(child, _Element) or child.skip:
            continue
        if child.tag == "tr":
            yield child
        elif child.tag in ("thead", "tbody", "tfoot"):
            for row in child.children:
                if isinstance(row, _Element) and row.tag == "tr" and not row.skip:
                    yield row


def _plain_text_raw(element: _Element) -> str:
    parts: List[str] = []
    stack: List[Union[_Element, str]] = [element]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            parts.append(node)
        elif node.tag == "br":
            parts.append("\n")
        elif not node.skip:
            stack.extend(reversed(node.children))
    return "".join(parts)


def _tidy(markdown: str) -> str:
    """Collapse whitespace, rebuild list indents, drop repeats and extra blank lines."""
    out: List[str] = []
    in_fence = False
    for raw in markdown.split("\n"):
        stripped = raw.strip(" \t")
        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(stripped)
            continue
        if in_fence:
            out.append(raw.rstrip())
            continue
        depth = len(stripped) - len(stripped.lstrip(_INDENT))
        text = _WHITESPACE.sub(" ", stripped.lstrip(_INDENT).replace(_INDENT, "")).strip()
        text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
        if text in ("-", "*") or re.fullmatch(r"\d+\.", text or "x"):
            continue
        line = "  " * depth + text if text else ""
        if line and out and out[-1] == line:
            continue
        if not line and (not out or not out[-1]):
            continue
        out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


# ─── Structured data ─────────────────────────────────────────────────────────


def _jsonld_records(blocks: Iterable[str]) -> List[dict]:
    """Every typed object in the page's JSON-LD blocks (``@graph`` flattened)."""
    records: List[dict] = []
    for raw in list(blocks)[:30]:
        text = raw.strip()
        if not text or len(text) > 2_000_000:
            continue
        text = re.sub(r"^\s*(?:<!--|<!\[CDATA\[)|(?:-->|\]\]>)\s*$", "", text)
        try:
            data = json.loads(text)
        except ValueError:
            continue
        stack: List[Any] = [data]
        seen = 0
        while stack and seen < 5000:
            item = stack.pop()
            seen += 1
            if isinstance(item, list):
                stack.extend(reversed(item))
            elif isinstance(item, dict):
                if "@type" in item:
                    records.append(item)
                for key, value in item.items():
                    if isinstance(value, (dict, list)) and key not in ("offers", "review", "aggregateRating"):
                        stack.append(value)
    return records


def _types(record: dict) -> set:
    value = record.get("@type")
    if isinstance(value, str):
        return {value.split("/")[-1]}
    if isinstance(value, list):
        return {str(v).split("/")[-1] for v in value}
    return set()


def _text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("@value") or ""
    if isinstance(value, list):
        return ", ".join(t for t in (_text(v) for v in value[:4]) if t)
    return _clean(str(value)) if value not in (None, "") else ""


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _short_schema(value: Any) -> str:
    """``https://schema.org/InStock`` → ``in stock``."""
    text = _text(value)
    if not text:
        return ""
    token = text.rstrip("/").split("/")[-1]
    return re.sub(r"(?<!^)(?=[A-Z])", " ", token).lower()


def _money(amount: Any, currency: Any) -> str:
    amount_text = _text(amount)
    if not amount_text:
        return ""
    currency_text = _text(currency)
    return f"{amount_text} {currency_text}".strip()


def _offer_line(offer: Any) -> str:
    if not isinstance(offer, dict):
        return ""
    kinds = _types(offer)
    spec = offer.get("priceSpecification")
    spec = spec[0] if isinstance(spec, list) and spec else spec
    spec = spec if isinstance(spec, dict) else {}
    currency = offer.get("priceCurrency") or spec.get("priceCurrency")
    if "AggregateOffer" in kinds or ("lowPrice" in offer and "price" not in offer):
        low = _money(offer.get("lowPrice"), currency)
        high = _money(offer.get("highPrice"), currency)
        price = f"{low} – {high}" if low and high and low != high else (low or high)
        count = _text(offer.get("offerCount"))
        if count:
            price = f"{price} ({count} offers)" if price else f"{count} offers"
    else:
        price = _money(offer.get("price") or spec.get("price"), currency)
    details = [
        _short_schema(offer.get("availability")),
        _short_schema(offer.get("itemCondition")),
    ]
    seller = _text(offer.get("seller"))
    if seller:
        details.append(f"sold by {seller}")
    details = [d for d in details if d]
    if not price and not details:
        return ""
    return f"Price: {price or 'not listed'}" + (f" ({', '.join(details)})" if details else "")


def _product_facts(records: List[dict]) -> List[str]:
    lines: List[str] = []
    products = [r for r in records if _types(r) & {"Product", "ProductGroup", "IndividualProduct", "ProductModel", "Vehicle"}]
    shown = set()
    for product in products:
        name = _text(product.get("name")) or "Product"
        offers = [line for line in (_offer_line(o) for o in _as_list(product.get("offers"))[:5]) if line]
        # Pages often repeat the same product in several JSON-LD blocks.
        signature = (name, tuple(offers))
        if signature in shown:
            continue
        shown.add(signature)
        if len(shown) > _MAX_PRODUCTS:
            break
        brand = _text(product.get("brand"))
        lines.append(f"- **{name}**" + (f" (brand: {brand})" if brand and brand.lower() not in name.lower() else ""))
        lines.extend(f"  - {line}" for line in offers)
        rating = product.get("aggregateRating")
        if isinstance(rating, dict) and _text(rating.get("ratingValue")):
            best = _text(rating.get("bestRating")) or "5"
            count = _text(rating.get("reviewCount")) or _text(rating.get("ratingCount"))
            lines.append(
                f"  - Rating: {_text(rating.get('ratingValue'))}/{best}" + (f" from {count} reviews" if count else "")
            )
        ids = [f"{key} {_text(product.get(key))}" for key in ("model", "mpn", "sku", "gtin13", "gtin12", "gtin") if _text(product.get(key))]
        if ids:
            lines.append("  - " + ", ".join(ids[:3]))
        url = _text(product.get("url"))
        if url and len(products) > 1:
            lines.append(f"  - Link: {url}")
    if not products:
        for offer in (r for r in records if _types(r) & {"Offer", "AggregateOffer"}):
            line = _offer_line(offer)
            if line:
                lines.append(f"- {line}")
            if len(lines) >= 5:
                break
    return lines


def _meta_price_facts(meta: Dict[str, str], microdata: Dict[str, Union[str, _Element]]) -> List[str]:
    lines: List[str] = []
    for amount_key, currency_key in (("product:price:amount", "product:price:currency"), ("og:price:amount", "og:price:currency")):
        if meta.get(amount_key):
            lines.append(f"- Price (page metadata): {_money(meta[amount_key], meta.get(currency_key))}")
            break
    values = {
        key: (_clean(_plain_text(value)) if isinstance(value, _Element) else _clean(value))
        for key, value in microdata.items()
    }
    price = values.get("price") or (
        f"{values['lowPrice']} – {values['highPrice']}" if values.get("lowPrice") and values.get("highPrice") else values.get("lowPrice", "")
    )
    if price and not lines:
        line = f"- Price (page markup): {_money(price, values.get('priceCurrency'))}"
        availability = _short_schema(values.get("availability"))
        lines.append(line + (f" ({availability})" if availability else ""))
    availability = meta.get("product:availability") or meta.get("og:availability")
    if availability and lines:
        lines[0] += f" ({_short_schema(availability)})"
    return lines


def _published_line(records: List[dict], meta: Dict[str, str]) -> str:
    article_types = {"Article", "NewsArticle", "BlogPosting", "Report", "ScholarlyArticle", "TechArticle", "Review"}
    for record in records:
        if _types(record) & article_types:
            parts = []
            if _text(record.get("datePublished")):
                parts.append(f"Published: {_text(record.get('datePublished'))}")
            if _text(record.get("dateModified")) and record.get("dateModified") != record.get("datePublished"):
                parts.append(f"Updated: {_text(record.get('dateModified'))}")
            authors = _text(record.get("author"))
            if authors:
                parts.append(f"By: {authors}")
            if parts:
                return " · ".join(parts)
    published = meta.get("article:published_time")
    return f"Published: {published}" if published else ""
