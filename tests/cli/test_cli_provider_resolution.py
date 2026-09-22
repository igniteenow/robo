import importlib
import sys
import types
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from robo_cli.auth import AuthError
from robo_cli import main as robo_main


# ---------------------------------------------------------------------------
# Module isolation: _import_cli() wipes tools.* / cli / run_agent from
# sys.modules so it can re-import cli fresh.  Without cleanup the wiped
# modules leak into subsequent tests, breaking
# mock patches that target "tools.file_tools._get_file_ops" etc.
# ---------------------------------------------------------------------------

def _reset_modules(prefixes: tuple[str, ...]):
    for name in list(sys.modules):
        if any(name == p or name.startswith(p + ".") for p in prefixes):
            sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _restore_cli_and_tool_modules():
    """Save and restore tools/cli/run_agent modules around every test."""
    prefixes = ("tools", "cli", "run_agent")
    original_modules = {
        name: module
        for name, module in sys.modules.items()
        if any(name == p or name.startswith(p + ".") for p in prefixes)
    }
    try:
        yield
    finally:
        _reset_modules(prefixes)
        sys.modules.update(original_modules)


def _install_prompt_toolkit_stubs():
    class _Dummy:
        def __init__(self, *args, **kwargs):
            pass

    class _Condition:
        def __init__(self, func):
            self.func = func

        def __bool__(self):
            return bool(self.func())

    class _ANSI(str):
        pass

    root = types.ModuleType("prompt_toolkit")
    history = types.ModuleType("prompt_toolkit.history")
    styles = types.ModuleType("prompt_toolkit.styles")
    patch_stdout = types.ModuleType("prompt_toolkit.patch_stdout")
    application = types.ModuleType("prompt_toolkit.application")
    layout = types.ModuleType("prompt_toolkit.layout")
    processors = types.ModuleType("prompt_toolkit.layout.processors")
    filters = types.ModuleType("prompt_toolkit.filters")
    dimension = types.ModuleType("prompt_toolkit.layout.dimension")
    menus = types.ModuleType("prompt_toolkit.layout.menus")
    widgets = types.ModuleType("prompt_toolkit.widgets")
    key_binding = types.ModuleType("prompt_toolkit.key_binding")
    completion = types.ModuleType("prompt_toolkit.completion")
    formatted_text = types.ModuleType("prompt_toolkit.formatted_text")

    history.FileHistory = _Dummy
    styles.Style = _Dummy
    patch_stdout.patch_stdout = lambda *args, **kwargs: nullcontext()
    application.Application = _Dummy
    layout.Layout = _Dummy
    layout.HSplit = _Dummy
    layout.Window = _Dummy
    layout.FormattedTextControl = _Dummy
    layout.ConditionalContainer = _Dummy
    processors.Processor = _Dummy
    processors.Transformation = _Dummy
    processors.PasswordProcessor = _Dummy
    processors.ConditionalProcessor = _Dummy
    filters.Condition = _Condition
    dimension.Dimension = _Dummy
    menus.CompletionsMenu = _Dummy
    widgets.TextArea = _Dummy
    key_binding.KeyBindings = _Dummy
    completion.Completer = _Dummy
    completion.Completion = _Dummy
    formatted_text.ANSI = _ANSI
    root.print_formatted_text = lambda *args, **kwargs: None

    sys.modules.setdefault("prompt_toolkit", root)
    sys.modules.setdefault("prompt_toolkit.history", history)
    sys.modules.setdefault("prompt_toolkit.styles", styles)
    sys.modules.setdefault("prompt_toolkit.patch_stdout", patch_stdout)
    sys.modules.setdefault("prompt_toolkit.application", application)
    sys.modules.setdefault("prompt_toolkit.layout", layout)
    sys.modules.setdefault("prompt_toolkit.layout.processors", processors)
    sys.modules.setdefault("prompt_toolkit.filters", filters)
    sys.modules.setdefault("prompt_toolkit.layout.dimension", dimension)
    sys.modules.setdefault("prompt_toolkit.layout.menus", menus)
    sys.modules.setdefault("prompt_toolkit.widgets", widgets)
    sys.modules.setdefault("prompt_toolkit.key_binding", key_binding)
    sys.modules.setdefault("prompt_toolkit.completion", completion)
    sys.modules.setdefault("prompt_toolkit.formatted_text", formatted_text)


