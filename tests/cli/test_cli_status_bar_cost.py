"""Status-bar session cost (``display.show_cost``).

The knob shipped in config defaults and the docs ("Show estimated $ cost in
the CLI status bar") with nothing reading it. It now renders the session's
estimated spend — the figure the conversation loop keeps in
``agent.session_estimated_cost_usd`` — as a dim segment after the duration,
and only when there is a priced amount to show.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from cli import RoboCLI, _format_session_cost


def _make_cli(*, show_cost: bool, cost: float = 0.0, status: str = "estimated"):
    cli_obj = RoboCLI.__new__(RoboCLI)
    cli_obj.model = "anthropic/claude-sonnet-4-20250514"
    cli_obj.session_start = datetime.now() - timedelta(minutes=3)
    cli_obj.conversation_history = [{"role": "user", "content": "hi"}]
    cli_obj.agent = SimpleNamespace(
        model=cli_obj.model,
        session_estimated_cost_usd=cost,
        session_cost_status=status,
        session_cost_source="static",
    )
    cli_obj._show_cost = show_cost
    return cli_obj


class TestFormatSessionCost:
    def test_priced_amounts_render_in_dollars(self):
        agent = SimpleNamespace(session_estimated_cost_usd=0.1234, session_cost_status="estimated")
        assert _format_session_cost(agent) == "$0.12"

    def test_tiny_amounts_do_not_round_to_zero(self):
        agent = SimpleNamespace(session_estimated_cost_usd=0.004, session_cost_status="estimated")
        assert _format_session_cost(agent) == "<$0.01"

    def test_nothing_to_say_when_unpriced_included_or_unspent(self):
        assert _format_session_cost(None) == ""
        assert _format_session_cost(SimpleNamespace(session_estimated_cost_usd=1.0, session_cost_status="unknown")) == ""
        assert _format_session_cost(SimpleNamespace(session_estimated_cost_usd=1.0, session_cost_status="included")) == ""
        assert _format_session_cost(SimpleNamespace(session_estimated_cost_usd=0.0, session_cost_status="estimated")) == ""
        assert _format_session_cost(SimpleNamespace(session_estimated_cost_usd="x", session_cost_status="estimated")) == ""


class TestStatusBarCostSegment:
    def test_off_by_default_shows_nothing(self):
        cli_obj = _make_cli(show_cost=False, cost=0.42)

        assert cli_obj._get_status_bar_snapshot()["cost_label"] == ""
        assert "$0.42" not in cli_obj._build_status_bar_text(width=120)

    def test_on_renders_in_every_width_tier(self):
        cli_obj = _make_cli(show_cost=True, cost=0.42)

        assert cli_obj._get_status_bar_snapshot()["cost_label"] == "$0.42"
        assert "$0.42" in cli_obj._build_status_bar_text(width=120)
        assert "$0.42" in cli_obj._build_status_bar_text(width=60)

    def test_on_but_unpriced_stays_quiet(self):
        cli_obj = _make_cli(show_cost=True, cost=0.42, status="unknown")

        assert cli_obj._get_status_bar_snapshot()["cost_label"] == ""
