"""Tips shown when a session starts. Copyright (c) 2026 Ignitee Now.

Two sources, joined into ``TIPS``:

* ``CURATED`` — written by hand, in Robo's voice, about how to work well with
  Robo. Every claim in them is checked against the code by
  ``tests/robo_cli/test_tips.py``.
* Generated tips — one per slash command, alias, ``robo`` subcommand and
  documented setting, built **at import time from the live registries**. They
  cannot drift: rename or remove a command and its tip changes or disappears
  with it. (A hand-written list once kept recommending skins that no longer
  existed; this design makes that impossible.)

Tips are printed through Rich markup, so a tip must never contain ``[`` or
``]``: Rich would read it as a style tag. Argument hints such as ``[name]`` are
rewritten as ``<name>``. The test suite enforces this for every tip.
"""

from __future__ import annotations

import logging
import random
import re
from collections import deque
from typing import Deque, Iterable, List

logger = logging.getLogger(__name__)

CURATED: tuple = (
    # Voice and wake word
    "Say Hey Roh Boh to wake Robo hands-free. Turn the listener on with /wake on. It is off by default, so nothing listens until you ask.",
    "Only one Robo can hold the microphone at a time. If the wake word says it is in use, another Robo window already has it.",
    "If Robo crashes while listening, the microphone lock frees itself. You never need to delete a lock file by hand.",
    # Skins and themes
    "Robo ships five skins: robo, ember, midnight, paper and contrast. Try one with /skin ember.",
    "On a light terminal? /skin paper is drawn for it. Want maximum legibility? /skin contrast.",
    "Make your own skin: drop a YAML file in the skins folder inside your Robo home. Set three colours and Robo fills in the rest from the brand skin.",
    "A config that still says skin: default keeps working. It means the robo skin.",
    "robo config set display.skin midnight changes the skin in one safe command. It cannot leave your config file half-written.",
    "The desktop app and the terminal share skin names, so /skin midnight means the same look in both.",
    "Every desktop theme has a hand-tuned light and dark mode. Robo follows your system setting until you pick one.",
    "The Contrast desktop theme keeps every text pair at 7 to 1 or better, in light and in dark.",
    # Start-up banner
    "The start-up banner adapts to your terminal. Below 100 columns it drops the art and keeps the facts.",
    "A toolset that is switched off shows up in the banner with exactly what it needs, such as a missing API key.",
    "MCP servers appear in the start-up banner with their transport, connection state and tool count.",
    "When an update is waiting, the banner names the right command for your install. It differs between a git checkout and a packaged build.",
    # Updates
    "Robo checks for updates in the background and never holds up start-up. Set ROBO_NO_UPDATE_CHECK=1 to switch the check off on air-gapped machines.",
    "Update checks never prompt for a password or a passphrase, even on a checkout that was cloned over SSH.",
    "robo update brings Robo up to date. Afterwards the banner stops saying you are behind straight away, not six hours later.",
    # Sessions and sharing
    "robo sessions export --format html turns a session into one self-contained file with search, role filters, light and dark mode and a print layout.",
    "Exported sessions are safe to pass around: everything a model or tool wrote is escaped, and the file makes no network requests.",
    "Long tool output is folded away in exported sessions with its size shown, so the conversation stays readable.",
    # Skills
    "A skill is a folder with a SKILL.md in it. Put your own under the skills folder in your Robo home and Robo picks it up.",
    "Choose which skill registries Robo searches. List the ones you do not want under skills.disabled_hub_sources in config.yaml.",
    "ROBO_SKILLS_DISABLED_SOURCES=clawhub,lobehub switches outside skill registries off from the environment. Robo's bundled skills always stay available.",
    "robo skills install adds a skill by name, and robo skills search finds one.",
    # Knowledge base
    "Attach a file of any size and Robo indexes it locally. Ask about it afterwards and it quotes the passages it used, instead of reading the whole file.",
    "Robo can read PDF, Word, Excel and PowerPoint files you attach, on every surface, with nothing uploaded anywhere.",
    # Moving in, and looking after your data
    "Coming from another agent? robo import-agent brings your settings and memory across. Add --dry-run to see every change before anything is written.",
    "robo backup saves a copy of your Robo home. Take one before a big change.",
    "robo debug share --local writes a redacted debug bundle to disk instead of uploading it anywhere.",
    "Profiles keep separate config, memory and skills side by side. robo profile manages them.",
    # Messaging
    "robo gateway setup connects Robo to your messaging platforms, so you can give it work from your phone.",
    "Telegram has a one-tap bot setup. If it is unavailable, Robo falls back to the manual BotFather steps on its own.",
    # Models
    "Hermes chat models are good company but do not call tools. Robo warns you if you pick one for agent work.",
    "MoA mode asks several models and lets one combine their answers. robo moa sets it up.",
    # Everywhere
    "Robo on iPhone can run entirely on the device in Local mode, or pair with your gateway to use your full setup.",
    "robo dashboard starts the web dashboard, and robo doctor looks your setup over when something feels off.",
)

