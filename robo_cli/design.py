"""Robo's command-line design language. Copyright (c) 2026 Ignitee Now.

One visual system for every command screen — ``robo setup``, ``robo gateway``,
``robo model``, ``robo tools``, ``robo skills``, ``robo doctor`` — so first-run
configuration looks like the same product as the chat, the desktop app and the
iPhone app.

The identity, from the Ignitee Now logo (``assets/brand/BRAND.md``):

* **The flame** is the brand. ``ROBO`` is drawn in a red-to-ember gradient, as a
  block wordmark on the first-run screen and inline in every screen title.
* **Ember means "act".** Prompts, the selected choice, numbered next steps and
  the filled part of a progress track are ember, and nothing else is.
* **Indigo is structure.** Rules, labels, table headers, panel borders.
* **The diamond** ``◆`` marks the product and the current selection.

Readability rules, which the previous design broke:

* Body text is never coloured. It stays in the terminal's own foreground, so it
  is readable on dark *and* light terminals. Only accents carry colour.
* Light terminals get deeper accents (detected from ``ROBO_LIGHT`` or
  ``COLORFGBG``), because bright ember on white is too faint to read.
* ``NO_COLOR``, ``TERM=dumb`` and pipes produce plain text. 16-colour terminals
  get the nearest ANSI colours. Nothing here ever raises.

Every public name below is part of the contract with ~700 call sites; keep the
names and signatures stable.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import Iterable, List, Optional, Sequence, Tuple

from robo_cli.colors import Colors, should_use_color

# ── Glyphs ────────────────────────────────────────────────────────────────────
OK = "✓"
WARN = "!"
ERR = "✗"
INFO = "·"
STEP = "▸"
PROMPT = "›"
BULLET = "•"
RULE = "─"
RULE_HEAVY = "━"
ELLIPSIS = "…"
MARK = "◆"
MARK_OFF = "◇"
PRODUCT = "ROBO"

# ── Palette ───────────────────────────────────────────────────────────────────
RGB = Tuple[int, int, int]

_DARK: dict = {
    "accent": (239, 138, 34),   # ember  #EF8A22
    "flame": (213, 39, 52),     # flame  #D52734
    "label": (163, 161, 236),   # indigo #A3A1EC
    "indigo": (100, 98, 196),   # indigo #6462C4
    "ok": (63, 191, 127),
    "warn": (242, 180, 65),
    "err": (240, 98, 110),
    "muted": (140, 145, 189),
}
_LIGHT: dict = {
    "accent": (181, 71, 15),    # burnt ember #B5470F
    "flame": (180, 35, 50),
    "label": (63, 62, 152),     # logo indigo #3F3E98
    "indigo": (88, 86, 184),
    "ok": (30, 122, 70),
    "warn": (143, 84, 0),
    "err": (180, 35, 50),
    "muted": (92, 96, 136),
}
_ANSI: dict = {
    "accent": Colors.YELLOW, "flame": Colors.RED, "label": Colors.MAGENTA, "indigo": Colors.MAGENTA,
    "ok": Colors.GREEN, "warn": Colors.YELLOW, "err": Colors.RED, "muted": Colors.DIM,
}
# "text" and "strong" are deliberately absent: body text keeps the terminal's colour.

_BLOCK_WORDMARK = (
    "██████╗  ██████╗ ██████╗  ██████╗ ",
    "██╔══██╗██╔═══██╗██╔══██╗██╔═══██╗",
    "██████╔╝██║   ██║██████╔╝██║   ██║",
    "██╔══██╗██║   ██║██╔══██╗██║   ██║",
    "██║  ██║╚██████╔╝██████╔╝╚██████╔╝",
    "╚═╝  ╚═╝ ╚═════╝ ╚═════╝  ╚═════╝ ",
)
_FLAME_ROWS: Tuple[RGB, ...] = ((245, 161, 58), (239, 138, 34), (232, 116, 42), (223, 90, 48), (217, 63, 50), (213, 39, 52))


def _truecolor() -> bool:
    if os.environ.get("ROBO_ANSI16"):
        return False
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return True
    term = os.environ.get("TERM", "")
    return term.endswith("-direct") or "kitty" in term or "wezterm" in term


def _light_terminal() -> bool:
    forced = os.environ.get("ROBO_LIGHT", "").strip().lower()
    if forced in ("1", "true", "yes", "on"):
        return True
    if forced in ("0", "false", "no", "off"):
        return False
    background = os.environ.get("COLORFGBG", "").rsplit(";", 1)[-1].strip()
    return background in ("7", "15")


def _rgb(role: str) -> Optional[RGB]:
    return (_LIGHT if _light_terminal() else _DARK).get(role)


def _sgr(rgb: RGB) -> str:
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def paint(text: str, role: str = "text", *, bold: bool = False, dim: bool = False) -> str:
    """Colour ``text`` by semantic role: accent, flame, label, indigo, ok, warn,
    err, muted. ``text`` and ``strong`` add no colour (``strong`` is bold)."""
    if not text or not should_use_color():
        return text
    codes = ""
    rgb = _rgb(role)
    if rgb is not None:
        codes = _sgr(rgb) if _truecolor() else _ANSI.get(role, "")
    if bold or role == "strong":
        codes += Colors.BOLD
    if dim:
        codes += Colors.DIM
    return f"{codes}{text}{Colors.RESET}" if codes else text


def gradient(text: str, start: str = "flame", end: str = "accent", *, bold: bool = True) -> str:
    """``text`` shaded from one role's colour to another, letter by letter. Falls
    back to the end colour where true colour is unavailable."""
    if not text or not should_use_color():
        return text
    a, b = _rgb(start), _rgb(end)
    if not _truecolor() or a is None or b is None:
        return paint(text, end, bold=bold)
    span = max(1, len(text) - 1)
    out = []
    for index, char in enumerate(text):
        t = index / span
        out.append(_sgr(tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))) + char)  # type: ignore[arg-type]
    return (Colors.BOLD if bold else "") + "".join(out) + Colors.RESET


def width(default: int = 80, maximum: int = 100) -> int:
    try:
        cols = shutil.get_terminal_size((default, 24)).columns
    except Exception:
        cols = default
    return max(40, min(cols, maximum))


def _out(line: str = "") -> None:
    print(line)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 1)] + ELLIPSIS


# ── Screens ───────────────────────────────────────────────────────────────────
def hero(tagline: str = "autonomous engineering agent", byline: str = "by Ignitee Now") -> None:
    """The first-run brand header: the block wordmark in the flame, top to
    bottom. On a terminal too narrow for it, a single branded line instead."""
    columns = width()
    _out()
    if columns < len(_BLOCK_WORDMARK[0]) + 4:
        _out("  " + paint(MARK, "accent", bold=True) + " " + gradient(PRODUCT) + "  " + paint(tagline, "muted"))
        _out()
        return
    colour = should_use_color()
    for row, rgb in zip(_BLOCK_WORDMARK, _FLAME_ROWS):
        if not colour:
            _out("  " + row)
        elif _truecolor():
            _out("  " + _sgr(rgb) + Colors.BOLD + row + Colors.RESET)
        else:
            _out("  " + paint(row, "accent", bold=True))
    _out("  " + paint(tagline, "muted") + "  " + paint(MARK, "accent") + "  " + paint(byline, "label"))
    _out()


def title(name: str, subtitle: str = "", *, version: Optional[str] = None, hero_art: bool = False) -> None:
    """Title bar for a command screen::

        ◆ ROBO · SETUP ─────────────────────────────────────── 3.0.0
          first-run configuration

    ``hero_art=True`` draws the block wordmark above it (first-run screens).
    """
    if hero_art:
        hero()
    columns = width()
    label = f"{MARK} {PRODUCT} · {name.upper()} "
    tail = f" {version}" if version else ""
    fill = max(2, columns - len(label) - len(tail) - 1)
    if not hero_art:
        _out()
    _out(
        paint(MARK, "accent", bold=True) + " " + gradient(PRODUCT) + paint(" · ", "muted")
        + paint(name.upper(), "strong") + " " + paint(RULE * fill, "indigo") + paint(tail, "muted")
    )
    if subtitle:
        _out("  " + paint(subtitle, "muted"))
    _out()


def progress(step: int, total: int, *, cells: int = 16) -> str:
    """``━━━━━━──────────  2/6`` — ember for what is done, indigo for what is left."""
    total = max(1, int(total))
    step = max(0, min(int(step), total))
    filled = round(cells * step / total)
    if step and not filled:
        filled = 1
    return paint(RULE_HEAVY * filled, "accent") + paint(RULE * (cells - filled), "indigo") + paint(f"  {step}/{total}", "muted")


def section(name: str, step: Optional[int] = None, total: Optional[int] = None, note: str = "") -> None:
    """Section heading. With ``step`` and ``total`` it shows how far along you are::

        ▸ Provider                                   ━━━━━━──────────  2/6
    """
    columns = width()
    if step is not None and total:
        right, right_len = progress(step, total), 16 + len(f"  {step}/{total}")
    elif step is not None:
        right, right_len = paint(f"step {step}", "muted"), len(f"step {step}")
    else:
        right, right_len = "", 0
    shown = _clip(name, max(8, columns - right_len - 6))
    pad = max(2, columns - len(shown) - right_len - 3)
    _out()
    _out(paint(STEP, "accent", bold=True) + " " + paint(shown, "strong") + (" " * pad + right if right else ""))
    if not right:
        _out("  " + paint(RULE * min(len(shown) + 24, columns - 4), "indigo"))
    if note:
        _out("  " + paint(note, "muted"))


def rule(label: str = "") -> None:
    columns = width()
    if label:
        text = f" {label} "
        _out(paint(RULE * 2, "indigo") + paint(text, "label") + paint(RULE * max(2, columns - len(text) - 2), "indigo"))
    else:
        _out(paint(RULE * columns, "indigo"))


def kv(label: str, value: object, *, label_width: int = 18, role: str = "text") -> None:
    """Aligned key/value row: ``  Model            anthropic/claude-sonnet-5``."""
    _out("  " + paint(f"{label:<{label_width}}", "label") + paint(str(value), role))


def kvs(rows: Iterable[Tuple[str, object]], *, label_width: Optional[int] = None) -> None:
    rows = list(rows)
    if not rows:
        return
    lw = label_width or min(28, max(len(str(k)) for k, _ in rows) + 2)
    for key, value in rows:
        kv(str(key), value, label_width=lw)


def ok(text: str) -> None:
    _out("  " + paint(OK, "ok", bold=True) + " " + text)


def warn(text: str) -> None:
    _out("  " + paint(WARN, "warn", bold=True) + " " + paint(text, "warn"))


def err(text: str) -> None:
    _out("  " + paint(ERR, "err", bold=True) + " " + paint(text, "err"))


def info(text: str) -> None:
    _out("  " + paint(INFO, "muted") + " " + text)


def hint(text: str) -> None:
    _out("    " + paint(text, "muted"))


def bullet(text: str, *, indent: int = 2) -> None:
    _out(" " * indent + paint(BULLET, "indigo") + " " + text)


def bullets(items: Iterable[str], *, indent: int = 2) -> None:
    for item in items:
        bullet(item, indent=indent)


def table(headers: Sequence[str], rows: Iterable[Sequence[object]], *, indent: int = 2) -> None:
    """Aligned table with indigo headers. The last column gives way first, and
    no row is ever wider than the terminal."""
    body = [[str(cell) for cell in row] for row in rows]
    cols = len(headers)
    if not cols:
        return
    widths = [len(str(h)) for h in headers]
    for row in body:
        for i in range(min(cols, len(row))):
            widths[i] = max(widths[i], len(row[i]))
    room = width() - indent - 2
    gaps = 2 * (cols - 1)
    overflow = sum(widths) + gaps - room
    for i in range(cols - 1, -1, -1):  # shrink from the right until it fits
        if overflow <= 0:
            break
        give = min(overflow, max(0, widths[i] - 6))
        widths[i] -= give
        overflow -= give
    pad = " " * indent
    _out(pad + "  ".join(paint(f"{_clip(str(h), widths[i]):<{widths[i]}}", "label") for i, h in enumerate(headers)))
    _out(pad + paint(RULE * min(room, sum(widths) + gaps), "indigo"))
    for row in body:
        _out(pad + "  ".join(f"{_clip(row[i] if i < len(row) else '', widths[i]):<{widths[i]}}" for i in range(cols)).rstrip())


def panel(name: str, lines: Iterable[str], *, role: str = "indigo") -> None:
    """Boxed block for summaries, with an indigo frame."""
    rows = [str(line) for line in lines]
    inner = max([len(name) + 4] + [len(r) for r in rows])
    inner = max(8, min(inner, width() - 6))
    shown = _clip(name, inner - 2)
    _out(paint("┌" + RULE + " ", role) + paint(shown, "label", bold=True) + paint(" " + RULE * max(1, inner - len(shown) - 1) + "┐", role))
    for r in rows:
        _out(paint("│ ", role) + f"{_clip(r, inner):<{inner}}" + paint(" │", role))
    _out(paint("└" + RULE * (inner + 2) + "┘", role))


def prompt_line(question: str, default: Optional[str] = None, *, hint_text: str = "") -> str:
    """The rendered prompt, for ``input()``: ``  › Question [default]: ``."""
    suffix = paint(f" [{default}]", "muted") if default else ""
    extra = paint(f"  {hint_text}", "muted") if hint_text else ""
    return "  " + paint(PROMPT, "accent", bold=True) + " " + paint(question, "strong") + suffix + extra + ": "


def choice_rows(choices: Sequence[str], selected: int, *, indent: int = 4) -> List[str]:
    """A radio list for terminals without cursor control. The selected row gets
    the ember diamond and bold text, so it is clear without colour too."""
    out = []
    for index, choice in enumerate(choices):
        chosen = index == selected
        mark = paint(MARK, "accent", bold=True) if chosen else paint(MARK_OFF, "indigo")
        out.append(" " * indent + f"{mark} {paint(str(index + 1), 'muted')}  {paint(str(choice), 'strong') if chosen else choice}")
    return out


def next_steps(items: Iterable[str]) -> None:
    section("Next steps")
    for index, item in enumerate(items, 1):
        _out(f"  {paint(str(index) + '.', 'accent', bold=True)} {item}")
    _out()


def command(cmd: str) -> str:
    """Inline styling for a shell command inside a sentence."""
    return paint(cmd, "accent")


def done(text: str = "Done.") -> None:
    _out()
    ok(text)
    _out()


def stderr(text: str) -> None:
    print(text, file=sys.stderr)
