"""Tests for agent/system_prompt.py — context-file cwd wiring."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.prompt_builder import TASK_COMPLETION_GUIDANCE, TASK_FOCUS_GUIDANCE, VERIFICATION_GUIDANCE, CLAIM_VERIFICATION_CHANNEL_NOTE
from agent.system_prompt import build_system_prompt, build_system_prompt_parts


def _make_agent(**overrides):
    base = dict(
        load_soul_identity=False,
        skip_context_files=False,
        valid_tool_names=[],
        _task_completion_guidance=False,
        _task_focus_guidance=False,
        _verification_guidance=False,
        _claim_verification=False,
        _tool_use_enforcement=False,
        _environment_probe=False,
        _kanban_worker_guidance="",
        _memory_store=None,
        _memory_manager=None,
        model="",
        provider="",
        platform="",
        pass_session_id=False,
        session_id="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _captured_context_cwd(agent):
    """The cwd build_system_prompt_parts hands to build_context_files_prompt."""
    captured = {}

    def fake_context_files(
        cwd=None, skip_soul=False, context_length=None,
        allow_install_tree_fallback=False,
    ):
        captured["cwd"] = cwd
        return ""

    with (
        patch("run_agent.load_soul_md", return_value=""),
        patch("run_agent.build_igniteenow_subscription_prompt", return_value=""),
        patch("run_agent.build_environment_hints", return_value=""),
        patch("run_agent.build_context_files_prompt", side_effect=fake_context_files),
    ):
        build_system_prompt_parts(agent)
    return captured["cwd"]


class TestContextFileCwd:
    def test_none_when_terminal_cwd_unset(self, monkeypatch):
        # Unset → None, so discovery falls back to the launch dir inside
        # build_context_files_prompt (the local-CLI #19242 contract).
        monkeypatch.delenv("TERMINAL_CWD", raising=False)
        assert _captured_context_cwd(_make_agent()) is None

    def test_configured_dir_when_terminal_cwd_set(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))
        assert _captured_context_cwd(_make_agent()) == tmp_path


def _stable_prompt(agent):
    with (
        patch("run_agent.load_soul_md", return_value=""),
        patch("run_agent.build_igniteenow_subscription_prompt", return_value=""),
        patch("run_agent.build_environment_hints", return_value=""),
        patch("run_agent.build_context_files_prompt", return_value=""),
    ):
        return build_system_prompt_parts(agent)["stable"]


def _prompt_parts(agent):
    with (
        patch("run_agent.load_soul_md", return_value=""),
        patch("run_agent.build_igniteenow_subscription_prompt", return_value=""),
        patch("run_agent.build_environment_hints", return_value=""),
        patch("run_agent.build_context_files_prompt", return_value=""),
    ):
        return build_system_prompt_parts(agent)


def _init_code_repo(path):
    """A git repo that actually holds code — the coding posture requires a source
    file (or manifest), not a bare ``.git`` (a prose/notes repo stays general)."""
    import subprocess

    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    (path / "main.py").write_text("print('hi')\n")


class TestCodingContextBlock:
    def test_injected_when_active(self, monkeypatch, tmp_path):
        _init_code_repo(tmp_path)
        monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))
        agent = _make_agent(valid_tool_names=["read_file"], platform="cli")
        parts = _prompt_parts(agent)
        assert "coding agent" in parts["stable"]
        assert "Workspace" in parts["context"]

    def test_absent_when_off(self, monkeypatch, tmp_path):
        _init_code_repo(tmp_path)
        monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))
        agent = _make_agent(valid_tool_names=["read_file"], platform="cli")
        # Drive the real path: force the resolved mode to "off" via config.
        with patch("agent.coding_context._coding_mode", return_value="off"):
            stable = _stable_prompt(agent)
        assert "coding agent" not in stable

    def test_absent_without_tools(self, monkeypatch, tmp_path):
        _init_code_repo(tmp_path)
        monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))
        agent = _make_agent(valid_tool_names=[], platform="cli")
        assert "coding agent" not in _stable_prompt(agent)


def test_build_system_prompt_records_stable_prefix():
    agent = _make_agent()
    with (
        patch("run_agent.load_soul_md", return_value=""),
        patch("run_agent.build_igniteenow_subscription_prompt", return_value=""),
        patch("run_agent.build_environment_hints", return_value=""),
        patch("run_agent.build_context_files_prompt", return_value="context"),
    ):
        prompt = build_system_prompt(agent)

    assert prompt.startswith(agent._cached_system_prompt_static)
    assert prompt[len(agent._cached_system_prompt_static):].startswith("\n\ncontext")


def test_coding_prompt_preserves_legacy_workspace_order(monkeypatch):
    """The cache split must not reorder the stored coding prompt."""
    import agent.system_prompt as system_prompt

    agent = _make_agent(
        valid_tool_names=["read_file"],
        _parallel_tool_call_guidance=False,
    )
    monkeypatch.setattr(system_prompt, "DEFAULT_AGENT_IDENTITY", "IDENTITY")
    monkeypatch.setattr(system_prompt, "ROBO_AGENT_HELP_GUIDANCE", "HELP")
    monkeypatch.setattr(system_prompt, "STEER_CHANNEL_NOTE", "STEER")
    monkeypatch.setattr(system_prompt, "get_robo_home", lambda: Path("/robo"))

    expected_profile = (
        "Active Robo profile: default. Other profiles (if any) live "
        "under /robo/profiles/<name>/. Each profile has its own skills/, "
        "plugins/, cron/, and memories/ that affect a different session than "
        "this one. Do not modify another profile's skills/plugins/cron/memories "
        "unless the user explicitly directs you to."
    )
    expected = "\n\n".join((
        "IDENTITY",
        "HELP",
        "STEER",
        "CODING_STABLE",
        "WORKSPACE",
        "Operator instructions (from config):\nOPERATOR",
        expected_profile,
        "SYSTEM_MESSAGE",
        "CONTEXT_FILES",
        "Conversation started: Friday, January 02, 2026",
    ))

    with (
        patch("run_agent.load_soul_md", return_value=""),
        patch("run_agent.build_igniteenow_subscription_prompt", return_value=""),
        patch("run_agent.build_environment_hints", return_value=""),
        patch("run_agent.build_context_files_prompt", return_value="CONTEXT_FILES"),
        patch(
            "agent.coding_context.coding_system_prompt_parts",
            return_value=(
                ["CODING_STABLE"],
                ["WORKSPACE"],
                ["Operator instructions (from config):\nOPERATOR"],
            ),
        ),
        patch("agent.file_safety._resolve_active_profile_name", return_value="default"),
        patch("robo_time.now", return_value=datetime(2026, 1, 2)),
    ):
        prompt = build_system_prompt(agent, system_message="SYSTEM_MESSAGE")

    assert prompt == expected
    assert agent._cached_system_prompt_static == "\n\n".join(expected.split("\n\n")[:4])


class TestTelegramRichMessagesHint:
    """Verify that TELEGRAM_RICH_MESSAGES_HINT is conditionally included."""

    def test_base_hint_without_rich_messages(self, monkeypatch):
        """When rich_messages is False (default), only the base hint is used."""
        agent = _make_agent(platform="telegram")
        # Mock config to return rich_messages: false (default)
        with patch("robo_cli.config.load_config_readonly") as mock_cfg:
            mock_cfg.return_value = {
                "platforms": {"telegram": {"extra": {"rich_messages": False}}}
            }
            stable = _stable_prompt(agent)
        # Base hint should be present
        assert "Standard Markdown is automatically converted" in stable
        # Rich-messages extension should NOT be present
        assert "lean into it" not in stable
        assert "task lists" not in stable

    def test_rich_hint_with_rich_messages_enabled(self, monkeypatch):
        """When rich_messages is True, the rich-messages extension is appended."""
        agent = _make_agent(platform="telegram")
        with patch("robo_cli.config.load_config_readonly") as mock_cfg:
            mock_cfg.return_value = {
                "platforms": {"telegram": {"extra": {"rich_messages": True}}}
            }
            stable = _stable_prompt(agent)
        # Base hint should be present
        assert "Standard Markdown is automatically converted" in stable
        # Rich-messages extension should be present
        assert "lean into it" in stable
        assert "task lists" in stable
        assert "math/formulas" in stable

    def test_base_hint_without_config(self, monkeypatch):
        """When config has no telegram section, only base hint is used."""
        agent = _make_agent(platform="telegram")
        with patch("robo_cli.config.load_config_readonly") as mock_cfg:
            mock_cfg.return_value = {}
            stable = _stable_prompt(agent)
        assert "Standard Markdown is automatically converted" in stable
        assert "lean into it" not in stable


_SKILLS = "SKILLS_INDEX_SENTINEL"
_CONTEXT = "CONTEXT_FILES_SENTINEL"


def _build(builder, **overrides):
    """Run a build_* function with skills + context files present."""
    agent = _make_agent(valid_tool_names=["skills_list"], **overrides)
    with (
        patch("run_agent.load_soul_md", return_value=""),
        patch("run_agent.build_igniteenow_subscription_prompt", return_value=""),
        patch("run_agent.build_environment_hints", return_value=""),
        patch("run_agent.build_context_files_prompt", return_value=_CONTEXT),
        patch("run_agent.get_toolset_for_tool", return_value=None),
        patch("run_agent.build_skills_system_prompt", return_value=_SKILLS),
    ):
        return builder(agent)


class TestSkillsInVolatileBand:
    """The skills index is runtime-mutable, so it lives in the volatile band,
    not the stable band, to keep the cached stable prefix reusable when a
    rebuild picks up a skill change."""

    def test_skills_not_in_stable_band(self):
        parts = _build(build_system_prompt_parts)
        assert _SKILLS not in parts["stable"]

    def test_skills_lead_the_volatile_band(self):
        parts = _build(build_system_prompt_parts)
        assert parts["volatile"].startswith(_SKILLS)

    def test_full_order_is_stable_context_then_skills(self):
        # build_system_prompt joins stable + context + volatile, so the skills
        # index renders after the context files and before the per-turn
        # memory/timestamp tail.
        full = _build(build_system_prompt)
        assert full.index(_CONTEXT) < full.index(_SKILLS)
        assert full.index(_SKILLS) < full.index("Conversation started:")


class TestTaskFocusGuidance:
    """The 'stay on task' block added alongside task_completion_guidance —
    real end-to-end checks that it's actually wired into the built prompt,
    not just present as an unused constant."""

    def test_included_when_enabled_with_tools(self):
        parts = _build(build_system_prompt_parts, _task_focus_guidance=True)
        assert TASK_FOCUS_GUIDANCE in parts["stable"]

    def test_excluded_when_toggled_off(self):
        parts = _build(build_system_prompt_parts, _task_focus_guidance=False)
        assert TASK_FOCUS_GUIDANCE not in parts["stable"]

    def test_excluded_with_no_tools_even_if_enabled(self):
        # Matches task_completion_guidance's own gating: guidance about using
        # tools (the todo tool) makes no sense in a toolless prompt.
        agent = _make_agent(_task_focus_guidance=True, valid_tool_names=[])
        with (
            patch("run_agent.load_soul_md", return_value=""),
            patch("run_agent.build_igniteenow_subscription_prompt", return_value=""),
            patch("run_agent.build_environment_hints", return_value=""),
            patch("run_agent.build_context_files_prompt", return_value=""),
        ):
            parts = build_system_prompt_parts(agent)
        assert TASK_FOCUS_GUIDANCE not in parts["stable"]

    def test_lands_in_stable_tier_not_volatile(self):
        # Stable tier is the cross-session-cacheable prefix — this is static
        # guidance, not per-turn state, so it must never land in volatile.
        parts = _build(build_system_prompt_parts, _task_focus_guidance=True)
        assert TASK_FOCUS_GUIDANCE not in parts["volatile"]
        assert TASK_FOCUS_GUIDANCE not in parts["context"]

    def test_independent_of_task_completion_guidance_toggle(self):
        # The two are separate flags — a user can enable one without the
        # other (that's the whole reason this is a second flag, not folded
        # into the existing one).
        parts = _build(
            build_system_prompt_parts,
            _task_focus_guidance=True,
            _task_completion_guidance=False,
        )
        assert TASK_FOCUS_GUIDANCE in parts["stable"]
        assert TASK_COMPLETION_GUIDANCE not in parts["stable"]


class TestVerificationGuidance:
    """The 'verify before you claim' block added alongside task_focus_guidance
    — real end-to-end checks that it's actually wired into the built prompt,
    not just present as an unused constant."""

    def test_included_when_enabled_with_tools(self):
        parts = _build(build_system_prompt_parts, _verification_guidance=True)
        assert VERIFICATION_GUIDANCE in parts["stable"]

    def test_excluded_when_toggled_off(self):
        parts = _build(build_system_prompt_parts, _verification_guidance=False)
        assert VERIFICATION_GUIDANCE not in parts["stable"]

    def test_excluded_with_no_tools_even_if_enabled(self):
        # Matches the other two blocks' own gating: guidance about verifying
        # via tool use makes no sense in a toolless prompt.
        agent = _make_agent(_verification_guidance=True, valid_tool_names=[])
        with (
            patch("run_agent.load_soul_md", return_value=""),
            patch("run_agent.build_igniteenow_subscription_prompt", return_value=""),
            patch("run_agent.build_environment_hints", return_value=""),
            patch("run_agent.build_context_files_prompt", return_value=""),
        ):
            parts = build_system_prompt_parts(agent)
        assert VERIFICATION_GUIDANCE not in parts["stable"]

    def test_lands_in_stable_tier_not_volatile(self):
        # Stable tier is the cross-session-cacheable prefix — this is static
        # guidance, not per-turn state, so it must never land in volatile.
        parts = _build(build_system_prompt_parts, _verification_guidance=True)
        assert VERIFICATION_GUIDANCE not in parts["volatile"]
        assert VERIFICATION_GUIDANCE not in parts["context"]

    def test_independent_of_the_other_two_guidance_toggles(self):
        # Three separate flags — a user can enable any one without the
        # others (that's the whole reason this is a third flag, not folded
        # into either existing one).
        parts = _build(
            build_system_prompt_parts,
            _verification_guidance=True,
            _task_focus_guidance=False,
            _task_completion_guidance=False,
        )
        assert VERIFICATION_GUIDANCE in parts["stable"]
        assert TASK_FOCUS_GUIDANCE not in parts["stable"]
        assert TASK_COMPLETION_GUIDANCE not in parts["stable"]


class TestClaimVerificationChannelNote:
    """The channel note explaining the automated-verification marker to the
    model — gated on its own toggle (unlike STEER_CHANNEL_NOTE, which is
    always live), since the underlying feature is off by default and a
    disabled feature shouldn't spend prompt tokens explaining a marker the
    model will never see."""

    def test_excluded_when_feature_disabled(self):
        parts = _build(build_system_prompt_parts, _claim_verification=False)
        assert CLAIM_VERIFICATION_CHANNEL_NOTE not in parts["stable"]

    def test_included_when_feature_enabled_with_tools(self):
        parts = _build(build_system_prompt_parts, _claim_verification=True)
        assert CLAIM_VERIFICATION_CHANNEL_NOTE in parts["stable"]

    def test_excluded_with_no_tools_even_if_enabled(self):
        # The marker only ever lands inside a tool result, so it's only
        # reachable when the agent has tools — same reasoning as
        # STEER_CHANNEL_NOTE's own no-tools exclusion.
        agent = _make_agent(_claim_verification=True, valid_tool_names=[])
        with (
            patch("run_agent.load_soul_md", return_value=""),
            patch("run_agent.build_igniteenow_subscription_prompt", return_value=""),
            patch("run_agent.build_environment_hints", return_value=""),
            patch("run_agent.build_context_files_prompt", return_value=""),
        ):
            parts = build_system_prompt_parts(agent)
        assert CLAIM_VERIFICATION_CHANNEL_NOTE not in parts["stable"]
