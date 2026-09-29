"""Turn an MCP server snippet pasted from any MCP client's docs into Robo config.

MCP servers publish their setup as JSON for Claude Desktop / Claude Code
(``{"mcpServers": {...}}``), VS Code (``{"servers": {...}}`` or
``{"mcp": {"servers": {...}}}``), Cursor, Windsurf (``serverUrl``), Gemini CLI
(``httpUrl``), Zed (``context_servers``) — or as Robo's own YAML. The dashboard
"Import" box accepts any of those so a user can add whatever server they want
without translating it by hand. Output entries use the ``mcp_servers`` shape
``tools/mcp_tool.py`` reads.

Pure helpers: the dashboard route does the profile scoping, saving and
``.env`` writes.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

__all__ = [
    "McpImportError",
    "parse_mcp_import",
    "normalize_mcp_entry",
    "secure_mcp_headers",
    "split_command_line",
]


class McpImportError(ValueError):
    """The pasted text (or one server in it) can't be turned into config."""


# Keys ``tools/mcp_tool.py`` understands that are copied through unchanged.
_PASSTHROUGH_KEYS = (
    "cwd",
    "timeout",
    "connect_timeout",
    "enabled",
    "tools",
    "ssl_verify",
    "client_cert",
    "client_key",
    "supports_parallel_tool_calls",
    "skip_preflight",
    "keepalive_interval",
    "lazy",
    "lifecycle",
    "sampling",
    "elicitation",
    "oauth",
    "auth",
)

# Where other MCP clients put a remote server's address.
_URL_KEYS = ("url", "serverUrl", "httpUrl", "server_url", "endpoint")

# Wrappers other clients put the name -> server map under.
_MAP_KEYS = ("mcpServers", "mcp_servers", "servers", "context_servers")

_SECRET_HEADER_RE = re.compile(
    r"auth|token|secret|password|passwd|credential|api[-_]?key|apikey|(^|[-_])key$",
    re.IGNORECASE,
)


def split_command_line(text: str) -> List[str]:
    """Split a command line on whitespace, keeping quoted parts together.

    Unlike ``shlex.split`` backslashes are literal, so Windows paths such as
    ``"C:\\Program Files\\nodejs\\npx.cmd"`` survive intact.
    """
    parts: List[str] = []
    current: List[str] = []
    quote: Optional[str] = None
    has_token = False
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
            else:
                current.append(ch)
        elif ch in ("'", '"'):
            quote = ch
            has_token = True
        elif ch.isspace():
            if has_token:
                parts.append("".join(current))
                current, has_token = [], False
        else:
            current.append(ch)
            has_token = True
    if quote:
        raise McpImportError(f"Unclosed {quote} quote in: {text}")
    if has_token:
        parts.append("".join(current))
    return parts


