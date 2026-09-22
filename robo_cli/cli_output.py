"""Shared CLI output helpers for Robo CLI modules.

Extracts the identical ``print_info/success/warning/error`` and ``prompt()``
functions previously duplicated across setup.py, tools_config.py,
mcp_config.py, and memory_setup.py.
"""

from robo_cli.colors import Colors, color
from robo_cli.secret_prompt import masked_secret_prompt


# ─── Print Helpers ────────────────────────────────────────────────────────────
# All four helpers render through robo_cli.design so every command surface
# shares one glyph set and palette (see that module for the design language).


def print_info(text: str) -> None:
    """Print a muted informational line."""
    from robo_cli import design as ui
    ui.info(text.strip() if text.strip() else "")


def print_success(text: str) -> None:
    """Print a success line with the ✓ marker."""
    from robo_cli import design as ui
    ui.ok(text)


def print_warning(text: str) -> None:
    """Print a warning line with the ! marker."""
    from robo_cli import design as ui
    ui.warn(text)


def print_error(text: str) -> None:
    """Print an error line with the ✗ marker."""
    from robo_cli import design as ui
    ui.err(text)


def print_header(text: str) -> None:
    """Print a section heading."""
    from robo_cli import design as ui
    ui.section(text)


# ─── Input Prompts ────────────────────────────────────────────────────────────


def prompt(
    question: str,
    default: str | None = None,
    password: bool = False,
) -> str:
    """Prompt the user for input with optional default and password masking.

    Replaces the four independent ``_prompt()`` / ``prompt()`` implementations
    in setup.py, tools_config.py, mcp_config.py, and memory_setup.py.

    Returns the user's input (stripped), or *default* if the user presses Enter.
    Returns empty string on Ctrl-C or EOF.
    """
    from robo_cli import design as ui
    display = ui.prompt_line(question, default)

    try:
        if password:
            value = masked_secret_prompt(display)
        else:
            value = input(display)
        value = value.strip()
        return value if value else (default or "")
    except (KeyboardInterrupt, EOFError):
        print()
        return ""


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Prompt for a yes/no answer. Returns bool."""
    hint = "Y/n" if default else "y/N"
    answer = prompt(f"{question} ({hint})")
    if not answer:
        return default
    return answer.lower().startswith("y")
