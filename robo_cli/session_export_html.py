"""Export Robo sessions as a single, self-contained HTML file.
Copyright (c) 2026 Ignitee Now.

The file is meant to be emailed, archived or opened straight from disk, so it
carries its own styles and script and makes no network requests.

Security model: everything that came from a model, a tool or a user is treated
as hostile. Every dynamic value is HTML-escaped at the point of output, CSS
class names are chosen from a fixed allow-list, and **no dynamic value is ever
written into the <script> block** — the script reads what it needs from the DOM.

Public API: ``generate_html_export(session)`` and
``generate_multi_session_html_export(sessions)``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from html import escape
from typing import Any, Dict, Iterable, List

_KNOWN_ROLES = {"user": "You", "assistant": "Robo", "tool": "Tool result", "system": "System"}
_LONG_TOOL_OUTPUT = 600  # characters; longer tool results start collapsed


# --------------------------------------------------------------------------- helpers
def _escape_html(text: Any) -> str:
    return escape("" if text is None else str(text), quote=True)


def _format_timestamp(ts: Any) -> str:
    """Seconds since the epoch -> local 'YYYY-MM-DD HH:MM'. Empty for missing or
    unusable values; strings are passed through for the caller to escape."""
    if ts in (None, "", 0, 0.0):
        return ""
    if isinstance(ts, str):
        return ts
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, TypeError, ValueError):
        return ""


def _role_token(role: Any) -> str:
    """A safe CSS token for the role: a known role, or 'other'."""
    role = str(role or "").strip().lower()
    return role if role in _KNOWN_ROLES else "other"


def _plain_text(content: Any) -> str:
    """Flatten message content (string, or a list of typed parts) to text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: List[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    chunks.append(part["text"])
                elif part.get("type"):
                    chunks.append(f"[{part.get('type')}]")
        return "\n".join(chunks)
    if isinstance(content, (dict, tuple)):
        return json.dumps(content, indent=2, ensure_ascii=False, default=str)
    return str(content)


_FENCE = re.compile(r"```([^\n`]*)\n(.*?)(?:```|\Z)", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")


def _render_text(raw: str) -> str:
    """Escape first, then apply a tiny, safe subset of Markdown: fenced code,
    inline code and bold. Formatting only ever wraps already-escaped text."""
    out: List[str] = []
    cursor = 0
    for match in _FENCE.finditer(raw):
        out.append(_render_inline(raw[cursor:match.start()]))
        lang = _escape_html(match.group(1).strip())
        label = f'<span class="lang">{lang}</span>' if lang else ""
        out.append(f'<pre class="code">{label}<code>{_escape_html(match.group(2).rstrip())}</code></pre>')
        cursor = match.end()
    out.append(_render_inline(raw[cursor:]))
    return "".join(out)


def _render_inline(raw: str) -> str:
    if not raw.strip():
        return ""
    text = _escape_html(raw.strip("\n"))
    text = _INLINE_CODE.sub(r"<code>\1</code>", text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    return f'<div class="text">{text}</div>'


def _pretty_arguments(arguments: Any) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (TypeError, ValueError):
            return arguments
    try:
        return json.dumps(arguments, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(arguments)


def _render_tool_calls(tool_calls: Any) -> str:
    if not isinstance(tool_calls, list):
        return ""
    blocks: List[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = function.get("name") or call.get("name") or "tool"
        arguments = function.get("arguments", call.get("arguments", ""))
        blocks.append(
            '<details class="tool-call"><summary><span class="chip">tool</span> '
            f'<span class="tool-name">{_escape_html(name)}</span></summary>'
            f'<pre class="code"><code>{_escape_html(_pretty_arguments(arguments))}</code></pre></details>'
        )
    return "".join(blocks)


def _render_message(message: Dict[str, Any]) -> str:
    token = _role_token(message.get("role"))
    raw_role = message.get("role")
    label = _KNOWN_ROLES.get(token) or (str(raw_role) if raw_role else "Message")
    if token == "tool" and message.get("name"):
        label = f"{label} · {message.get('name')}"
    when = _format_timestamp(message.get("timestamp"))

    body: List[str] = []
    reasoning = message.get("reasoning") or message.get("reasoning_content")
    if reasoning:
        body.append(f'<details class="reasoning"><summary>Reasoning</summary>{_render_text(_plain_text(reasoning))}</details>')

    text = _plain_text(message.get("content"))
    if token == "tool" and len(text) > _LONG_TOOL_OUTPUT:
        body.append(f'<details class="tool-output"><summary>Output ({len(text):,} characters)</summary>{_render_text(text)}</details>')
    else:
        body.append(_render_text(text))
    body.append(_render_tool_calls(message.get("tool_calls")))

    time_html = f'<time class="when">{_escape_html(when)}</time>' if when else ""
    return (
        f'<article class="message message-{token} active" data-role="{token}">'
        f'<header class="meta"><span class="role">{_escape_html(label)}</span>{time_html}</header>'
        f'{"".join(body)}</article>'
    )


def _generate_messages_html(messages: List[Dict[str, Any]]) -> str:
    return "".join(_render_message(m) for m in (messages or []) if isinstance(m, dict))


# ----------------------------------------------------------------------------- page
_MARK = (
    '<svg class="mark" viewBox="60 20 392 460" aria-hidden="true"><defs><linearGradient id="xf" x1="0" y1="1" x2="0" y2="0">'
    '<stop offset="0" stop-color="#D52734"/><stop offset=".55" stop-color="#DF5A30"/><stop offset="1" stop-color="#F5A13A"/>'
    '</linearGradient></defs><circle cx="256" cy="290" r="170" fill="#3F3E98"/>'
    '<path fill="url(#xf)" d="M262 44c40 62 118 98 118 190 0 70-54 118-124 118s-124-48-124-118c0-52 30-86 62-116 2 40 16 62 40 72-12-52-4-102 28-146z"/>'
    '<rect x="136" y="216" width="240" height="200" rx="58" fill="#FFE9D6"/><rect x="164" y="254" width="184" height="96" rx="42" fill="#0A1030"/>'
    '<rect x="198" y="282" width="40" height="40" rx="14" fill="url(#xf)"/><rect x="274" y="282" width="40" height="40" rx="14" fill="url(#xf)"/></svg>'
)

_STYLE = """
:root{--bg:#0a1030;--panel:#0e1437;--raised:#141a45;--line:#1e255c;--ink:#ffe9d6;--muted:#a9aecf;--accent:#ef8a22;--indigo:#8e8ce0;--code:#070b24;--ok:#3fbf7f}
:root[data-theme="light"]{--bg:#fff8f1;--panel:#ffffff;--raised:#fbf0e4;--line:#eadccb;--ink:#0a1030;--muted:#4b4f7a;--accent:#b5470f;--indigo:#3f3e98;--code:#0e1437;--ok:#1f7a4d}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:400 15px/1.6 Poppins,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.shell{display:flex;min-height:100vh}
.sidebar{flex:none;width:17rem;padding:16px;border-right:1px solid var(--line);background:var(--panel);position:sticky;top:0;height:100vh;overflow:auto}
.sidebar h2{margin:0 0 10px;font-size:12px;font-weight:500;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.session-link{display:block;width:100%;margin:0 0 6px;padding:9px 11px;border:1px solid transparent;border-radius:9px;background:transparent;color:var(--ink);font:inherit;font-size:14px;text-align:left;cursor:pointer}
.session-link:hover{background:var(--raised)}
.session-link[aria-current="true"]{border-color:var(--accent);background:var(--raised)}
.session-link small{display:block;color:var(--muted);font-size:12px}
main{flex:1;min-width:0;max-width:60rem;margin:0 auto;padding:24px 20px 64px}
.top{display:flex;align-items:center;gap:14px;margin-bottom:18px}
.mark{width:40px;height:46px;flex:none}
.top h1{margin:0;font-size:20px;font-weight:600;line-height:1.25}
.facts{margin:2px 0 0;color:var(--muted);font-size:13px}
.bar{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 -8px 16px;padding:10px 8px;background:color-mix(in srgb,var(--bg) 92%,transparent);backdrop-filter:blur(6px);border-bottom:1px solid var(--line)}
.bar input[type=search]{flex:1;min-width:10rem;height:34px;padding:0 11px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);font:inherit;font-size:14px}
.bar button,.filter{height:34px;padding:0 11px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);font:inherit;font-size:13px;cursor:pointer}
.filter[aria-pressed="false"]{opacity:.45;text-decoration:line-through}
.bar button:hover,.filter:hover{border-color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.session-view{display:none}.session-view.active{display:block}
.message{display:none;margin:0 0 12px;padding:12px 14px;border:1px solid var(--line);border-left-width:3px;border-radius:10px;background:var(--panel)}
.message.active{display:block}
.message.hit-miss{display:none}
.message-user{border-left-color:var(--indigo)}
.message-assistant{border-left-color:var(--accent)}
.message-tool{border-left-color:var(--ok);background:var(--raised)}
.message-system,.message-other{border-left-color:var(--muted);background:var(--raised)}
.meta{display:flex;justify-content:space-between;gap:12px;margin-bottom:4px;font-size:12px;color:var(--muted)}
.role{font-weight:600;letter-spacing:.04em;text-transform:uppercase}
.message-assistant .role{color:var(--accent)}.message-user .role{color:var(--indigo)}
.text{white-space:pre-wrap;overflow-wrap:anywhere}
.text+.text,.code+.text,.text+.code{margin-top:8px}
code{font:13px/1.5 "JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.text code{padding:.1em .35em;border-radius:5px;background:var(--raised)}
.code{position:relative;margin:8px 0 0;padding:12px;border-radius:8px;background:var(--code);color:#ffe9d6;overflow:auto}
.lang{position:absolute;top:6px;right:10px;font-size:11px;color:#a9aecf}
details{margin-top:8px;border:1px solid var(--line);border-radius:8px;background:var(--raised)}
summary{padding:7px 11px;cursor:pointer;font-size:13px;color:var(--muted)}
details>.text,details>.code{margin:0 10px 10px}
.chip{padding:1px 7px;border-radius:999px;background:var(--accent);color:var(--bg);font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase}
.tool-name{font-family:"JetBrains Mono",ui-monospace,monospace;color:var(--ink)}
.none{padding:24px;border:1px dashed var(--line);border-radius:10px;color:var(--muted);text-align:center}
footer{margin-top:28px;color:var(--muted);font-size:12px;text-align:center}
@media (max-width:760px){.shell{display:block}.sidebar{position:static;width:auto;height:auto;border-right:0;border-bottom:1px solid var(--line)}}
@media print{.bar,.sidebar{display:none}.session-view{display:block!important;break-after:page}.message{display:block!important;break-inside:avoid;background:#fff;color:#000;border-color:#bbb}
  body{background:#fff;color:#000}details{border-color:#bbb;background:#fff}details>summary{list-style:none}.code{background:#f3f3f3;color:#000}}
"""

# Static text. It never receives interpolated values; it reads ids from the DOM.
_SCRIPT = """
function showSession(id) {
  document.querySelectorAll(".session-view").forEach(function (v) { v.classList.toggle("active", v.id === "view-" + id); });
  document.querySelectorAll(".session-link").forEach(function (b) { b.setAttribute("aria-current", String(b.dataset.id === id)); });
  window.scrollTo(0, 0);
}
(function () {
  var root = document.documentElement;
  document.querySelectorAll(".session-link").forEach(function (b) { b.addEventListener("click", function () { showSession(b.dataset.id); }); });
  var theme = document.getElementById("theme");
  if (theme) theme.addEventListener("click", function () { root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light"; });
  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) root.dataset.theme = "light";
  document.querySelectorAll(".filter").forEach(function (f) {
    f.addEventListener("click", function () {
      var on = f.getAttribute("aria-pressed") !== "true"; f.setAttribute("aria-pressed", String(on));
      document.querySelectorAll('.message[data-role="' + f.dataset.role + '"]').forEach(function (m) { m.classList.toggle("active", on); });
    });
  });
  var search = document.getElementById("search");
  if (search) search.addEventListener("input", function () {
    var q = search.value.trim().toLowerCase();
    document.querySelectorAll(".message").forEach(function (m) { m.classList.toggle("hit-miss", q !== "" && m.textContent.toLowerCase().indexOf(q) === -1); });
  });
  var toggle = document.getElementById("expand");
  if (toggle) toggle.addEventListener("click", function () {
    var open = toggle.dataset.open !== "true"; toggle.dataset.open = String(open); toggle.textContent = open ? "Collapse all" : "Expand all";
    document.querySelectorAll("details").forEach(function (d) { d.open = open; });
  });
  var print = document.getElementById("print"); if (print) print.addEventListener("click", function () { window.print(); });
})();
"""


def _session_title(session: Dict[str, Any]) -> str:
    return str(session.get("title") or session.get("preview") or session.get("id") or "Untitled session")


def _session_facts(session: Dict[str, Any]) -> str:
    messages = session.get("messages") or []
    facts = [
        _format_timestamp(session.get("started_at") or session.get("created_at")),
        str(session.get("model") or ""),
        str(session.get("source") or ""),
        f"{len(messages):,} message{'s' if len(messages) != 1 else ''}",
    ]
    return " · ".join(_escape_html(f) for f in facts if f)


def _toolbar(roles: Iterable[str]) -> str:
    present = [r for r in ("user", "assistant", "tool", "system", "other") if r in set(roles)]
    filters = "".join(
        f'<button type="button" class="filter" data-role="{r}" aria-pressed="true">{_escape_html(_KNOWN_ROLES.get(r, "Other"))}</button>'
        for r in present
    )
    return (
        '<div class="bar" role="toolbar" aria-label="View options">'
        '<input id="search" type="search" placeholder="Search this export" aria-label="Search messages">'
        f"{filters}"
        '<button type="button" id="expand" data-open="false">Expand all</button>'
        '<button type="button" id="theme">Light / dark</button>'
        '<button type="button" id="print">Print</button></div>'
    )


def _session_view(session: Dict[str, Any], *, active: bool) -> str:
    messages = [m for m in (session.get("messages") or []) if isinstance(m, dict)]
    body = _generate_messages_html(messages) or '<p class="none">This session has no messages.</p>'
    sid = _escape_html(session.get("id") or "session")
    return (
        f'<section class="session-view{" active" if active else ""}" id="view-{sid}">'
        f'<div class="top">{_MARK}<div><h1>{_escape_html(_session_title(session))}</h1>'
        f'<p class="facts">{_session_facts(session)}</p></div></div>{body}</section>'
    )


def _document(title: str, sidebar: str, views: str, roles: Iterable[str]) -> str:
    exported = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        '<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="generator" content="Robo by Ignitee Now">'
        f"<title>{_escape_html(title)}</title><style>{_STYLE}</style></head><body>"
        f'<div class="shell">{sidebar}<main>{_toolbar(roles)}{views}'
        f"<footer>Exported from Robo on {_escape_html(exported)}. This file is self-contained and makes no network requests.</footer>"
        f"</main></div><script>{_SCRIPT}</script></body></html>"
    )


def _roles_in(sessions: Iterable[Dict[str, Any]]) -> List[str]:
    return [_role_token(m.get("role")) for s in sessions for m in (s.get("messages") or []) if isinstance(m, dict)]


def generate_html_export(session_data: Dict[str, Any]) -> str:
    """One session as a standalone HTML document."""
    session = session_data if isinstance(session_data, dict) else {}
    return _document(f"{_session_title(session)} · Robo", "", _session_view(session, active=True), _roles_in([session]))


def generate_multi_session_html_export(sessions: List[Dict[str, Any]]) -> str:
    """Several sessions in one document, with a sidebar to switch between them."""
    sessions = [s for s in (sessions or []) if isinstance(s, dict)]
    links: List[str] = []
    for index, session in enumerate(sessions):
        sid = _escape_html(session.get("id") or "session")
        when = _escape_html(_format_timestamp(session.get("started_at") or session.get("created_at")))
        links.append(
            f'<button type="button" class="session-link" data-id="{sid}" aria-current="{"true" if index == 0 else "false"}">'
            f'{_escape_html(_session_title(session))}<small>{when}</small></button>'
        )
    sidebar = f'<nav class="sidebar" aria-label="Sessions"><h2>{len(sessions):,} sessions</h2>{"".join(links)}</nav>'
    views = "".join(_session_view(s, active=(i == 0)) for i, s in enumerate(sessions))
    if not sessions:
        views = '<p class="none">No sessions to show.</p>'
    return _document(f"{len(sessions)} sessions · Robo", sidebar, views, _roles_in(sessions))
