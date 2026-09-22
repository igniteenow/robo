"""The ``robo`` command: Robo's cross-platform engineering runtime."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from .bootstrap import activate_robo_home
from .version import ROBO_VERSION


# DEC private modes a previous session may have left on if it was killed or its
# terminal tab closed: mouse tracking (every mouse move then arrives at the shell
# as text like "35;111;47M"), focus events, bracketed paste, hidden cursor.
# Cheap, idempotent, and only touches a real terminal.
_TERMINAL_RESET = (
    "\x1b[?1006l\x1b[?1005l\x1b[?1003l\x1b[?1002l\x1b[?1001l\x1b[?1000l\x1b[?9l"
    "\x1b[?1004l\x1b[?2004l\x1b[0m\x1b[?25h"
)


def restore_terminal_modes() -> None:
    """Undo terminal modes a crashed session left behind. Never raises."""
    try:
        if os.name != "nt" and sys.stdout.isatty():
            sys.stdout.write(_TERMINAL_RESET)
            sys.stdout.flush()
    except Exception:
        pass


def _print_robo_version() -> None:
    print(f"Robo {ROBO_VERSION}")
    print("Runtime: Robo Engineering Core")


def _print_assets(home: Path) -> None:
    report = {
        "robo_home": str(home),
        "face": str(home / "assets" / "face" / "cute-face.html"),
        "wake_word_onnx": str(home / "assets" / "wake_word" / "hey_roh_boh.onnx"),
        "wake_word_tflite": str(home / "assets" / "wake_word" / "hey_roh_boh.tflite"),
    }
    print(json.dumps(report, indent=2))


def main() -> None:
    """Bootstrap and launch Robo."""

    restore_terminal_modes()
    home = activate_robo_home()
    os.environ.setdefault("ROBO_CLI_NAME", "robo")
    os.environ.setdefault("ROBO_PRODUCT_NAME", "Robo")
    os.environ.setdefault("ROBO_DESKTOP_APP_NAME", "Robo")
    os.environ.setdefault("ROBO_WAKE_PHRASE_DISPLAY", "Hey Roh Boh")
    robo_bin = shutil.which("robo")
    if robo_bin:
        os.environ.setdefault("ROBO_BIN", robo_bin)
    argv = sys.argv[1:]

    if argv in (["--robo-version"], ["--version"], ["version"], ["version", "--robo"]):
        _print_robo_version()
        return
    if argv == ["assets"]:
        _print_assets(home)
        return
    if argv and argv[0] == "update":
        print("Robo updates are installed from a signed or checksum-verified Robo release package.")
        print("Robo will not replace itself with a third-party runtime.")
        return

    # The compatibility core reads argv directly. Keep process listings and
    # diagnostics branded as the product the operator launched.
    sys.argv[0] = "robo"
    from robo_cli.main import main as robo_main

    robo_main()


if __name__ == "__main__":
    main()
