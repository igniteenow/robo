"""Robo's start-up banner. Copyright (c) 2026 Ignitee Now.

Presentation only. It draws what it is given: the model, the working folder,
tools grouped by toolset, anything unavailable and why, MCP servers, skills,
and an update notice. It gathers nothing over the network and runs no git
commands itself; the update checker in ``robo_cli.banner`` owns that.

``robo_cli.banner`` re-exports everything here, and remains the import path the
rest of the codebase uses. Collaborators that tests (and callers) replace on
that module — ``get_available_skills``, ``get_update_result``,
``get_latest_release_tag``, ``get_git_banner_state`` — are looked up through it
at call time, so a patch on ``robo_cli.banner`` reaches this code.

Every dynamic string is escaped before it enters Rich markup. Model names,
folder paths and skill names can contain ``[``, which Rich would otherwise read
as a tag.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from rich.console import Console

logger = logging.getLogger(__name__)

# ANSI accents for plain-terminal output (brand ember).
_GOLD = "\033[1;38;2;239;138;34m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RST = "\033[0m"

ROBO_AGENT_LOGO = """[bold #F5A13A]██████╗  ██████╗ ██████╗  ██████╗ [/]
[bold #EF8A22]██╔══██╗██╔═══██╗██╔══██╗██╔═══██╗[/]
[#E8742A]██████╔╝██║   ██║██████╔╝██║   ██║[/]
[#DF5A30]██╔══██╗██║   ██║██╔══██╗██║   ██║[/]
[#D93F32]██║  ██║╚██████╔╝██████╔╝╚██████╔╝[/]
[#D52734]╚═╝  ╚═╝ ╚═════╝ ╚═════╝  ╚═════╝ [/]"""

ROBO_HERO = """[bold #F5A13A]  ██████╗  ██████╗ ██████╗  ██████╗ [/]
[bold #EF8A22]  ██╔══██╗██╔═══██╗██╔══██╗██╔═══██╗[/]
[#E8742A]  ██████╔╝██║   ██║██████╔╝██║   ██║[/]
[#DF5A30]  ██╔══██╗██║   ██║██╔══██╗██║   ██║[/]
[#D93F32]  ██║  ██║╚██████╔╝██████╔╝╚██████╔╝[/]
[#D52734]  ╚═╝  ╚═╝ ╚═════╝ ╚═════╝  ╚═════╝ [/]
[#8E8CE0]  autonomous engineering agent · Ignitee Now[/]"""

_HERO_MIN_WIDTH = 100   # below this the art is dropped and the info takes the full width
_LOGO_MIN_WIDTH = 60
_MIN_NAMES_SHOWN = 3
_LIST_LINES = 2         # a name list may wrap to this many lines before "+N more"
_LABEL_MAX = 18         # longer row labels are ellipsized so one long name cannot widen the column


# ------------------------------------------------------------------------ small helpers
def cprint(text: str) -> None:
    """Print ANSI-coloured text through prompt_toolkit so it renders correctly
    while an interactive prompt is on screen. Falls back to ``print`` whenever
    prompt_toolkit is absent or has no console to write to."""
    try:
        from prompt_toolkit import print_formatted_text
        from prompt_toolkit.formatted_text import ANSI

        print_formatted_text(ANSI(text))
    except Exception:
        print(text)


def _skin_color(key: str, fallback: str) -> str:
    try:
        from robo_cli.skin_engine import get_active_skin

        return get_active_skin().get_color(key, fallback)
    except Exception:
        return fallback


def _skin_branding(key: str, fallback: str) -> str:
    try:
        from robo_cli.skin_engine import get_active_skin

        return get_active_skin().get_branding(key, fallback)
    except Exception:
        return fallback


def _host() -> Any:
    """The public banner module, through which patchable collaborators resolve."""
    module = sys.modules.get("robo_cli.banner")
    if module is None:
        import robo_cli.banner as module  # noqa: PLC0415
    return module


def _call_host(name: str, default: Any = None) -> Any:
    try:
        return getattr(_host(), name)()
    except Exception as exc:
        logger.debug("banner: %s() failed: %s", name, exc)
        return default


def _esc(value: Any) -> str:
    from rich.markup import escape

    return escape("" if value is None else str(value))


def _format_context_length(tokens: int) -> str:
    """128000 -> '128K', 1048576 -> '1M', 1500000 -> '1.5M', 900 -> '900'."""
    try:
        n = int(tokens)
    except (TypeError, ValueError):
        return str(tokens)
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{round(n / 1000)}K"
    millions = round(n / 1_000_000, 1)
    return f"{int(millions)}M" if millions == int(millions) else f"{millions}M"


def _display_toolset_name(toolset_name: str) -> str:
    """Internal ids such as ``file_tools`` read better as ``file``."""
    name = str(toolset_name or "").strip()
    for suffix in ("_tools", "-tools", "_toolset", "-toolset"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
            break
    return name or "other"


def get_available_skills() -> Dict[str, List[str]]:
    """Skill names grouped by category (``general`` when a skill has none).
    Platform and disabled-skill filtering is done by the skills tool."""
    try:
        import tools.skills_tool as skills_tool

        found = skills_tool._find_all_skills()
    except Exception as exc:
        logger.debug("banner: could not list skills: %s", exc)
        return {}
    grouped: Dict[str, List[str]] = {}
    for skill in found or []:
        if isinstance(skill, dict) and skill.get("name"):
            grouped.setdefault(str(skill.get("category") or "general"), []).append(str(skill["name"]))
    return grouped


def format_banner_version_label() -> str:
    """``Robo v3.0.0 (2026.9.1) · upstream 1a2b3c4d`` and, when the checkout has
    local commits, ``… · local 9f8e7d6c (+3)``."""
    try:
        from robo_cli import __release_date__, __version__
    except Exception:
        __version__, __release_date__ = "0", ""
    label = f"{_skin_branding('agent_name', 'Robo')} v{__version__}"
    if __release_date__:
        label += f" ({__release_date__})"
    state = _call_host("get_git_banner_state")
    if isinstance(state, dict) and state.get("upstream"):
        label += f" · upstream {state['upstream']}"
        local, ahead = state.get("local"), state.get("ahead") or 0
        if local and local != state["upstream"]:
            label += f" · local {local}" + (f" (+{ahead})" if ahead else "")
    return label


# ---------------------------------------------------------------------------- sections
def _fit_names(names: Sequence[str], width: int) -> str:
    """Join as many names as fit in ``_LIST_LINES`` lines of ``width`` columns,
    always showing a few, and say how many were left out."""
    names = [str(n) for n in names]
    budget = max(width, 20) * _LIST_LINES
    shown: List[str] = []
    used = 0
    for index, name in enumerate(names):
        remaining = len(names) - index - 1
        cost = len(name) + 2
        reserve = len(f"+{remaining} more") if remaining else 0
        if len(shown) >= _MIN_NAMES_SHOWN and used + cost + reserve > budget:
            break
        shown.append(name)
        used += cost
    text = ", ".join(_esc(n) for n in shown)
    hidden = len(names) - len(shown)
    return f"{text}, [dim]+{hidden} more[/]" if hidden > 0 else text


def _short(label: Any) -> str:
    text = str(label if label is not None else "")
    return text if len(text) <= _LABEL_MAX else text[: _LABEL_MAX - 1] + "…"


def _group_tools(tools: Iterable[dict], get_toolset_for_tool: Optional[Callable[[str], Any]]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if not name:
            continue
        toolset = None
        if get_toolset_for_tool is not None:
            try:
                toolset = get_toolset_for_tool(name)
            except Exception:
                toolset = None
        grouped.setdefault(_display_toolset_name(toolset or "other"), []).append(str(name))
    return grouped


def _model_line(model: str, provider: Optional[str], context_length: Optional[int]) -> str:
    text = str(model or "")
    if str(provider or "").lower() == "moa":
        label = f"MoA: {_esc(text)}"
        try:
            from robo_cli.config import load_config
            from robo_cli.moa_config import resolve_moa_preset

            preset = resolve_moa_preset(load_config(), text or None)
            references = preset.get("references") or preset.get("reference_models") or []
            if references:
                label += f" [dim]({len(references)} advisors)[/]"
        except Exception as exc:
            logger.debug("banner: MoA preset not resolved: %s", exc)
    else:
        label = _esc(text.rsplit("/", 1)[-1] if "/" in text else text)
    extras = [_esc(provider)] if provider and str(provider).lower() != "moa" else []
    if context_length:
        extras.append(f"{_format_context_length(context_length)} context")
    return label + (f" [dim]· {' · '.join(extras)}[/]" if extras else "")


def _update_line(result: Any, warn: str, dim: str) -> Optional[str]:
    if result in (None, 0, False):
        return None
    no_count = getattr(_host(), "UPDATE_AVAILABLE_NO_COUNT", object())
    if result == no_count or not isinstance(result, int) or result < 0:
        detail = "A newer Robo is available"
    else:
        detail = f"{result} update{'s' if result != 1 else ''} behind"
    command = "robo update"
    try:  # the right command differs by install type (git checkout, package manager, image)
        from robo_cli.config import recommended_update_command

        command = str(recommended_update_command() or command)
    except Exception as exc:
        logger.debug("banner: no recommended update command: %s", exc)
    return f"[bold {warn}]↑ {detail}[/] [{dim}]— run[/] [bold]{_esc(command)}[/]"


def build_welcome_banner(
    console: "Console",
    model: str,
    cwd: str,
    tools: List[dict] = None,
    enabled_toolsets: List[str] = None,
    session_id: str = None,
    get_toolset_for_tool=None,
    context_length: int = None,
    provider: str = None,
) -> None:
    """Print the start-up banner to ``console``."""
    from rich.panel import Panel
    from rich.table import Table

    border = _skin_color("banner_border", "#6462C4")
    title_c = _skin_color("banner_title", "#FFE9D6")
    accent = _skin_color("banner_accent", "#EF8A22")
    dim = _skin_color("banner_dim", "#8C91BD")
    text_c = _skin_color("banner_text", "#E6E3F5")
    label_c = _skin_color("session_label", "#A3A1EC")
    ok, warn, err = _skin_color("ui_ok", "#3FBF7F"), _skin_color("ui_warn", "#F2B441"), _skin_color("ui_error", "#F0626E")

    try:
        from robo_cli.skin_engine import get_active_skin

        skin = get_active_skin()
        hero_art, logo_art = skin.banner_hero or ROBO_HERO, skin.banner_logo or ROBO_AGENT_LOGO
    except Exception:
        hero_art, logo_art = ROBO_HERO, ROBO_AGENT_LOGO

    width = int(getattr(console, "width", 0) or 80)
    show_hero = width >= _HERO_MIN_WIDTH and bool(hero_art.strip())
    hero_width = max((len(_strip_markup(line)) for line in hero_art.splitlines()), default=0) if show_hero else 0
    label_width = 11
    list_width = max(24, width - hero_width - label_width - 12)

    rows: List[tuple] = []  # (label markup, value markup)

    def section(title: str, count: Optional[int] = None) -> None:
        rows.append(("", ""))
        rows.append((f"[bold {accent}]{title}[/]", f"[{dim}]{count}[/]" if count is not None else ""))

    rows.append((f"[{label_c}]Model[/]", f"[{text_c}]{_model_line(model, provider, context_length)}[/]"))
    rows.append((f"[{label_c}]Folder[/]", f"[{text_c}]{_esc(cwd)}[/]"))
    if session_id:
        rows.append((f"[{label_c}]Session[/]", f"[{dim}]{_esc(session_id)}[/]"))

    grouped = _group_tools(tools or [], get_toolset_for_tool)
    if grouped:
        section("Tools", sum(len(v) for v in grouped.values()))
        for toolset in sorted(grouped):
            rows.append((f"  [{dim}]{_esc(_short(toolset))}[/]", f"[{text_c}]{_fit_names(sorted(grouped[toolset]), list_width)}[/]"))
    elif enabled_toolsets:
        section("Toolsets", len(enabled_toolsets))
        rows.append(("", f"[{text_c}]{_fit_names([_display_toolset_name(t) for t in enabled_toolsets], list_width)}[/]"))

    try:
        import model_tools

        _available, unavailable = model_tools.check_tool_availability(quiet=True)
    except TypeError:
        _available, unavailable = model_tools.check_tool_availability()
    except Exception as exc:
        logger.debug("banner: tool availability unknown: %s", exc)
        unavailable = []
    wanted = {str(t) for t in enabled_toolsets} if enabled_toolsets else None
    missing = [u for u in unavailable or [] if isinstance(u, dict) and (wanted is None or str(u.get("name")) in wanted)]
    if missing:
        section("Unavailable", len(missing))
        for item in missing:
            needs = ", ".join(str(v) for v in (item.get("env_vars") or []))
            reason = f"needs {_esc(needs)}" if needs else "not configured"
            rows.append((f"  [{err}]{_esc(_short(_display_toolset_name(item.get('name'))))}[/]", f"[{dim}]{reason}[/]"))

    try:
        import tools.mcp_tool as mcp_tool

        servers = mcp_tool.get_mcp_status() or []
    except Exception as exc:
        logger.debug("banner: MCP status unknown: %s", exc)
        servers = []
    if servers:
        section("MCP servers", len(servers))
        for server in servers:
            if not isinstance(server, dict):
                continue
            if server.get("disabled"):
                state = f"[{dim}]disabled[/]"
            elif server.get("connected"):
                count = server.get("tools")
                count = len(count) if isinstance(count, (list, tuple)) else count
                state = f"[{ok}]connected[/]" + (f" [{dim}]· {count} tools[/]" if count else "")
            else:
                state = f"[{warn}]{_esc(server.get('status') or 'not connected')}[/]"
            transport = f"[{dim}]{_esc(server.get('transport'))} ·[/] " if server.get("transport") else ""
            rows.append((f"  [{dim}]{_esc(_short(server.get('name')))}[/]", f"{transport}{state}"))

    skills = _call_host("get_available_skills", {}) or {}
    if skills:
        section("Skills", sum(len(v) for v in skills.values()))
        for category in sorted(skills):
            label = _short(category)
            room = list_width - max(0, len(label) + 2 - label_width)
            rows.append((f"  [{dim}]{_esc(label)}[/]", f"[{text_c}]{_fit_names(sorted(skills[category]), room)}[/]"))

    notice = _update_line(_call_host("get_update_result"), warn, dim)
    if notice:
        rows.append(("", ""))
        rows.append(("", notice))

    info = Table.grid(padding=(0, 2))
    info.add_column(no_wrap=True, min_width=label_width)
    info.add_column(overflow="fold")
    for left, right in rows:
        info.add_row(left, right)

    if show_hero:
        body = Table.grid(padding=(0, 3))
        body.add_column(no_wrap=True)
        body.add_column()
        body.add_row(hero_art, info)
    else:
        body = info

    label = _esc(format_banner_version_label())
    release = _call_host("get_latest_release_tag")
    url = None
    if isinstance(release, (tuple, list)) and len(release) >= 2:
        url = release[1]
    elif isinstance(release, dict):
        url = release.get("url")
    elif isinstance(release, str) and release:
        base = getattr(_host(), "_RELEASE_URL_BASE", "")
        url = f"{base.rstrip('/')}/{release}" if base else None
    title = f"[bold {title_c}]{label}[/]"
    if url:
        title = f"[link={_esc(url)}]{title}[/link]"

    if width >= _LOGO_MIN_WIDTH and logo_art.strip():
        console.print(logo_art)
    console.print(Panel(body, title=title, title_align="left", border_style=border, padding=(1, 2)))
    welcome = _skin_branding("welcome", "")
    if welcome:
        console.print(f"  [{dim}]{_esc(welcome)}[/]")


def _strip_markup(line: str) -> str:
    try:
        from rich.text import Text

        return Text.from_markup(line).plain
    except Exception:
        return line
