"""One-shot ``chat -q`` runs and the notices they print.

``chat -q`` prints one reply and exits, so a background subagent dispatched
during that turn would finish after nobody is left to read its result. The
agent turn runs on its own thread, and ContextVars do not cross threads, so
the one-shot declaration has to happen on that thread too.
"""

from __future__ import annotations

import importlib
import queue
import sys
import threading
from unittest.mock import MagicMock, patch

from gateway.session_context import async_delivery_supported


def _make_cli():
    """Build a RoboCLI with prompt_toolkit stubbed (same pattern as
    test_cli_interrupt_ack_race.py)."""
    clean_config = {
        "model": {
            "default": "test/model",
            "base_url": "https://openrouter.ai/api/v1",
            "provider": "auto",
        },
        "display": {"compact": False, "tool_progress": "all"},
        "agent": {},
        "terminal": {"env_type": "local"},
    }
    clean_env = {"LLM_MODEL": "", "ROBO_MAX_ITERATIONS": ""}
    prompt_toolkit_stubs = {
        name: MagicMock()
        for name in (
            "prompt_toolkit",
            "prompt_toolkit.history",
            "prompt_toolkit.styles",
            "prompt_toolkit.patch_stdout",
            "prompt_toolkit.application",
            "prompt_toolkit.layout",
            "prompt_toolkit.layout.processors",
            "prompt_toolkit.filters",
            "prompt_toolkit.layout.dimension",
            "prompt_toolkit.layout.menus",
            "prompt_toolkit.widgets",
            "prompt_toolkit.key_binding",
            "prompt_toolkit.completion",
            "prompt_toolkit.formatted_text",
            "prompt_toolkit.auto_suggest",
        )
    }
    with patch.dict(sys.modules, prompt_toolkit_stubs), patch.dict(
        "os.environ", clean_env, clear=False
    ):
        import cli as cli_mod

        cli_mod = importlib.reload(cli_mod)
        with patch.object(cli_mod, "get_tool_definitions", return_value=[]), patch.dict(
            cli_mod.__dict__, {"CLI_CONFIG": clean_config}
        ):
            return cli_mod, cli_mod.RoboCLI()


class _ProbeAgent:
    """Records what the delivery capability looks like from the agent thread."""

    def __init__(self, session_id):
        self.session_id = session_id
        self._interrupt_requested = False
        self._interrupt_message = None
        self._active_children = []
        self.max_iterations = 90
        self.model = "test/model"
        self.platform = "cli"
        self.seen_async_delivery = None

    def run_conversation(self, **kwargs):
        self.seen_async_delivery = async_delivery_supported()
        return {
            "final_response": "done",
            "messages": [{"role": "assistant", "content": "done"}],
            "api_calls": 1,
            "completed": True,
            "partial": True,
            "response_previewed": True,
        }

    def interrupt(self, message=None):
        self._interrupt_requested = True

    def clear_interrupt(self):
        self._interrupt_requested = False


def _run_one_turn(cli, *, single_query):
    agent = _ProbeAgent(cli.session_id)
    cli.agent = agent
    cli._interrupt_queue = queue.Queue()
    cli._pending_input = queue.Queue()
    if single_query:
        cli._single_query_mode = True
    with patch.object(cli, "_ensure_runtime_credentials", return_value=True), \
         patch.object(cli, "_resolve_turn_agent_config", return_value={
             "signature": cli._active_agent_route_signature,
             "model": None, "runtime": None, "request_overrides": None,
         }), \
         patch.object(cli, "_init_agent", return_value=True):
        cli.chat("hello")
    return agent


def test_single_query_turn_cannot_take_late_background_results():
    _, cli = _make_cli()
    agent = _run_one_turn(cli, single_query=True)
    assert agent.seen_async_delivery is False


def test_interactive_turn_still_takes_background_results():
    _, cli = _make_cli()
    agent = _run_one_turn(cli, single_query=False)
    assert agent.seen_async_delivery is True


def test_declaration_stays_on_the_thread_that_made_it():
    cli_mod, _ = _make_cli()
    seen = {}

    def declare_and_probe():
        cli_mod._declare_single_query_channel()
        seen["declared"] = async_delivery_supported()

    def probe_only():
        seen["other"] = async_delivery_supported()

    for target in (declare_and_probe, probe_only):
        t = threading.Thread(target=target)
        t.start()
        t.join(timeout=5)

    assert seen == {"declared": False, "other": True}


def test_single_query_clarify_answers_at_once():
    _, cli = _make_cli()
    cli._single_query_mode = True
    with patch("tools.clarify_gateway.resolve_clarify_timeout", return_value=120):
        answer = cli._clarify_callback("Pick one", ["a", "b"])
    assert "['a', 'b']" in answer
    assert getattr(cli, "_clarify_state", None) is None


def _tirith_notice_lines(cli_mod, cli, *, in_progress, quiet=False):
    cli._tirith_security_checked = False
    cli.config = {"security": {"tirith_enabled": True}}
    cli.tool_progress_mode = "off" if quiet else "all"
    printed = []
    with patch("tools.tirith_security.ensure_installed", return_value=None), \
         patch("tools.tirith_security.is_platform_supported", return_value=True), \
         patch("tools.tirith_security.install_in_progress", return_value=in_progress), \
         patch.object(cli_mod, "_cprint", side_effect=printed.append):
        cli._ensure_tirith_security()
    return [line for line in printed if "tirith" in line]


def test_tirith_notice_waits_for_first_download_to_finish():
    cli_mod, cli = _make_cli()
    assert _tirith_notice_lines(cli_mod, cli, in_progress=True) == []


def test_tirith_notice_shown_when_scanner_is_really_missing():
    cli_mod, cli = _make_cli()
    assert len(_tirith_notice_lines(cli_mod, cli, in_progress=False)) == 1


def test_tirith_notice_kept_out_of_quiet_output():
    cli_mod, cli = _make_cli()
    assert _tirith_notice_lines(cli_mod, cli, in_progress=False, quiet=True) == []


def test_install_in_progress_tracks_the_download_thread():
    import tools.tirith_security as ts

    release = threading.Event()
    worker = threading.Thread(target=release.wait, daemon=True)
    with patch.object(ts, "_install_thread", None):
        assert ts.install_in_progress() is False
    with patch.object(ts, "_install_thread", worker):
        worker.start()
        assert ts.install_in_progress() is True
        release.set()
        worker.join(timeout=5)
        assert ts.install_in_progress() is False
