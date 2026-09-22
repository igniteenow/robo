"""Dashboard sign-in page. Copyright (c) 2026 Ignitee Now.

Server-rendered and self-contained: no SPA bundle, no external requests except
the brand font the dashboard already serves from ``/brand-fonts/``. Shown before
authentication, so it must work with nothing but this HTML.

Contract (see ``tests/robo_cli/test_dashboard_auth_password_login.py``):

* ``render_login_html(next_path="")`` returns a complete HTML document.
* Providers come from ``registry.list_session_providers()``, in registration
  order.
* A provider with ``supports_password`` renders
  ``<form class="provider-form" data-provider="NAME">`` with ``username``,
  ``password`` and hidden ``next`` fields. The form posts JSON to
  ``/auth/password-login`` from a small inline script.
* Any other provider renders a ``provider-btn`` link to
  ``/auth/login?provider=NAME&next=...``.
* The script is emitted only when a password form exists, so a redirect-only
  sign-in page ships no JavaScript at all.

``next_path`` is validated by the route before it gets here; it is still
escaped on output, because this module does not trust its callers with HTML.
"""

from __future__ import annotations

from html import escape
from typing import Any, Iterable, List
from urllib.parse import urlencode

from robo_cli.dashboard_auth.registry import list_session_providers

PASSWORD_LOGIN_PATH = "/auth/password-login"
REDIRECT_LOGIN_PATH = "/auth/login"

# The Robo mark (assets/brand/robo-mark-plain.svg), inlined so the page needs no
# image request.
_MARK_SVG = (
    '<svg class="mark" viewBox="60 20 392 460" aria-hidden="true" focusable="false">'
    '<defs><linearGradient id="lf" x1="0" y1="1" x2="0" y2="0">'
    '<stop offset="0" stop-color="#D52734"/><stop offset=".55" stop-color="#DF5A30"/>'
    '<stop offset="1" stop-color="#F5A13A"/></linearGradient></defs>'
    '<circle cx="256" cy="290" r="170" fill="#3F3E98"/>'
    '<path fill="url(#lf)" d="M262 44c40 62 118 98 118 190 0 70-54 118-124 118s-124-48-124-118'
    'c0-52 30-86 62-116 2 40 16 62 40 72-12-52-4-102 28-146z"/>'
    '<rect x="120" y="292" width="20" height="52" rx="8" fill="#8E8CE0"/>'
    '<rect x="372" y="292" width="20" height="52" rx="8" fill="#8E8CE0"/>'
    '<rect x="136" y="216" width="240" height="200" rx="58" fill="#FFE9D6"/>'
    '<rect x="164" y="254" width="184" height="96" rx="42" fill="#0A1030"/>'
    '<rect x="198" y="282" width="40" height="40" rx="14" fill="url(#lf)"/>'
    '<rect x="274" y="282" width="40" height="40" rx="14" fill="url(#lf)"/>'
    '<rect x="230" y="372" width="52" height="10" rx="5" fill="#3F3E98"/></svg>'
)

