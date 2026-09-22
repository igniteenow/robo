"""Tests for the setup wizard's returning-user behavior.

On an existing install:
- Bare `robo setup` drops straight into the full reconfigure wizard
  (every prompt shows the current value as its default).
- `robo setup --quick` runs the narrower "fill in missing items" flow.
- `robo setup --reconfigure` is a backwards-compat alias for the
  bare-setup default.

On a fresh install, all three are no-ops — fall through to first-time setup.
"""

from argparse import Namespace
from contextlib import ExitStack
from unittest.mock import patch

import pytest


def _make_setup_args(**overrides):
    return Namespace(
        non_interactive=overrides.get("non_interactive", False),
        section=overrides.get("section", None),
        reset=overrides.get("reset", False),
        reconfigure=overrides.get("reconfigure", False),
        quick=overrides.get("quick", False),
    )


@pytest.fixture
def existing_install(tmp_path, monkeypatch):
    """Simulate a returning user with an existing configured install."""
    home = tmp_path / ".robo"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("ROBO_HOME", str(home))
    return home


@pytest.fixture
def fresh_install(tmp_path, monkeypatch):
    """Simulate a first-time user with no existing configuration."""
    home = tmp_path / ".robo"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("ROBO_HOME", str(home))
    return home


def _enter_existing_install_patches(stack, **extra):
    """Apply standard existing-install mocks via an ExitStack.

    Returns a dict of mocks from the `extra` kwargs (which map mock-name to
    target path) so callers can assert on them.
    """
    # Unconditional mocks (no return values to assert against).
    for target, kwargs in [
        ("robo_cli.setup.ensure_robo_home", {}),
        ("robo_cli.setup.is_interactive_stdin", {"return_value": True}),
        ("robo_cli.config.is_managed", {"return_value": False}),
        ("robo_cli.setup.load_config", {"return_value": {}}),
        ("robo_cli.setup.save_config", {}),
        ("robo_cli.setup.get_env_value", {"return_value": None}),
        ("robo_cli.auth.get_active_provider", {"return_value": "openrouter"}),
        ("robo_cli.setup._print_setup_summary", {}),
    ]:
        stack.enter_context(patch(target, **kwargs))

    # Named mocks caller wants to assert on.
    named = {}
    for name, target in extra.items():
        named[name] = stack.enter_context(patch(target))
    return named


def _enter_fresh_install_patches(stack, **extra):
    for target, kwargs in [
        ("robo_cli.setup.ensure_robo_home", {}),
        ("robo_cli.setup.is_interactive_stdin", {"return_value": True}),
        ("robo_cli.config.is_managed", {"return_value": False}),
        ("robo_cli.setup.load_config", {"return_value": {}}),
        ("robo_cli.setup.save_config", {}),
        ("robo_cli.auth.get_active_provider", {"return_value": None}),
        ("robo_cli.setup.get_env_value", {"return_value": None}),
    ]:
        stack.enter_context(patch(target, **kwargs))

    named = {}
    for name, target_spec in extra.items():
        if isinstance(target_spec, tuple):
            target, kwargs = target_spec
            named[name] = stack.enter_context(patch(target, **kwargs))
        else:
            named[name] = stack.enter_context(patch(target_spec))
    return named


class TestExistingInstallDefault:
    """Bare `robo setup` on an existing install = full reconfigure wizard."""

    def test_bare_setup_runs_full_reconfigure_without_menu(self, existing_install):
        """No menu, no prompt_choice — just run every section in sequence."""
        args = _make_setup_args()  # no flags

        with ExitStack() as stack:
            m = _enter_existing_install_patches(
                stack,
                prompt_choice="robo_cli.setup.prompt_choice",
                quick="robo_cli.setup._run_quick_setup",
                model="robo_cli.setup.setup_model_provider",
                terminal="robo_cli.setup.setup_terminal_backend",
                agent="robo_cli.setup.setup_agent_settings",
                gateway="robo_cli.setup.setup_gateway",
                tools="robo_cli.setup.setup_tools",
            )
            from robo_cli.setup import run_setup_wizard
            run_setup_wizard(args)

        # No menu shown.
        m["prompt_choice"].assert_not_called()
        # Quick-setup path NOT taken.
        m["quick"].assert_not_called()
        # Model/terminal/gateway/tools run; agent settings are no longer
        # prompted on existing installs (they keep their tuned values).
        m["model"].assert_called_once()
        m["terminal"].assert_called_once()
        m["agent"].assert_not_called()
        m["gateway"].assert_called_once()
        m["tools"].assert_called_once()


class TestQuickFlag:
    """`--quick` on an existing install runs the fill-missing flow."""

    def test_quick_flag_runs_quick_setup_only(self, existing_install):
        args = _make_setup_args(quick=True)

        with ExitStack() as stack:
            m = _enter_existing_install_patches(
                stack,
                quick="robo_cli.setup._run_quick_setup",
                model="robo_cli.setup.setup_model_provider",
                terminal="robo_cli.setup.setup_terminal_backend",
                agent="robo_cli.setup.setup_agent_settings",
                gateway="robo_cli.setup.setup_gateway",
                tools="robo_cli.setup.setup_tools",
            )
            from robo_cli.setup import run_setup_wizard
            run_setup_wizard(args)

        m["quick"].assert_called_once()
        # Full reconfigure sections must NOT run.
        m["model"].assert_not_called()
        m["terminal"].assert_not_called()
        m["agent"].assert_not_called()
        m["gateway"].assert_not_called()
        m["tools"].assert_not_called()


class TestFreshInstall:
    """On a fresh install (no active provider), flags are no-ops."""


    def test_reconfigure_on_fresh_install_falls_through(self, fresh_install):
        """On a fresh install, --reconfigure shows the setup-mode menu; the
        default choice (Full setup) falls through to run every section in
        sequence, same as an existing-install reconfigure — there is no
        dedicated quick-setup function anymore (Ignitee Now Portal's one-shot
        quick-setup path was removed along with the provider itself)."""
        args = _make_setup_args(reconfigure=True)

        with ExitStack() as stack:
            m = _enter_fresh_install_patches(
                stack,
                prompt=("robo_cli.setup.prompt_choice", {"return_value": 0}),
                model="robo_cli.setup.setup_model_provider",
                terminal="robo_cli.setup.setup_terminal_backend",
                agent="robo_cli.setup.setup_agent_settings",
                gateway="robo_cli.setup.setup_gateway",
                tools="robo_cli.setup.setup_tools",
            )
            from robo_cli.setup import run_setup_wizard
            run_setup_wizard(args)

        m["prompt"].assert_called_once()
        m["model"].assert_called_once()


class TestArgparse:
    """The flags are plumbed through argparse to cmd_setup."""

    def test_reconfigure_flag_reaches_cmd_setup(self, monkeypatch):
        import sys
        from robo_cli.main import main

        captured = {}
        monkeypatch.setattr(
            "robo_cli.setup.run_setup_wizard",
            lambda args: captured.setdefault("args", args),
        )
        monkeypatch.setattr(sys, "argv", ["robo", "setup", "--reconfigure"])
        try:
            main()
        except SystemExit:
            pass
        assert captured["args"].reconfigure is True
        assert captured["args"].quick is False


