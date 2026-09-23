"""Terminal skins for Robo. Copyright (c) 2026 Ignitee Now.

A skin is data: a colour palette, a few branding strings, spinner text, and
optional banner art. The engine resolves a skin by name, fills every gap from
the brand skin so callers never meet a missing key, and exposes the active skin
to the CLI, the TUI gateway and the prompt styling.

Where skins come from, in lookup order:

1. ``<robo home>/skins/<name>.yaml``   user skins; win over built-ins of the same name
2. built-ins                           defined below, from ``assets/brand/BRAND.md``
3. ``robo_runtime/resources/skins``    shipped YAML; merged over a same-named built-in
                                       (this is how ``robo`` gets its banner art)

Unknown names fall back to the brand skin and log a warning; malformed YAML
sections are ignored individually rather than rejecting the whole file. This
module is imported while the CLI starts, so nothing in it may raise on bad
input.

YAML format (every key optional)::

    name: my-skin
    description: One line.
    colors: {banner_title: "#RRGGBB", ...}     # see REQUIRED_COLOR_KEYS
    light_colors: {...}                        # overlay for light terminals
    dark_colors: {...}                         # overlay for dark terminals
    branding: {agent_name, welcome, goodbye, response_label, prompt_symbol, help_header}
    spinner: {waiting_faces: [...], thinking_faces: [...], thinking_verbs: [...], wings: [[l, r], ...]}
    tool_prefix: "┊"
    tool_emojis: {terminal: "⌘", ...}
    banner_logo: "rich markup"
    banner_hero: "rich markup"
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BRAND_SKIN = "robo"
# Older configs say ``skin: default``. Keep them working.
SKIN_ALIASES: Dict[str, str] = {"default": BRAND_SKIN, "": BRAND_SKIN}

# Every colour key a complete palette defines. Audited, with contrast floors,
# by tests/robo_cli/test_skin_palettes.py.
REQUIRED_COLOR_KEYS: Tuple[str, ...] = (
    "banner_border", "banner_title", "banner_accent", "banner_dim", "banner_text",
    "ui_accent", "ui_label", "ui_ok", "ui_error", "ui_warn",
    "prompt", "input_rule", "response_border",
    "status_bar_bg", "status_bar_text", "status_bar_strong", "status_bar_dim",
    "status_bar_good", "status_bar_warn", "status_bar_bad", "status_bar_critical",
    "session_label", "session_border",
    "completion_menu_bg", "completion_menu_current_bg", "selection_bg",
    "shell_dollar", "voice_status_bg",
)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


# --------------------------------------------------------------------- built-in data
def _palette(
    *, title: str, text: str, dim: str, line: str, accent: str, accent_soft: str, label: str,
    ok: str, warn: str, bad: str, critical: str, fill: str, fill_hi: str, selection: str,
    voice: Optional[str] = None, shell: Optional[str] = None,
) -> Dict[str, str]:
    """Expand a handful of seed colours into a complete palette."""
    return {
        "banner_border": line, "banner_title": title, "banner_accent": accent,
        "banner_dim": dim, "banner_text": text,
        "ui_accent": accent, "ui_primary": accent, "ui_label": label, "ui_ok": ok,
        "ui_error": critical, "ui_warn": warn, "ui_tool": accent_soft, "ui_thinking": label,
        "prompt": title, "input_rule": line, "response_border": accent_soft,
        "status_bar_bg": fill, "status_bar_text": text, "status_bar_strong": title,
        "status_bar_dim": dim, "status_bar_good": ok, "status_bar_warn": warn,
        "status_bar_bad": bad, "status_bar_critical": critical,
        "session_label": label, "session_border": line,
        "completion_menu_bg": fill, "completion_menu_current_bg": fill_hi,
        "selection_bg": selection, "shell_dollar": shell or accent,
        "voice_status_bg": voice or fill,
    }


_SPINNER_FACES = ["◐", "◓", "◑", "◒"]

_BUILTIN_SKINS: Dict[str, Dict[str, Any]] = {
    # The brand skin: navy, indigo structure, ember accent.
    "robo": {
        "name": "robo",
        "description": "Robo — navy, indigo and ember. The Ignitee Now look.",
        "colors": _palette(
            title="#FFE9D6", text="#E6E3F5", dim="#8C91BD", line="#6462C4",
            accent="#EF8A22", accent_soft="#E8742A", label="#A3A1EC",
            ok="#3FBF7F", warn="#F2B441", bad="#F08A4B", critical="#F0626E",
            fill="#0E1437", fill_hi="#2A2C73", selection="#2A2C73", voice="#141A45",
        ),
        # Fills-only flip for light terminals plus the foregrounds that need it.
        "light_colors": {
            "banner_border": "#8F88BD", "banner_title": "#0A1030", "banner_accent": "#B5470F",
            "banner_dim": "#5C6088", "banner_text": "#23264A", "ui_accent": "#B5470F",
            "ui_label": "#3F3E98", "ui_ok": "#1E7A46", "ui_error": "#B42332", "ui_warn": "#8F5400",
            "prompt": "#0A1030", "input_rule": "#8F88BD", "response_border": "#B5470F",
            "status_bar_bg": "#F3E9DD", "status_bar_text": "#23264A", "status_bar_strong": "#0A1030",
            "status_bar_dim": "#5C6088", "completion_menu_bg": "#F3E9DD",
            "completion_menu_current_bg": "#E2CDB5", "selection_bg": "#F6D9BC",
            "voice_status_bg": "#EFE3D5", "shell_dollar": "#B5470F",
        },
        "branding": {
            "agent_name": "Robo",
            "welcome": "Robo online — talk normally or assign an engineering task.",
            "goodbye": "Robo standing by.",
            "response_label": " ROBO ",
            "prompt_symbol": "❯",
            "help_header": "ROBO COMMAND DECK",
        },
        "spinner": {
            "waiting_faces": _SPINNER_FACES,
            "thinking_faces": _SPINNER_FACES,
            "thinking_verbs": ["analyzing", "tracing dependencies", "checking evidence", "planning", "verifying"],
            "wings": [],
        },
        "tool_prefix": "┊",
    },
    # Warm charcoal with the full flame.
    "ember": {
        "name": "ember",
        "description": "Ember — warm charcoal with the full Ignitee flame.",
        "colors": _palette(
            title="#FFD9B0", text="#F3E6DA", dim="#A8968A", line="#A8683E",
            accent="#F5A13A", accent_soft="#E8742A", label="#F0B07A",
            ok="#6CC08B", warn="#F2C14E", bad="#F59A5B", critical="#FF7A70",
            fill="#24180F", fill_hi="#4A2C17", selection="#5A3318", voice="#2B1B12",
        ),
        "branding": {
            "agent_name": "Robo", "welcome": "Robo is lit. What are we building?",
            "goodbye": "Embers banked. Robo standing by.", "response_label": " ROBO ",
            "prompt_symbol": "▲", "help_header": "ROBO COMMAND DECK",
        },
        "spinner": {
            "waiting_faces": ["·", "•", "●", "•"], "thinking_faces": ["·", "•", "●", "•"],
            "thinking_verbs": ["kindling", "forging", "tempering", "checking the weld"],
            "wings": [["« ", " »"], ["‹ ", " ›"]],
        },
        "tool_prefix": "▸",
    },
    # Cool and quiet: indigo-forward, lower saturation, for long sessions.
    "midnight": {
        "name": "midnight",
        "description": "Midnight — calm indigo for long sessions.",
        "colors": _palette(
            title="#F2F3FF", text="#DEE1F7", dim="#8A8FB8", line="#6B6ED0",
            accent="#A5A3F5", accent_soft="#8E8CE0", label="#9FB4F0",
            ok="#5FD0A0", warn="#F2C14E", bad="#F59A6B", critical="#FF7A8A",
            fill="#14183A", fill_hi="#2C3170", selection="#2F3478", voice="#191E48",
            shell="#EF8A22",
        ),
        "branding": {
            "agent_name": "Robo", "welcome": "Robo online. Quiet mode.",
            "goodbye": "Robo standing by.", "response_label": " ROBO ",
            "prompt_symbol": "◆", "help_header": "ROBO COMMAND DECK",
        },
        "spinner": {
            "waiting_faces": ["∙", "∘", "○", "∘"], "thinking_faces": ["∙", "∘", "○", "∘"],
            "thinking_verbs": ["thinking", "reading", "cross-checking", "drafting"], "wings": [],
        },
        "tool_prefix": "┆",
    },
    # Authored for light terminals.
    "paper": {
        "name": "paper",
        "description": "Paper — indigo ink and burnt ember on a light terminal.",
        "colors": _palette(
            title="#0A1030", text="#23264A", dim="#5C6088", line="#8F88BD",
            accent="#B5470F", accent_soft="#C8511A", label="#3F3E98",
            ok="#1E7A46", warn="#8F5400", bad="#B5470F", critical="#B42332",
            fill="#F3E9DD", fill_hi="#E2CDB5", selection="#F6D9BC", voice="#EFE3D5",
        ),
        "branding": {
            "agent_name": "Robo", "welcome": "Robo online — talk normally or assign an engineering task.",
            "goodbye": "Robo standing by.", "response_label": " ROBO ",
            "prompt_symbol": "❯", "help_header": "ROBO COMMAND DECK",
        },
        "spinner": {"waiting_faces": _SPINNER_FACES, "thinking_faces": _SPINNER_FACES,
                    "thinking_verbs": ["analyzing", "checking evidence", "planning"], "wings": []},
        "tool_prefix": "┊",
    },
    # Accessibility first: maximum contrast, colour never the only signal.
    "contrast": {
        "name": "contrast",
        "description": "Contrast — maximum legibility; pairs well with screen magnifiers.",
        "colors": _palette(
            title="#FFFFFF", text="#FFFFFF", dim="#C8C8C8", line="#A0A0A0",
            accent="#FFD23F", accent_soft="#FFFFFF", label="#7FDBFF",
            ok="#5CFF8F", warn="#FFD23F", bad="#FFA45C", critical="#FF8A8A",
            fill="#1C1C1C", fill_hi="#404040", selection="#404040", voice="#262626",
        ),
        "branding": {
            "agent_name": "Robo", "welcome": "Robo online.", "goodbye": "Robo standing by.",
            "response_label": " ROBO ", "prompt_symbol": ">", "help_header": "ROBO COMMANDS",
        },
        "spinner": {"waiting_faces": ["-", "\\", "|", "/"], "thinking_faces": ["-", "\\", "|", "/"],
                    "thinking_verbs": ["working"], "wings": []},
        "tool_prefix": "|",
    },
}

# Skins authored for a light terminal background (the rest are dark-authored).
LIGHT_AUTHORED_SKINS = frozenset({"paper"})


# ------------------------------------------------------------------------- the model
@dataclass
class SkinConfig:
    name: str = BRAND_SKIN
    description: str = ""
    colors: Dict[str, str] = field(default_factory=dict)
    light_colors: Dict[str, str] = field(default_factory=dict)
    dark_colors: Dict[str, str] = field(default_factory=dict)
    spinner: Dict[str, Any] = field(default_factory=dict)
    branding: Dict[str, str] = field(default_factory=dict)
    tool_prefix: str = "┊"
    tool_emojis: Dict[str, str] = field(default_factory=dict)
    banner_logo: str = ""
    banner_hero: str = ""

    def get_color(self, key: str, fallback: str = "") -> str:
        value = self.colors.get(key)
        return value if isinstance(value, str) and value else fallback

    def get_branding(self, key: str, fallback: str = "") -> str:
        value = self.branding.get(key)
        return value if isinstance(value, str) and value else fallback

    def get_spinner_wings(self) -> List[Tuple[str, str]]:
        """``[(left, right), ...]``; malformed and empty pairs are skipped."""
        wings = self.spinner.get("wings") if isinstance(self.spinner, dict) else None
        out: List[Tuple[str, str]] = []
        for pair in wings if isinstance(wings, list) else []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and (pair[0] or pair[1]):
                out.append((str(pair[0]), str(pair[1])))
        return out


# --------------------------------------------------------------------------- loading
def _skins_dir() -> Path:
    from robo_constants import get_robo_home

    return get_robo_home() / "skins"


def _load_skin_from_yaml(path: Path) -> Optional[Dict[str, Any]]:
    try:
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:  # unreadable, or not YAML
        logger.warning("Skin file %s could not be read: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("Skin file %s is not a mapping; ignored", path)
        return None
    return data


def _mapping_or_empty(value: Any, *, section: str, skin_name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    logger.warning("Skin %r: section %r should be a mapping, got %s; ignored", skin_name, section, type(value).__name__)
    return {}


def _string_map(value: Dict[str, Any]) -> Dict[str, str]:
    return {str(k): v for k, v in value.items() if isinstance(v, str) and v}


def _build_skin_config(data: Dict[str, Any]) -> SkinConfig:
    """Turn raw skin data into a complete SkinConfig.

    Colours, branding and spinner inherit from the brand skin, so a skin that
    sets three colours is still complete. Light/dark overlays, tool emojis and
    banner art are the skin's own: inheriting another palette's overlay or
    another skin's art would produce a mismatched look.
    """
    base = _BUILTIN_SKINS[BRAND_SKIN]
    name = str(data.get("name") or BRAND_SKIN)
    section = lambda key: _mapping_or_empty(data.get(key), section=key, skin_name=name)  # noqa: E731

    spinner = dict(copy.deepcopy(base.get("spinner", {})))
    spinner.update(section("spinner"))
    prefix = data.get("tool_prefix")

    return SkinConfig(
        name=name,
        description=str(data.get("description") or ""),
        colors={**base["colors"], **_string_map(section("colors"))},
        light_colors=_string_map(section("light_colors")),
        dark_colors=_string_map(section("dark_colors")),
        spinner=spinner,
        branding={**base["branding"], **_string_map(section("branding"))},
        tool_prefix=prefix if isinstance(prefix, str) and prefix else str(base.get("tool_prefix", "┊")),
        tool_emojis=_string_map(section("tool_emojis")),
        banner_logo=data.get("banner_logo") if isinstance(data.get("banner_logo"), str) else "",
        banner_hero=data.get("banner_hero") if isinstance(data.get("banner_hero"), str) else "",
    )


_resources_registered = False


def _register_resource_skins() -> None:
    """Merge shipped YAML skins into the built-ins. Safe to call repeatedly."""
    global _resources_registered
    if _resources_registered:
        return
    _resources_registered = True
    try:
        import robo_runtime

        root = Path(robo_runtime.__file__).resolve().parent / "resources" / "skins"
    except Exception as exc:
        logger.debug("No shipped skins directory: %s", exc)
        return
    if not root.is_dir():
        return
    for path in sorted(list(root.glob("*.yaml")) + list(root.glob("*.yml"))):
        data = _load_skin_from_yaml(path)
        if not data:
            continue
        name = str(data.get("name") or path.stem)
        if not _SAFE_NAME.match(name):
            logger.warning("Shipped skin %s has an unusable name; ignored", path)
            continue
        merged = copy.deepcopy(_BUILTIN_SKINS.get(name, {"name": name}))
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        merged["name"] = name
        _BUILTIN_SKINS[name] = merged


def _resolve(name: Any) -> str:
    text = str(name or "").strip()
    return SKIN_ALIASES.get(text.lower(), text)


def _user_skin_path(name: str) -> Optional[Path]:
    if not _SAFE_NAME.match(name):
        return None  # never build a path from something that could traverse
    try:
        directory = _skins_dir()
    except Exception as exc:
        logger.debug("No user skins directory: %s", exc)
        return None
    for suffix in (".yaml", ".yml"):
        candidate = directory / f"{name}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def load_skin(name: str) -> SkinConfig:
    """Resolve ``name`` to a complete skin. Never raises; unknown names return
    the brand skin."""
    _register_resource_skins()
    resolved = _resolve(name)

    path = _user_skin_path(resolved)
    if path is not None:
        data = _load_skin_from_yaml(path)
        if data is not None:
            data = {**data, "name": str(data.get("name") or resolved)}
            return _build_skin_config(data)

    if resolved in _BUILTIN_SKINS:
        return _build_skin_config(_BUILTIN_SKINS[resolved])

    logger.warning("Unknown skin %r; using %r", name, BRAND_SKIN)
    return _build_skin_config(_BUILTIN_SKINS[BRAND_SKIN])


def list_skins() -> List[Dict[str, str]]:
    """Built-ins first, then user skins. A user skin that shadows a built-in is
    listed once, as ``user``."""
    _register_resource_skins()
    found: Dict[str, Dict[str, str]] = {
        name: {"name": name, "description": str(data.get("description") or ""), "source": "builtin"}
        for name, data in _BUILTIN_SKINS.items()
    }
    try:
        directory = _skins_dir()
        files = sorted(list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))) if directory.is_dir() else []
    except Exception as exc:
        logger.debug("Could not list user skins: %s", exc)
        files = []
    for path in files:
        data = _load_skin_from_yaml(path)
        if data is None:
            continue
        name = str(data.get("name") or path.stem)
        if _SAFE_NAME.match(name):
            found[name] = {"name": name, "description": str(data.get("description") or ""), "source": "user"}
    return list(found.values())


# ------------------------------------------------------------------------ active skin
_active_skin: Optional[SkinConfig] = None
_active_skin_name: str = BRAND_SKIN


def get_active_skin() -> SkinConfig:
    global _active_skin
    if _active_skin is None:
        _active_skin = load_skin(_active_skin_name)
    return _active_skin


def set_active_skin(name: str) -> SkinConfig:
    global _active_skin, _active_skin_name
    skin = load_skin(name)
    _active_skin, _active_skin_name = skin, skin.name
    return skin


def get_active_skin_name() -> str:
    return _active_skin_name


def init_skin_from_config(config: dict) -> None:
    """Activate ``display.skin`` from the loaded config. Tolerates any shape."""
    display = config.get("display") if isinstance(config, dict) else None
    name = display.get("skin") if isinstance(display, dict) else None
    set_active_skin(str(name) if name else BRAND_SKIN)


def get_active_prompt_symbol(fallback: str = "❯") -> str:
    return get_active_skin().get_branding("prompt_symbol", fallback)


def get_active_help_header(fallback: str = "ROBO COMMAND DECK") -> str:
    return get_active_skin().get_branding("help_header", fallback)


def get_active_goodbye(fallback: str = "Robo standing by.") -> str:
    return get_active_skin().get_branding("goodbye", fallback)


def get_prompt_toolkit_style_overrides() -> Dict[str, str]:
    """prompt_toolkit style classes for the interactive prompt, from the active
    skin. Every class the TUI uses is present, so switching skins restyles the
    whole prompt in one step."""
    skin = get_active_skin()
    c = skin.get_color
    title, text, dim = c("banner_title", "#FFE9D6"), c("banner_text", "#E6E3F5"), c("banner_dim", "#8C91BD")
    accent, label, line = c("ui_accent", "#EF8A22"), c("ui_label", "#A3A1EC"), c("input_rule", "#6462C4")
    ok, warn, error = c("ui_ok", "#3FBF7F"), c("ui_warn", "#F2B441"), c("ui_error", "#F0626E")
    bar = c("status_bar_bg", "#0E1437")
    bar_text = c("status_bar_text", text)
    menu, menu_hi = c("completion_menu_bg", bar), c("completion_menu_current_bg", "#2A2C73")
    meta, meta_hi = c("completion_menu_meta_bg", menu), c("completion_menu_meta_current_bg", menu_hi)
    voice = c("voice_status_bg", bar)

    return {
        "input-area": text,
        "placeholder": f"{dim} italic",
        "prompt": c("prompt", title),
        "prompt-working": f"{dim} italic",
        "hint": f"{dim} italic",
        "input-rule": line,
        "image-badge": f"{label} bold",
        "status-bar": f"bg:{bar} {bar_text}",
        "status-bar-strong": f"bg:{bar} {c('status_bar_strong', title)} bold",
        "status-bar-dim": f"bg:{bar} {c('status_bar_dim', dim)}",
        "status-bar-good": f"bg:{bar} {c('status_bar_good', ok)} bold",
        "status-bar-warn": f"bg:{bar} {c('status_bar_warn', warn)} bold",
        "status-bar-bad": f"bg:{bar} {c('status_bar_bad', warn)} bold",
        "status-bar-critical": f"bg:{bar} {c('status_bar_critical', error)} bold",
        "completion-menu": f"bg:{menu} {text}",
        "completion-menu.completion": f"bg:{menu} {text}",
        "completion-menu.completion.current": f"bg:{menu_hi} {title} bold",
        "completion-menu.meta.completion": f"bg:{meta} {dim}",
        "completion-menu.meta.completion.current": f"bg:{meta_hi} {text}",
        "voice-status": f"bg:{voice} {label}",
        "voice-status-recording": f"bg:{voice} {error} bold",
        "clarify-border": line,
        "clarify-title": f"{title} bold",
        "clarify-question": f"{text} bold",
        "clarify-choice": dim,
        "clarify-selected": f"{accent} bold",
        "clarify-active-other": f"{accent} italic",
        "clarify-countdown": dim,
        "sudo-prompt": f"{error} bold",
        "sudo-border": error,
        "sudo-title": f"{error} bold",
        "sudo-text": text,
        "approval-border": warn,
        "approval-title": f"{warn} bold",
        "approval-desc": f"{text} bold",
        "approval-cmd": f"{dim} italic",
        "approval-choice": dim,
        "approval-selected": f"{accent} bold",
    }


_register_resource_skins()
