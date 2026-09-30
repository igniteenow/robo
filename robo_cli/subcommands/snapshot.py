"""``robo snapshot`` subcommand parser.

The terminal twin of the ``/snapshot`` slash command. Restoring belongs here,
outside a running chat: the TUI and the desktop app block ``/snapshot
restore`` because it rewrites config and state on disk under a live agent.
Handler injected to avoid importing ``main``.
"""

from __future__ import annotations

from typing import Callable


def build_snapshot_parser(subparsers, *, cmd_snapshot: Callable) -> None:
    """Attach the ``snapshot`` subcommand to ``subparsers``."""
    snapshot_parser = subparsers.add_parser(
        "snapshot",
        help="List, create, restore or prune quick state snapshots",
        description="Quick state snapshots of config.yaml, state.db, .env, auth "
        "and cron (the same ones /snapshot and `robo backup --quick` make). "
        "Restore with Robo closed, then start it again.",
    )
    snapshot_parser.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "ls", "create", "restore", "rewind", "prune"],
        help="What to do (default: list)",
    )
    snapshot_parser.add_argument(
        "value",
        nargs="*",
        help="create: a label; restore: a snapshot id or its number in the list; "
        "prune: how many to keep (default 20)",
    )
    snapshot_parser.set_defaults(func=cmd_snapshot)