def _import_cli():
    for name in list(sys.modules):
        if name == "cli" or name == "run_agent" or name == "tools" or name.startswith("tools."):
            sys.modules.pop(name, None)

    if "firecrawl" not in sys.modules:
        sys.modules["firecrawl"] = types.SimpleNamespace(Firecrawl=object)

    try:
        importlib.import_module("prompt_toolkit")
    except ModuleNotFoundError:
        _install_prompt_toolkit_stubs()
    return importlib.import_module("cli")


def test_robo_cli_init_does_not_eagerly_resolve_runtime_provider(monkeypatch):
    cli = _import_cli()
    calls = {"count": 0}

    def _unexpected_runtime_resolve(**kwargs):
        calls["count"] += 1
        raise AssertionError("resolve_runtime_provider should not be called in RoboCLI.__init__")

    monkeypatch.setattr("robo_cli.runtime_provider.resolve_runtime_provider", _unexpected_runtime_resolve)
    monkeypatch.setattr("robo_cli.runtime_provider.format_runtime_provider_error", lambda exc: str(exc))

    shell = cli.RoboCLI(model="gpt-5", compact=True, max_turns=1)

    assert shell is not None
    assert calls["count"] == 0


def test_runtime_resolution_failure_is_not_sticky(monkeypatch):
    cli = _import_cli()
    calls = {"count": 0}

    def _runtime_resolve(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary auth failure")
        return {
            "provider": "openrouter",
            "api_mode": "chat_completions",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "test-key",
            "source": "env/config",
        }

    class _DummyAgent:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr("robo_cli.runtime_provider.resolve_runtime_provider", _runtime_resolve)
    monkeypatch.setattr("robo_cli.runtime_provider.format_runtime_provider_error", lambda exc: str(exc))
    monkeypatch.setattr(cli, "AIAgent", _DummyAgent)

    shell = cli.RoboCLI(model="gpt-5", compact=True, max_turns=1)

    assert shell._init_agent() is False
    assert shell._init_agent() is True
    assert calls["count"] == 2
    assert shell.agent is not None




def test_cli_turn_routing_uses_primary_when_disabled(monkeypatch):
    cli = _import_cli()
    shell = cli.RoboCLI(model="gpt-5", compact=True, max_turns=1)
    shell.provider = "openrouter"
    shell.api_mode = "chat_completions"
    shell.base_url = "https://openrouter.ai/api/v1"
    shell.api_key = "sk-primary"

    result = shell._resolve_turn_agent_config("what time is it in tokyo?")

    assert result["model"] == "gpt-5"
    assert result["runtime"]["provider"] == "openrouter"












def test_codex_provider_uses_config_model(monkeypatch):
    """Model comes from config.yaml, not LLM_MODEL env var.
    Config.yaml is the single source of truth to avoid multi-agent conflicts."""
    cli = _import_cli()

    # LLM_MODEL env var should be IGNORED (even if set)
    monkeypatch.setenv("LLM_MODEL", "should-be-ignored")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    # Set model via config
    monkeypatch.setitem(cli.CLI_CONFIG, "model", {
        "default": "gpt-5.2-codex",
        "provider": "openai-codex",
        "base_url": "https://chatgpt.com/backend-api/codex",
    })

    def _runtime_resolve(**kwargs):
        return {
            "provider": "openai-codex",
            "api_mode": "codex_responses",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_key": "fake-codex-token",
            "source": "env/config",
        }

    monkeypatch.setattr("robo_cli.runtime_provider.resolve_runtime_provider", _runtime_resolve)
    monkeypatch.setattr("robo_cli.runtime_provider.format_runtime_provider_error", lambda exc: str(exc))
    # Prevent live API call from overriding the config model
    monkeypatch.setattr(
        "robo_cli.codex_models.get_codex_model_ids",
        lambda access_token=None: ["gpt-5.2-codex"],
    )

    shell = cli.RoboCLI(compact=True, max_turns=1)

    assert shell._ensure_runtime_credentials() is True
    assert shell.provider == "openai-codex"
    # Model from config (may be normalized by codex provider logic)
    assert "codex" in shell.model.lower()
    # LLM_MODEL env var is NOT used
    assert shell.model != "should-be-ignored"










def test_model_flow_custom_saves_verified_v1_base_url(monkeypatch, capsys):
    monkeypatch.setattr(
        "robo_cli.config.get_env_value",
        lambda key: "" if key in {"OPENAI_BASE_URL", "OPENAI_API_KEY"} else "",
    )
    saved_env = {}
    monkeypatch.setattr("robo_cli.config.save_env_value", lambda key, value: saved_env.__setitem__(key, value))
    monkeypatch.setattr("robo_cli.auth._save_model_choice", lambda model: saved_env.__setitem__("MODEL", model))
    monkeypatch.setattr("robo_cli.auth.deactivate_provider", lambda: None)
    monkeypatch.setattr("robo_cli.main._save_custom_provider", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "robo_cli.models.probe_api_models",
        lambda api_key, base_url: {
            "models": ["llm"],
            "probed_url": "http://localhost:8000/v1/models",
            "resolved_base_url": "http://localhost:8000/v1",
            "suggested_base_url": "http://localhost:8000/v1",
            "used_fallback": True,
        },
    )
    monkeypatch.setattr(
        "robo_cli.config.load_config",
        lambda: {"model": {"default": "", "provider": "custom", "base_url": ""}},
    )
    monkeypatch.setattr("robo_cli.config.save_config", lambda cfg: None)

    # After the probe detects a single model ("llm"), the flow asks
    # "Use this model? [Y/n]:" — confirm with Enter, then context length,
    # then display name. The api_mode prompt also runs before model selection.
    answers = iter(["http://localhost:8000", "local-key", "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr("robo_cli.secret_prompt.masked_secret_prompt", lambda _prompt="": next(answers))

    robo_main._model_flow_custom({})
    output = capsys.readouterr().out

    assert "Saving the working base URL instead" in output
    assert "Detected model: llm" in output
    # OPENAI_BASE_URL is no longer saved to .env — config.yaml is authoritative
    assert "OPENAI_BASE_URL" not in saved_env
    assert saved_env["MODEL"] == "llm"


def test_model_flow_custom_persists_selected_api_mode(monkeypatch):
    saved_cfg = {"model": {"default": "", "provider": "custom", "base_url": ""}}
    captured_provider = {}

    monkeypatch.setattr(
        "robo_cli.config.get_env_value",
        lambda key: "" if key in {"OPENAI_BASE_URL", "OPENAI_API_KEY"} else "",
    )
    monkeypatch.setattr("robo_cli.auth._save_model_choice", lambda model: None)
    monkeypatch.setattr("robo_cli.auth.deactivate_provider", lambda: None)
    monkeypatch.setattr(
        "robo_cli.models.probe_api_models",
        lambda api_key, base_url: {
            "models": [],
            "probed_url": f"{base_url.rstrip('/')}/models",
            "resolved_base_url": None,
            "suggested_base_url": None,
            "used_fallback": False,
        },
    )
    saved_env = {}
    monkeypatch.setattr("robo_cli.config.load_config", lambda: saved_cfg)
    monkeypatch.setattr("robo_cli.config.save_config", lambda cfg: saved_cfg.update(cfg))
    monkeypatch.setattr(
        "robo_cli.config.save_env_value",
        lambda key, value: saved_env.__setitem__(key, value),
    )
    monkeypatch.setattr(
        "robo_cli.main._save_custom_provider",
        lambda base_url, api_key="", model="", context_length=None, name=None, api_mode=None, key_env="": captured_provider.update(
            {
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
                "context_length": context_length,
                "name": name,
                "api_mode": api_mode,
                "key_env": key_env,
            }
        ),
    )

    answers = iter(
        [
            "https://codex.example.com/v1",
            "3",
            "chosen-model",
            "",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr("robo_cli.secret_prompt.masked_secret_prompt", lambda _prompt="": "test-key")

    robo_main._model_flow_custom({"model": {"provider": "custom"}})

    assert saved_cfg["model"]["provider"] == "custom"
    assert saved_cfg["model"]["base_url"] == "https://codex.example.com/v1"
    assert saved_cfg["model"]["api_mode"] == "codex_responses"
    assert captured_provider["api_mode"] == "codex_responses"

    # The key itself goes to .env; config.yaml only references it (#69449).
    key_env = captured_provider["key_env"]
    assert saved_cfg["model"]["api_key"] == f"${{{key_env}}}"
    assert saved_env[key_env] == "test-key"



# ---------------------------------------------------------------------------
# _auto_provider_name — unit tests
# ---------------------------------------------------------------------------

def test_auto_provider_name_localhost():
    from robo_cli.main import _auto_provider_name
    assert _auto_provider_name("http://localhost:11434/v1") == "Local (localhost:11434)"
    assert _auto_provider_name("http://127.0.0.1:1234/v1") == "Local (127.0.0.1:1234)"






def test_save_custom_provider_uses_provided_name(monkeypatch, tmp_path):
    """When a display name is passed, it should appear in the saved entry."""
    import yaml
    from robo_cli.main import _save_custom_provider

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump({}))

    monkeypatch.setattr(
        "robo_cli.config.load_config", lambda: yaml.safe_load(cfg_path.read_text()) or {},
    )
    saved = {}
    def _save(cfg):
        saved.update(cfg)
    monkeypatch.setattr("robo_cli.config.save_config", _save)

    _save_custom_provider("http://localhost:11434/v1", name="Ollama")
    entries = saved.get("custom_providers", [])
    assert len(entries) == 1
    assert entries[0]["name"] == "Ollama"


def test_save_custom_provider_references_the_key_instead_of_inlining_it(monkeypatch, tmp_path):
    """With key_env set the entry must not carry the secret (#69449)."""
    import yaml
    from robo_cli.main import _save_custom_provider

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump({}))
    monkeypatch.setattr(
        "robo_cli.config.load_config", lambda: yaml.safe_load(cfg_path.read_text()) or {},
    )
    saved = {}
    monkeypatch.setattr("robo_cli.config.save_config", lambda cfg: saved.update(cfg))

    _save_custom_provider(
        "http://localhost:11434/v1",
        api_key="sk-secret",
        name="Ollama",
        key_env="ROBO_CUSTOM_LOCALHOST_11434_API_KEY",
    )

    entry = saved["custom_providers"][0]
    assert entry["key_env"] == "ROBO_CUSTOM_LOCALHOST_11434_API_KEY"
    assert "api_key" not in entry
    assert "sk-secret" not in yaml.safe_dump(saved)




def test_custom_endpoint_key_env_is_a_valid_posix_name_for_ip_endpoints():
    """Every IP-based local endpoint slugs to a digit-leading name.

    ``save_env_value`` rejects names that don't match
    ``[A-Za-z_][A-Za-z0-9_]*``, so deriving ``127_0_0_1_8080_API_KEY`` would
    raise on exactly the local-proxy setups this is meant to protect. The
    fixed prefix makes the result valid by construction.
    """
    import re

    from robo_cli.config import _ENV_VAR_NAME_RE, custom_endpoint_key_env

    for identity in ("127.0.0.1_8080", "0.0.0.0", "10.0.0.7:11434", "", "-–-"):
        assert _ENV_VAR_NAME_RE.match(custom_endpoint_key_env(identity)), identity


