"""Cross-surface contract for the persistent /approvals mode command."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import yaml

from cli import RoboCLI
from robo_cli.commands import (
    GATEWAY_KNOWN_COMMANDS,
    SUBCOMMANDS,
    SlashCommandCompleter,
    gateway_help_lines,
    resolve_command,
    telegram_bot_commands,
)
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document


def _completions(text: str) -> set[str]:
    return {
        item.text
        for item in SlashCommandCompleter().get_completions(
            Document(text=text), CompleteEvent(completion_requested=True)
        )
    }


def test_approvals_registry_drives_help_menu_and_autocomplete():
    command = resolve_command("approvals")
    assert command is not None
    assert command.category == "Configuration"
    assert command.args_hint == "[manual|smart|off]"
    assert SUBCOMMANDS["/approvals"] == ["manual", "smart", "off"]
    assert "approvals" in GATEWAY_KNOWN_COMMANDS
    assert any("/approvals" in line for line in gateway_help_lines())
    assert "approvals" in {name for name, _ in telegram_bot_commands()}
    assert _completions("/approvals ") == {"manual", "smart", "off"}


def _isolate_config(monkeypatch, home):
    monkeypatch.setenv("ROBO_HOME", str(home))
    monkeypatch.setenv("ROBO_MANAGED_DIR", str(home / "missing-managed"))
    from robo_cli import managed_scope
    from robo_cli.config import _LOAD_CONFIG_CACHE, _RAW_CONFIG_CACHE

    _LOAD_CONFIG_CACHE.clear()
    _RAW_CONFIG_CACHE.clear()
    managed_scope.invalidate_managed_cache()






def test_shared_command_refuses_managed_mode_override(tmp_path, monkeypatch):
    from robo_cli import managed_scope
    from robo_cli.approval_mode import run_approval_mode_command

    home = tmp_path / "home"
    managed = tmp_path / "managed"
    home.mkdir()
    managed.mkdir()
    monkeypatch.setenv("ROBO_HOME", str(home))
    monkeypatch.setenv("ROBO_MANAGED_DIR", str(managed))
    (managed / "config.yaml").write_text("approvals:\n  mode: manual\n", encoding="utf-8")
    managed_scope.invalidate_managed_cache()

    result = run_approval_mode_command("off")

    assert result.ok is False
    assert result.mode == "manual"
    assert result.changed is False
    assert "managed" in result.message.lower()
    assert not (home / "config.yaml").exists()






