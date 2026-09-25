"""
Top-level argparse construction for the robo CLI.

Lives in its own module so other modules (e.g. ``relaunch.py``) can
introspect the parser to discover which flags exist without running the
``main`` fn.

Only the top-level parser and the ``chat`` subparser live here. Every other
subparser (model, gateway, sessions, …) is built inline in ``main.py``
because its dispatch is tightly coupled to module-level ``cmd_*`` functions.
"""

import argparse
import os


def _brand_help_text(text: str) -> str:
    """Brand human-facing help while preserving compatibility identifiers."""

    cli_name = os.environ.get("ROBO_CLI_NAME", "robo").strip() or "robo"
    if cli_name == "robo":
        return text
    product_name = os.environ.get("ROBO_PRODUCT_NAME", "Robo").strip() or "Robo"
    return (
        text.replace("Robo", product_name)
        .replace("`robo ", f"`{cli_name} ")
        .replace(" robo ", f" {cli_name} ")
    )


class _ProductHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def _expand_help(self, action):
        return _brand_help_text(super()._expand_help(action))


# `--profile` / `-p` is consumed by ``main._apply_profile_override`` before
# argparse runs (it sets ``ROBO_HOME`` and strips itself from ``sys.argv``),
# so it isn't on the parser. Listed here so all "carry over on relaunch"
# metadata lives in one file.
PRE_ARGPARSE_INHERITED_FLAGS: list[tuple[str, bool]] = [
    ("--profile", True),
    ("-p", True),
]


def _inherited_flag(parser, *args, **kwargs):
    """Register a flag that ``robo_cli.relaunch`` should carry over when
    the CLI re-execs itself (e.g. after ``sessions browse`` picks a session,
    or after the setup wizard launches chat).

    Equivalent to ``parser.add_argument(...)`` plus tagging the resulting
    Action with ``inherit_on_relaunch = True`` so the relaunch table builder
    can find it via introspection.
    """
    action = parser.add_argument(*args, **kwargs)
    action.inherit_on_relaunch = True
    return action


_EPILOGUE = """
Commands by area
  Get started      setup · model · tools · chat · status · doctor
  Sessions         sessions · checkpoints · backup · dump · logs · prompt-size
  Gateway          gateway · whatsapp · whatsapp-cloud · slack · send · webhook · pairing
  Models & auth    model · moa · fallback · logout · auth · proxy · migrate
  Automation       cron · kanban · project · hooks · approvals · security
  Extensions       skills · bundles · plugins · mcp · tools · computer-use · lsp
  Memory           memory · memory-graph · learning · curator · insights · monitoring
  Interfaces       dashboard · desktop · gui · serve · acp · console · skin
  Maintenance      config · profile · secrets · egress · sync · update · uninstall
  About            version · completion · journey · pets

Examples
  robo                          Start the TUI (display.interface: tui)
  robo --cli                    Classic REPL
  robo -c                       Resume the most recent session
  robo chat -q "Hello"          One-shot query
  robo setup                    First-run wizard (re-run any time)
  robo setup model|tools|gateway|agent   Jump to one section
  robo model                    Pick the default model and provider
  robo tools                    Choose toolsets per platform
  robo gateway install          Run the messaging gateway as a service
  robo config set model gpt-4   Set a config value
  robo sessions browse          Interactive session picker
  robo logs -f                  Follow agent.log

Run `robo <command> --help` for the options of any command.
"""