# Plain string, not an f-string: CSS braces stay literal.
_STYLE = """
@font-face{font-family:'Poppins';font-weight:400;font-display:swap;src:url('/brand-fonts/Poppins-Regular.woff') format('woff')}
@font-face{font-family:'Poppins';font-weight:500;font-display:swap;src:url('/brand-fonts/Poppins-Medium.woff') format('woff')}
@font-face{font-family:'Poppins';font-weight:700;font-display:swap;src:url('/brand-fonts/Poppins-Bold.woff') format('woff')}
:root{--navy:#0a1030;--panel:#0e1437;--line:#1e255c;--indigo:#8e8ce0;--ember:#ef8a22;--flame:#d52734;--ink:#ffe9d6;--muted:#a9aecf;--danger:#f0525f}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{display:grid;place-items:center;padding:24px;background:var(--navy);color:var(--ink);
  font:400 15px/1.55 'Poppins',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  background-image:radial-gradient(60rem 30rem at 50% -10%,rgba(239,138,34,.13),transparent 60%),
    linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);
  background-size:auto,44px 44px,44px 44px;background-position:center,-1px -1px,-1px -1px}
main{width:100%;max-width:26rem;padding:32px 28px 28px;border:1px solid var(--line);border-radius:18px;
  background:color-mix(in srgb,var(--panel) 94%,transparent);box-shadow:0 30px 70px -30px #000}
.brand{display:flex;align-items:center;gap:14px;margin-bottom:22px}
.mark{width:52px;height:60px;flex:none}
.word{margin:0;font-weight:700;font-size:26px;letter-spacing:.04em;line-height:1;
  background:linear-gradient(90deg,var(--flame),#df5a30,var(--ember));-webkit-background-clip:text;background-clip:text;color:transparent}
.by{margin:4px 0 0;font-size:12px;letter-spacing:.06em;color:var(--muted)}
h1{margin:0 0 4px;font-size:18px;font-weight:500}
.lede{margin:0 0 20px;color:var(--muted);font-size:14px}
.providers{display:grid;gap:12px}
.provider-btn,.provider-form button{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;min-height:44px;
  padding:0 16px;border:1px solid transparent;border-radius:10px;font:500 15px/1 inherit;font-family:inherit;text-decoration:none;cursor:pointer;
  transition:background-color .15s,border-color .15s}
.provider-btn{border-color:color-mix(in srgb,var(--ink) 28%,transparent);background:transparent;color:var(--ink)}
.provider-btn:hover{background:color-mix(in srgb,var(--ink) 8%,transparent)}
.provider-form{display:grid;gap:10px;padding:16px;border:1px solid var(--line);border-radius:12px;background:color-mix(in srgb,#000 16%,var(--panel))}
.provider-form legend,.provider-form .title{font-weight:500;font-size:14px;padding:0}
.provider-form label{display:grid;gap:6px;font-size:13px;color:var(--muted)}
.provider-form input{width:100%;min-height:42px;padding:0 12px;border:1px solid color-mix(in srgb,var(--ink) 26%,transparent);border-radius:9px;
  background:color-mix(in srgb,#000 22%,var(--navy));color:var(--ink);font:inherit}
.provider-form button{background:var(--ember);color:var(--navy)}
.provider-form button:hover:not(:disabled){background:#f5a13a}
.provider-form button:disabled{opacity:.55;cursor:progress}
.provider-form .error{min-height:1.2em;margin:0;font-size:13px;color:var(--danger)}
a:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid var(--ember);outline-offset:2px}
.divider{display:flex;align-items:center;gap:12px;color:var(--muted);font-size:12px;letter-spacing:.08em;text-transform:uppercase}
.divider::before,.divider::after{content:"";flex:1;height:1px;background:var(--line)}
.empty{margin:0;padding:14px;border:1px dashed var(--line);border-radius:10px;color:var(--muted);font-size:14px}
footer{margin-top:22px;font-size:12px;color:var(--muted);text-align:center}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

# Posts the credential form as JSON. Kept dependency-free and small; it is only
# included when a password form is on the page.
_SCRIPT = """
(function(){
  var ENDPOINT = %(endpoint)s;
  var MESSAGES = {401:"That username or password is not right.",404:"This sign-in method is not available.",
                  429:"Too many attempts. Wait a minute, then try again."};
  document.querySelectorAll("form.provider-form").forEach(function(form){
    var error = form.querySelector(".error"), button = form.querySelector("button");
    form.addEventListener("submit", function(event){
      event.preventDefault();
      error.textContent = ""; button.disabled = true;
      var data = new FormData(form);
      fetch(ENDPOINT, {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({provider: form.dataset.provider, username: data.get("username") || "",
                              password: data.get("password") || "", next: data.get("next") || ""})})
      .then(function(response){
        if (!response.ok) throw response.status;
        return response.json();
      })
      .then(function(body){
        var target = (body && typeof body.next === "string" && body.next.charAt(0) === "/" && body.next.charAt(1) !== "/") ? body.next : "/";
        window.location.assign(target);
      })
      .catch(function(status){
        error.textContent = MESSAGES[status] || "Sign-in failed. Check your connection and try again.";
        button.disabled = false;
        var field = form.querySelector('input[name="password"]'); if (field) { field.value = ""; field.focus(); }
      });
    });
  });
})();
"""


def _attr(value: Any) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _label(provider: Any) -> str:
    return str(getattr(provider, "display_name", "") or getattr(provider, "name", "") or "Sign in")


def _render_password_form(provider: Any, next_path: str, index: int) -> str:
    name, label = _attr(getattr(provider, "name", "")), escape(_label(provider))
    uid, pid, eid = f"u{index}", f"p{index}", f"e{index}"
    return (
        f'<form class="provider-form" data-provider="{name}" novalidate aria-describedby="{eid}">'
        f'<div class="title">{label}</div>'
        f'<label for="{uid}">Username'
        f'<input id="{uid}" name="username" type="text" autocomplete="username" autocapitalize="none" spellcheck="false" required></label>'
        f'<label for="{pid}">Password'
        f'<input id="{pid}" name="password" type="password" autocomplete="current-password" required></label>'
        f'<input type="hidden" name="next" value="{_attr(next_path)}">'
        f'<p class="error" id="{eid}" role="alert" aria-live="assertive"></p>'
        f'<button type="submit">Sign in</button>'
        f"</form>"
    )


def _render_redirect_button(provider: Any, next_path: str) -> str:
    query = {"provider": str(getattr(provider, "name", ""))}
    if next_path:
        query["next"] = next_path
    href = f"{REDIRECT_LOGIN_PATH}?{urlencode(query)}"
    return f'<a class="provider-btn" href="{_attr(href)}">Continue with {escape(_label(provider))}</a>'


def _split(providers: Iterable[Any]) -> tuple[List[Any], List[Any]]:
    password, redirect = [], []
    for provider in providers:
        (password if getattr(provider, "supports_password", False) else redirect).append(provider)
    return password, redirect


def render_login_html(*, next_path: str = "") -> str:
    """Return the sign-in page for the currently registered session providers."""
    next_path = next_path or ""
    password, redirect = _split(list_session_providers())

    blocks: List[str] = [_render_password_form(p, next_path, i) for i, p in enumerate(password)]
    if password and redirect:
        blocks.append('<div class="divider" role="separator">or</div>')
    blocks.extend(_render_redirect_button(p, next_path) for p in redirect)
    if not blocks:
        blocks.append(
            '<p class="empty">No sign-in method is configured for this dashboard. '
            "Ask the person who runs this Robo gateway to enable one.</p>"
        )

    script = ""
    if password:
        import json

        script = "<script>" + _SCRIPT % {"endpoint": json.dumps(PASSWORD_LOGIN_PATH)} + "</script>"
        blocks.append("<noscript><p class=\"empty\">Password sign-in needs JavaScript turned on.</p></noscript>")

    return (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        '<meta name="color-scheme" content="dark">'
        "<title>Sign in · Robo</title>"
        f"<style>{_STYLE}</style></head>"
        "<body><main>"
        f'<div class="brand">{_MARK_SVG}<div><p class="word">ROBO</p><p class="by">by IGNITEE NOW</p></div></div>'
        "<h1>Sign in to your dashboard</h1>"
        '<p class="lede">Choose how you want to continue.</p>'
        f'<div class="providers">{"".join(blocks)}</div>'
        "<footer>This page is private to your Robo gateway.</footer>"
        f"</main>{script}</body></html>"
    )
