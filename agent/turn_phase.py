"""Tell a surface with a live status line what the turn is doing right now.

After the answer has streamed, a turn can keep going for a while with no
tool call and no token for the person to see: the end-of-turn fact check
researches the answer's statements, a verification pass re-reads what was
edited. On the TUI that time looked like a silent "thinking…". These reports
go out through ``status_callback`` with a kind of their own so the TUI can
show them in the live area under the answer and in the status-bar verb until
the model moves on; they never reach a messaging surface (Telegram, Slack…),
where every status is relayed as a chat message and this would be noise. The
CLI's printed lifecycle lines are untouched — use ``agent._emit_status`` for
those.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def phase_channel(agent: Any, kind: str) -> Optional[Callable[[str], None]]:
    """A ``report(text)`` callable for *kind*, or ``None`` when nobody is listening.

    ``None`` when the agent has no ``status_callback`` or the turn is being
    delivered over a messaging surface. Never raises.
    """
    callback = getattr(agent, "status_callback", None)
    if not callable(callback):
        return None
    try:
        from agent.judgment import on_messaging_surface

        if on_messaging_surface():
            return None
    except Exception:
        return None

    def _report(text: str) -> None:
        try:
            callback(kind, text)
        except Exception:
            logger.debug("turn phase %s: status callback failed", kind, exc_info=True)

    return _report


def report_phase(agent: Any, kind: str, text: str) -> None:
    """One-shot form of :func:`phase_channel`."""
    channel = phase_channel(agent, kind)
    if channel is not None:
        channel(text)