def _load_text(text: str) -> Any:
    text = text.strip().lstrip("\ufeff")
    if not text:
        raise McpImportError("Paste an MCP server configuration first.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as json_exc:
        # Docs often show just the inner part: `"github": { ... }`.
        if text.startswith('"'):
            try:
                return json.loads("{" + text.rstrip(",") + "}")
            except json.JSONDecodeError:
                pass
        # Robo's own docs use YAML; YAML also forgives trailing commas.
        try:
            import yaml

            data = yaml.safe_load(text)
        except Exception:
            data = None
        if isinstance(data, dict):
            return data
        raise McpImportError(
            f"Not valid JSON: {json_exc.msg} (line {json_exc.lineno}, "
            f"column {json_exc.colno})."
        ) from json_exc


def _looks_like_entry(value: Any) -> bool:
    return isinstance(value, dict) and (
        "command" in value or any(k in value for k in _URL_KEYS)
    )


def parse_mcp_import(raw: Any) -> Dict[str, Any]:
    """Return ``{name: raw entry}`` from pasted text or an already-parsed object."""
    data = _load_text(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise McpImportError(
            "Expected a JSON object such as {\"mcpServers\": {\"name\": {...}}}."
        )
    for key in _MAP_KEYS:
        if isinstance(data.get(key), dict):
            servers = data[key]
            break
    else:
        nested = data.get("mcp")
        if isinstance(nested, dict) and isinstance(nested.get("servers"), dict):
            servers = nested["servers"]
        elif _looks_like_entry(data):
            name = str(data.get("name") or "").strip()
            if not name:
                raise McpImportError(
                    'This is a single server with no name. Add "name": "..." '
                    'or wrap it as {"my-server": { ... }}.'
                )
            servers = {name: {k: v for k, v in data.items() if k != "name"}}
        elif data and all(isinstance(v, dict) for v in data.values()):
            servers = data
        else:
            raise McpImportError(
                "No MCP servers found. Expected {\"mcpServers\": {...}} or "
                "{\"server-name\": {\"command\": ...} / {\"url\": ...}}."
            )
    if not servers:
        raise McpImportError("The configuration lists no MCP servers.")
    return servers


def _as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _command_and_args(name: str, entry: Dict[str, Any]) -> tuple[str, List[str]]:
    command = entry.get("command")
    raw_args = entry.get("args")
    if isinstance(raw_args, str):
        args = split_command_line(raw_args)
    elif isinstance(raw_args, (list, tuple)):
        args = [_as_text(a) for a in raw_args if a is not None]
    elif raw_args is None:
        args = []
    else:
        raise McpImportError(f"Server '{name}': \"args\" must be a list.")

    if isinstance(command, (list, tuple)):
        parts = [_as_text(p) for p in command if p is not None]
        if not parts:
            raise McpImportError(f"Server '{name}': \"command\" is empty.")
        return parts[0], parts[1:] + args
    command = _as_text(command or "").strip()
    if not command:
        raise McpImportError(f"Server '{name}': \"command\" is empty.")
    # "npx -y @scope/server" in one string — split it, unless it's a real
    # path that happens to contain spaces (C:\Program Files\...).
    if not args and " " in command and not os.path.exists(command):
        parts = split_command_line(command)
        if parts:
            return parts[0], parts[1:]
    return command, args


def normalize_mcp_entry(name: str, entry: Any) -> Dict[str, Any]:
    """Convert one pasted server entry to a Robo ``mcp_servers`` entry."""
    if not name:
        raise McpImportError("Every server needs a name.")
    if not isinstance(entry, dict):
        raise McpImportError(f"Server '{name}': expected an object.")

    url = ""
    url_key = ""
    for key in _URL_KEYS:
        if entry.get(key):
            url, url_key = _as_text(entry[key]).strip(), key
            break
    has_command = bool(entry.get("command"))
    if url and has_command:
        raise McpImportError(
            f"Server '{name}' has both a command and a URL; keep one."
        )
    if not url and not has_command:
        raise McpImportError(
            f"Server '{name}' needs a \"command\" (local server) or a "
            f"\"url\" (remote server)."
        )

    cfg: Dict[str, Any] = {}
    kind = _as_text(entry.get("type") or entry.get("transport") or "").strip().lower()
    if url:
        if not re.match(r"^https?://", url, re.IGNORECASE):
            raise McpImportError(f"Server '{name}': URL must start with http:// or https://.")
        cfg["url"] = url
        if kind == "sse" or (
            not kind and url_key != "httpUrl" and url.split("?", 1)[0].rstrip("/").endswith("/sse")
        ):
            cfg["transport"] = "sse"
        headers = entry.get("headers")
        if headers is not None:
            if not isinstance(headers, dict):
                raise McpImportError(f"Server '{name}': \"headers\" must be an object.")
            clean = {
                str(k).strip(): _as_text(v)
                for k, v in headers.items()
                if str(k).strip() and v is not None
            }
            if clean:
                cfg["headers"] = clean
    else:
        command, args = _command_and_args(name, entry)
        cfg["command"] = command
        if args:
            cfg["args"] = args
        env = entry.get("env")
        if env is not None:
            if not isinstance(env, dict):
                raise McpImportError(f"Server '{name}': \"env\" must be an object.")
            clean_env = {
                str(k).strip(): _as_text(v)
                for k, v in env.items()
                if str(k).strip() and v is not None
            }
            if clean_env:
                cfg["env"] = clean_env

    for key in _PASSTHROUGH_KEYS:
        if key in entry and entry[key] is not None and key not in cfg:
            cfg[key] = entry[key]
    if cfg.get("auth") not in (None, "oauth"):
        # Other clients' auth shapes don't map onto Robo's; OAuth is the
        # only mode stored under this key.
        cfg.pop("auth", None)
    if entry.get("disabled") is True:
        cfg["enabled"] = False

    from robo_cli.mcp_security import validate_mcp_server_entry

    issues = validate_mcp_server_entry(name, cfg)
    if issues:
        raise McpImportError("; ".join(issues))
    return cfg


def _env_suffix(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text.upper()).strip("_")


def secure_mcp_headers(
    name: str,
    cfg: Dict[str, Any],
    save_env: Callable[[str, str], Any],
) -> Dict[str, Any]:
    """Move secret header values into ``.env`` and reference them from config.

    ``Authorization: Bearer X`` uses the same ``MCP_<NAME>_API_KEY`` variable
    the Add form's Bearer option writes, so the dashboard shows it as Bearer
    auth. Other credential-looking headers (``X-API-Key``, ``Authorization:
    Basic ...``) go to ``MCP_<NAME>_<HEADER>``. Values that are already
    ``${VAR}`` references and ordinary headers stay as they are.
    """
    headers = cfg.get("headers")
    if not isinstance(headers, dict) or not headers:
        return cfg
    from robo_cli.mcp_config import _bearer_auth_headers, _env_key_for_server

    secured: Dict[str, str] = {}
    for key, value in headers.items():
        text = _as_text(value)
        if "${" in text or not text.strip():
            secured[key] = text
            continue
        if key.lower() == "authorization" and text.strip()[:7].lower() == "bearer ":
            token = text.strip()[7:].strip()
            if token:
                save_env(_env_key_for_server(name), token)
                secured[key] = _bearer_auth_headers(name)["Authorization"]
                continue
        if _SECRET_HEADER_RE.search(key):
            env_key = f"MCP_{_env_suffix(name)}_{_env_suffix(key)}"
            save_env(env_key, text)
            secured[key] = "${" + env_key + "}"
            continue
        secured[key] = text
    out = dict(cfg)
    out["headers"] = secured
    return out
