"""Resolve ROBO_HOME for standalone skill scripts.

Skill scripts may run outside the Robo process (system Python, nix env,
CI) where ``robo_constants`` is not importable.  This module provides the
same ``get_robo_home()`` contract without requiring it on ``sys.path``.

When ``robo_constants`` IS available it is used directly so profile
resolution and any future enhancements are picked up automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from robo_constants import get_robo_home as get_robo_home
except (ModuleNotFoundError, ImportError):

    def get_robo_home() -> Path:
        """Return the Robo home directory (default: ``~/.robo``)."""
        val = os.environ.get("ROBO_HOME", "").strip()
        return Path(val) if val else Path.home() / ".robo"