def build_top_level_parser():
    """Build the top-level parser, the subparsers action, and the ``chat`` subparser.

    Returns ``(parser, subparsers, chat_parser)``. The caller wires
    ``chat_parser.set_defaults(func=cmd_chat)`` and continues registering
    other subparsers via ``subparsers.add_parser(...)``.
    """
    cli_name = os.environ.get("ROBO_CLI_NAME", "robo").strip() or "robo"
    product_name = os.environ.get("ROBO_PRODUCT_NAME", "Robo").strip() or "Robo"
    epilogue = _brand_help_text(
        _EPILOGUE
        if cli_name == "robo"
        else _EPILOGUE.replace("    robo ", f"    {cli_name} ")
    )

    parser = argparse.ArgumentParser(
        prog=cli_name,
        description=f"{product_name} — autonomous engineering runtime (Ignitee Now)",
        formatter_class=_ProductHelpFormatter,
        epilog=epilogue,
    )

    parser.add_argument(
        "--version", "-V", action="store_true", help="Show version and exit"
    )
    parser.add_argument(
        "-z",
        "--oneshot",
        metavar="PROMPT",
        default=None,
        help=(
            "One-shot mode: send a single prompt and print ONLY the final "
            "response text to stdout. No banner, no spinner, no tool "
            "previews, no session_id line. Tools, memory, rules, and "
            "AGENTS.md in the CWD are loaded as normal; approvals are "
            "auto-bypassed. Intended for scripts / pipes."
        ),
    )
    parser.add_argument(
        "--usage-file",
        metavar="PATH",
        default=None,
        help=(
            "One-shot mode only: after the run, write a JSON usage report "
            "(estimated cost, token counts, model, api_calls) to PATH. "
            "The report is written even when the run fails, so pipelines "
            "can always account for spend. No effect outside -z/--oneshot."
        ),
    )
    # --model / --provider are accepted at the top level so they can pair
    # with -z without needing the `chat` subcommand.  If neither -z nor a
    # subcommand consumes them, they fall through harmlessly as None.
    # Mirrors `robo chat --model ... --provider ...` semantics.
    _inherited_flag(
        parser,
        "-m",
        "--model",
        default=None,
        help=(
            "Model override for this invocation (e.g. anthropic/claude-sonnet-4.6). "
            "Applies to -z/--oneshot and --tui. Also settable via ROBO_INFERENCE_MODEL env var."
        ),
    )
    _inherited_flag(
        parser,
        "--provider",
        default=None,
        help=(
            "Provider override for this invocation (e.g. openrouter, anthropic). "
            "Applies to -z/--oneshot and --tui. The persistent provider lives in config.yaml "
            f"under model.provider — use `{cli_name} setup` or edit the file to change it."
        ),
    )
    _inherited_flag(
        parser,
        "--reasoning",
        default=None,
        metavar="LEVEL",
        help=(
            "Reasoning effort for this invocation: none, minimal, low, medium, "
            "high, xhigh, max, or ultra. Overrides agent.reasoning_effort in "
            "config.yaml for this run only; the persistent level lives there "
            "(or per-model under agent.reasoning_overrides)."
        ),
    )
    parser.add_argument(
        "-t",
        "--toolsets",
        default=None,
        help="Comma-separated toolsets to enable for this invocation. Applies to -z/--oneshot and --tui.",
    )
    parser.add_argument(
        "--resume",
        "-r",
        metavar="SESSION",
        default=None,
        help="Resume a previous session by ID or title",
    )
    parser.add_argument(
        "--no-restore-cwd",
        action="store_true",
        default=False,
        help="Don't cd into a resumed session's recorded working directory.",
    )
    parser.add_argument(
        "--continue",
        "-c",
        dest="continue_last",
        nargs="?",
        const=True,
        default=None,
        metavar="SESSION_NAME",
        help="Resume a session by name, or the most recent if no name given",
    )
    parser.add_argument(
        "--worktree",
        "-w",
        action="store_true",
        default=False,
        help="Run in an isolated git worktree (for parallel workers)",
    )
    _inherited_flag(
        parser,
        "--accept-hooks",
        action="store_true",
        default=False,
        help=(
            "Auto-approve any unseen shell hooks declared in config.yaml "
            "without a TTY prompt.  Equivalent to ROBO_ACCEPT_HOOKS=1 or "
            "hooks_auto_accept: true in config.yaml.  Use on CI / headless "
            "runs that can't prompt."
        ),
    )
    _inherited_flag(
        parser,
        "--skills",
        "-s",
        action="append",
        default=None,
        help="Preload one or more skills for the session (repeat flag or comma-separate)",
    )
    _inherited_flag(
        parser,
        "--yolo",
        action="store_true",
        default=False,
        help="Bypass all dangerous command approval prompts (use at your own risk)",
    )
    _inherited_flag(
        parser,
        "--pass-session-id",
        action="store_true",
        default=False,
        help="Include the session ID in Robo's system prompt",
    )
    _inherited_flag(
        parser,
        "--ignore-user-config",
        action="store_true",
        default=False,
        help="Ignore ~/.robo/config.yaml and fall back to built-in defaults (credentials in .env are still loaded)",
    )
    _inherited_flag(
        parser,
        "--ignore-rules",
        action="store_true",
        default=False,
        help="Skip auto-injection of AGENTS.md, SOUL.md, .cursorrules, memory, and preloaded skills",
    )
    _inherited_flag(
        parser,
        "--safe-mode",
        action="store_true",
        default=False,
        help="Troubleshooting mode: disable ALL customizations — user config, AGENTS.md/memory injection, plugins, and MCP servers (implies --ignore-user-config and --ignore-rules)",
    )
    _inherited_flag(
        parser,
        "--tui",
        action="store_true",
        default=False,
        help="Launch the modern TUI instead of the classic REPL",
    )
    _inherited_flag(
        parser,
        "--cli",
        action="store_true",
        default=False,
        help="Force the classic prompt_toolkit REPL (overrides display.interface=tui)",
    )
    _inherited_flag(
        parser,
        "--dev",
        dest="tui_dev",
        action="store_true",
        default=False,
        help="With --tui: run TypeScript sources via tsx (skip dist build)",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>", help="Command to run")

    # =========================================================================
    # chat command
    # =========================================================================
    chat_parser = subparsers.add_parser(
        "chat",
        help=f"Interactive chat with {product_name}",
        description=f"Start an interactive chat session with {product_name}",
    )
    chat_parser.add_argument(
        "-q", "--query", help="Single query (non-interactive mode)"
    )
    chat_parser.add_argument(
        "--image", help="Optional local image path to attach to a single query"
    )
    # `default=argparse.SUPPRESS` on flags that are ALSO declared on the
    # top-level parser: when the user writes `robo -m foo chat`, argparse
    # first sets `args.model = "foo"` from the top-level parser, then
    # dispatches to the chat subparser. Without SUPPRESS the chat subparser's
    # own default (`None`) would silently clobber the top-level value because
    # the subparser shares the same namespace and `dest`. SUPPRESS keeps the
    # subparser action a no-op unless the user actually passes the flag after
    # the subcommand. Matches the pattern already used for `-s/--skills` and
    # the relaunch-inherited flags `-r/--resume`, `-c/--continue`,
    # `-w/--worktree`, `--yolo`, etc. (see tests/robo_cli/
    # test_argparse_flag_propagation.py).
    _inherited_flag(
        chat_parser,
        "-m", "--model",
        default=argparse.SUPPRESS,
        help="Model to use (e.g., anthropic/claude-sonnet-4)",
    )
    chat_parser.add_argument(
        "-t", "--toolsets",
        default=argparse.SUPPRESS,
        help="Comma-separated toolsets to enable",
    )
    _inherited_flag(
        chat_parser,
        "--reasoning",
        default=argparse.SUPPRESS,
        metavar="LEVEL",
        help=(
            "Reasoning effort for this session: none, minimal, low, medium, "
            "high, xhigh, max, or ultra. Overrides agent.reasoning_effort for "
            "this run only (same levels as the /reasoning slash command)."
        ),
    )
    _inherited_flag(
        chat_parser,
        "-s",
        "--skills",
        action="append",
        default=argparse.SUPPRESS,
        help="Preload one or more skills for the session (repeat flag or comma-separate)",
    )
    _inherited_flag(
        chat_parser,
        "--provider",
        # No `choices=` here: user-defined providers from config.yaml `providers:`
        # are also valid values, and runtime resolution (resolve_runtime_provider)
        # handles validation/error reporting consistently with the top-level
        # `--provider` flag.
        default=argparse.SUPPRESS,
        help="Inference provider (default: auto). Built-in or a user-defined name from `providers:` in config.yaml.",
    )
    chat_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Verbose output",
    )
    chat_parser.add_argument(
        "-Q",
        "--quiet",
        action="store_true",
        help="Quiet mode for programmatic use: suppress banner, spinner, and tool previews. Only output the final response and session info.",
    )
    chat_parser.add_argument(
        "--resume",
        "-r",
        metavar="SESSION_ID",
        default=argparse.SUPPRESS,
        help="Resume a previous session by ID (shown on exit)",
    )
    chat_parser.add_argument(
        "--no-restore-cwd",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Don't cd into a resumed session's recorded working directory.",
    )
    chat_parser.add_argument(
        "--continue",
        "-c",
        dest="continue_last",
        nargs="?",
        const=True,
        default=argparse.SUPPRESS,
        metavar="SESSION_NAME",
        help="Resume a session by name, or the most recent if no name given",
    )
    chat_parser.add_argument(
        "--worktree",
        "-w",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Run in an isolated git worktree (for parallel workers on the same repo)",
    )
    _inherited_flag(
        chat_parser,
        "--accept-hooks",
        action="store_true",
        default=argparse.SUPPRESS,
        help=(
            "Auto-approve any unseen shell hooks declared in config.yaml "
            "without a TTY prompt (see also ROBO_ACCEPT_HOOKS env var and "
            "hooks_auto_accept: in config.yaml)."
        ),
    )
    chat_parser.add_argument(
        "--checkpoints",
        action="store_true",
        default=False,
        help="Enable filesystem checkpoints before destructive file operations (use /rollback to restore)",
    )
    chat_parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        metavar="N",
        help="Maximum tool-calling iterations per conversation turn (default: 500, or agent.max_turns in config)",
    )
    _inherited_flag(
        chat_parser,
        "--yolo",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Bypass all dangerous command approval prompts (use at your own risk)",
    )
    _inherited_flag(
        chat_parser,
        "--pass-session-id",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Include the session ID in Robo's system prompt",
    )
    _inherited_flag(
        chat_parser,
        "--ignore-user-config",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Ignore ~/.robo/config.yaml and fall back to built-in defaults (credentials in .env are still loaded). Useful for isolated CI runs, reproduction, and third-party integrations.",
    )
    _inherited_flag(
        chat_parser,
        "--ignore-rules",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Skip auto-injection of AGENTS.md, SOUL.md, .cursorrules, memory, and preloaded skills. Combine with --ignore-user-config for a fully isolated run.",
    )
    _inherited_flag(
        chat_parser,
        "--safe-mode",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Troubleshooting mode: disable ALL customizations — user config, AGENTS.md/memory injection, plugins, and MCP servers (implies --ignore-user-config and --ignore-rules). Use to isolate whether a problem comes from your setup or from Robo itself.",
    )
    chat_parser.add_argument(
        "--source",
        default=None,
        help="Session source tag for filtering (default: cli). Use 'tool' for third-party integrations that should not appear in user session lists.",
    )
    _inherited_flag(
        chat_parser,
        "--tui",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Launch the modern TUI instead of the classic REPL",
    )
    _inherited_flag(
        chat_parser,
        "--cli",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Force the classic prompt_toolkit REPL (overrides display.interface=tui)",
    )
    _inherited_flag(
        chat_parser,
        "--dev",
        dest="tui_dev",
        action="store_true",
        default=argparse.SUPPRESS,
        help="With --tui: run TypeScript sources via tsx (skip dist build)",
    )

    return parser, subparsers, chat_parser
