"""Resolve ROBO_HOME for standalone skill scripts.

Skill scripts may run outside the Robo process (e.g. system Python,
nix env, CI) where ``robo_constants`` is not importable.  This module
provides the same ``get_robo_home()`` and ``display_robo_home()``
contracts as ``robo_constants`` without requiring it on ``sys.path``.

When ``robo_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``robo_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``ROBO_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from robo_constants import display_robo_home as display_robo_home
    from robo_constants import get_robo_home as get_robo_home
except (ModuleNotFoundError, ImportError):

    def get_robo_home() -> Path:
        """Return the Robo home directory (default: ~/.robo).

        Mirrors ``robo_constants.get_robo_home()``."""
        val = os.environ.get("ROBO_HOME", "").strip()
        return Path(val) if val else Path.home() / ".robo"

    def display_robo_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``robo_constants.display_robo_home()``."""
        home = get_robo_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