_SKIP_COMMANDS = {"start"}  # platform plumbing, not something a person types
MAX_TIP_LENGTH = 200  # a tip is one glanceable line; longer generated ones are left out
_BRACKET_HINT = re.compile(r"\[([^\[\]]*)\]")


def _plain(text: object) -> str:
    """One line, no square brackets, no trailing full stop."""
    line = " ".join(str(text or "").split())
    line = _BRACKET_HINT.sub(lambda m: f"<{m.group(1)}>", line)
    return line.replace("[", "(").replace("]", ")").rstrip(". ")


def _command_tips() -> List[str]:
    from robo_cli.commands import COMMAND_REGISTRY

    tips: List[str] = []
    for command in COMMAND_REGISTRY:
        name = getattr(command, "name", "")
        description = _plain(getattr(command, "description", ""))
        if not name or not description or name in _SKIP_COMMANDS:
            continue
        hint = _plain(getattr(command, "args_hint", ""))
        usage = f" Usage: /{name} {hint}." if hint else ""
        tips.append(f"/{name}: {description}.{usage}")
        for alias in getattr(command, "aliases", ()) or ():
            if alias and alias != name:
                tips.append(f"/{alias} is another name for /{name}: {description}.")
    return tips


def _subcommand_tips() -> List[str]:
    """``robo <subcommand>`` tips from the argparse help strings."""
    from pathlib import Path

    here = Path(__file__).resolve().parent
    pattern = re.compile(r"""\bsubparsers\.add_parser\(\s*["']([a-z][a-z0-9-]*)["']\s*,[^)]*?\bhelp\s*=\s*["']([^"']{8,})["']""", re.S)
    seen, tips = set(), []
    for path in sorted([*(here / "subcommands").glob("*.py"), here / "main.py"]):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for name, help_text in pattern.findall(source):
            if name not in seen:
                seen.add(name)
                tips.append(f"robo {name}: {_plain(help_text)}.")
    return tips


def _setting_tips() -> List[str]:
    from robo_cli.config_defaults import OPTIONAL_ENV_VARS

    tips: List[str] = []
    for name, info in OPTIONAL_ENV_VARS.items():
        if not isinstance(info, dict) or not info.get("url"):
            continue  # only settings a person can act on: there is somewhere to get the value
        description = _plain(info.get("description"))
        if description:
            tips.append(f"{name} in your .env: {description}. Get one at {info['url']}")
    return tips


def _build() -> List[str]:
    tips: List[str] = [_plain(t) + "." if not t.rstrip().endswith((".", "?", "!")) else " ".join(t.split()) for t in CURATED]
    for source in (_command_tips, _subcommand_tips, _setting_tips):
        try:
            tips.extend(source())
        except Exception as exc:  # a tip is never worth a failed start-up
            logger.debug("tips: %s unavailable: %s", source.__name__, exc)
    unique: List[str] = []
    seen = set()
    for tip in tips:
        if tip and "[" not in tip and "]" not in tip and len(tip) <= MAX_TIP_LENGTH and tip not in seen:
            seen.add(tip)
            unique.append(tip)
    return unique


TIPS: List[str] = _build()

_recent: Deque[str] = deque(maxlen=64)


def get_random_tip(exclude_recent: int = 0) -> str:
    """A random tip. With ``exclude_recent=N`` it will not repeat any of the
    last ``N`` tips handed out in this process."""
    pool: Iterable[str] = TIPS
    if exclude_recent > 0 and _recent:
        blocked = set(list(_recent)[-int(exclude_recent):])
        remaining = [t for t in TIPS if t not in blocked]
        pool = remaining or TIPS
    tip = random.choice(list(pool)) if TIPS else "Type /help to see what Robo can do."
    _recent.append(tip)
    return tip
