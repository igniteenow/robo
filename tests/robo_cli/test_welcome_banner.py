"""Tests for robo_cli.welcome_banner. Copyright (c) 2026 Ignitee Now.

The banner is reached through ``robo_cli.banner`` (the public import path), and
collaborators are replaced on that module, exactly as callers do.
"""

import io
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from rich.console import Console

import model_tools
import robo_cli.banner as banner
import tools.mcp_tool


@pytest.fixture(autouse=True)
def brand_skin():
    from robo_cli import skin_engine

    skin_engine.set_active_skin("robo")
    yield
    skin_engine._active_skin, skin_engine._active_skin_name = None, "default"


def render(width=160, colour=False, skills=None, update=None, unavailable=None, mcp=None, release=None, git=None, **kwargs):
    with ExitStack() as stack:
        stack.enter_context(patch.object(model_tools, "check_tool_availability", return_value=([], unavailable or [])))
        stack.enter_context(patch.object(tools.mcp_tool, "get_mcp_status", return_value=mcp or []))
        stack.enter_context(patch.object(banner, "get_available_skills", return_value=skills or {}))
        stack.enter_context(patch.object(banner, "get_update_result", return_value=update))
        stack.enter_context(patch.object(banner, "get_latest_release_tag", return_value=release))
        stack.enter_context(patch.object(banner, "get_git_banner_state", return_value=git))
        buf = io.StringIO()
        console = Console(file=buf, record=True, width=width, force_terminal=colour,
                          color_system="truecolor" if colour else None)
        params = dict(console=console, model="anthropic/claude-test", cwd="/tmp/project", tools=[])
        params.update(kwargs)
        banner.build_welcome_banner(**params)
        return buf.getvalue() if colour else console.export_text()


class TestHelpers:
    @pytest.mark.parametrize("tokens, expected", [
        (900, "900"), (1000, "1K"), (8192, "8K"), (128000, "128K"), (200000, "200K"), (999_499, "999K"),
        (1_000_000, "1M"), (1_048_576, "1M"), (1_500_000, "1.5M"), (2_000_000, "2M"), ("n/a", "n/a"), (None, "None"),
    ])
    def test_format_context_length(self, tokens, expected):
        assert banner._format_context_length(tokens) == expected

    @pytest.mark.parametrize("raw, expected", [
        ("file_tools", "file"), ("web-tools", "web"), ("browser", "browser"), ("memory_toolset", "memory"),
        ("_tools", "_tools"), ("", "other"), (None, "other"),
    ])
    def test_display_toolset_name(self, raw, expected):
        assert banner._display_toolset_name(raw) == expected

    def test_skin_color_falls_back_when_the_engine_fails(self):
        with patch("robo_cli.skin_engine.get_active_skin", side_effect=RuntimeError("boom")):
            assert banner._skin_color("banner_title", "#123456") == "#123456"

    def test_get_available_skills_survives_a_broken_skills_tool(self):
        with patch("tools.skills_tool._find_all_skills", side_effect=RuntimeError("boom")):
            assert banner.get_available_skills() == {}

    def test_get_available_skills_ignores_malformed_entries(self):
        found = [{"name": "ok", "category": "a"}, {"category": "a"}, "junk", None, {"name": "solo", "category": ""}]
        with patch("tools.skills_tool._find_all_skills", return_value=found):
            assert banner.get_available_skills() == {"a": ["ok"], "general": ["solo"]}


class TestVersionLabel:
    def test_without_git_state(self):
        with patch.object(banner, "get_git_banner_state", return_value=None):
            label = banner.format_banner_version_label()
        assert label.startswith("Robo v") and "upstream" not in label

    def test_local_commits_are_shown(self):
        state = {"upstream": "aaaa1111", "local": "bbbb2222", "ahead": 3}
        with patch.object(banner, "get_git_banner_state", return_value=state):
            assert banner.format_banner_version_label().endswith("· upstream aaaa1111 · local bbbb2222 (+3)")

    def test_a_failing_git_probe_does_not_break_the_label(self):
        with patch.object(banner, "get_git_banner_state", side_effect=OSError("no git")):
            assert banner.format_banner_version_label().startswith("Robo v")

    def test_a_custom_skin_renames_the_title(self, tmp_path, monkeypatch):
        import yaml

        from robo_cli import skin_engine

        (tmp_path / "skins").mkdir()
        (tmp_path / "skins" / "acme.yaml").write_text(yaml.dump({"name": "acme", "branding": {"agent_name": "Acme Bot"}}))
        monkeypatch.setattr(skin_engine, "_skins_dir", lambda: tmp_path / "skins")
        skin_engine.set_active_skin("acme")
        assert "Acme Bot v" in render()


class TestContent:
    def test_core_facts_are_shown(self):
        out = render(session_id="sess-42", provider="openrouter", context_length=200000)
        for expected in ("claude-test", "/tmp/project", "sess-42", "openrouter", "200K context", "Robo v"):
            assert expected in out
        assert "anthropic/" not in out  # the vendor prefix is dropped

    def test_deep_model_paths_show_the_last_segment(self):
        assert "llama-v3" in render(model="accounts/fireworks/models/llama-v3")

    def test_square_brackets_in_dynamic_text_are_shown_literally(self):
        out = render(model="org/[bold]model[red]", cwd="/tmp/[red]dir", session_id="[x]",
                     skills={"[cat]": ["[skill]"]})
        for literal in ("[bold]model[red]", "/tmp/[red]dir", "[x]", "[cat]", "[skill]"):
            assert literal in out

    def test_tools_are_grouped_by_toolset(self):
        tools_list = [{"function": {"name": n}} for n in ("read_file", "write_file", "web_search")] + [{}, {"function": {}}]
        mapping = {"read_file": "file_tools", "write_file": "file_tools", "web_search": "web"}
        out = render(tools=tools_list, get_toolset_for_tool=mapping.get)
        assert "Tools" in out and "read_file, write_file" in out and "web_search" in out
        assert "file_tools" not in out

    def test_a_failing_toolset_lookup_lands_in_other(self):
        def lookup(name):
            raise KeyError(name)

        assert "other" in render(tools=[{"function": {"name": "mystery"}}], get_toolset_for_tool=lookup)

    def test_unavailable_toolsets_say_what_they_need(self):
        unavailable = [{"name": "browser_tools", "env_vars": ["BROWSER_KEY"], "tools": ["open"]}, {"name": "vision", "env_vars": []}]
        out = render(unavailable=unavailable)
        assert "Unavailable" in out and "needs BROWSER_KEY" in out and "not configured" in out

    def test_unavailable_is_limited_to_enabled_toolsets(self):
        unavailable = [{"name": "browser", "env_vars": ["K"]}, {"name": "vision", "env_vars": ["V"]}]
        out = render(unavailable=unavailable, enabled_toolsets=["browser"])
        assert "needs K" in out and "needs V" not in out

    def test_mcp_server_states(self):
        servers = [
            {"name": "github", "transport": "stdio", "tools": 12, "connected": True},
            {"name": "files", "transport": "http", "tools": ["a", "b"], "connected": True},
            {"name": "legacy", "disabled": True},
            {"name": "flaky", "connected": False, "status": "timeout"},
            "junk",
        ]
        out = render(mcp=servers)
        assert "MCP servers" in out and "12 tools" in out and "2 tools" in out
        assert "disabled" in out and "timeout" in out

    def test_moa_provider_is_labelled(self):
        out = render(model="council", provider="moa")
        assert "MoA: council" in out

    @pytest.mark.parametrize("result, expected", [(5, "5 updates behind"), (1, "1 update behind")])
    def test_update_notice_counts(self, result, expected):
        out = render(update=result)
        assert expected in out and "robo update" in out

    def test_update_notice_names_the_right_command_for_this_install(self):
        with patch("robo_cli.config.recommended_update_command", return_value="brew upgrade robo"):
            out = render(update=2)
        assert "brew upgrade robo" in out and "robo update" not in out

    def test_update_notice_survives_a_broken_command_lookup(self):
        with patch("robo_cli.config.recommended_update_command", side_effect=RuntimeError("boom")):
            assert "robo update" in render(update=2)

    def test_update_notice_without_a_count(self):
        assert "A newer Robo is available" in render(update=banner.UPDATE_AVAILABLE_NO_COUNT)

    @pytest.mark.parametrize("result", [None, 0])
    def test_no_update_notice_when_current(self, result):
        assert "robo update" not in render(update=result)

    def test_collaborator_failures_never_break_the_banner(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(model_tools, "check_tool_availability", side_effect=RuntimeError("x")))
            stack.enter_context(patch.object(tools.mcp_tool, "get_mcp_status", side_effect=RuntimeError("x")))
            stack.enter_context(patch.object(banner, "get_available_skills", side_effect=RuntimeError("x")))
            stack.enter_context(patch.object(banner, "get_update_result", side_effect=RuntimeError("x")))
            stack.enter_context(patch.object(banner, "get_latest_release_tag", side_effect=RuntimeError("x")))
            console = Console(record=True, width=120, force_terminal=False, color_system=None)
            banner.build_welcome_banner(console=console, model="m", cwd="/x")
        assert "Robo v" in console.export_text()


class TestLayout:
    def test_narrow_terminals_drop_the_art_but_keep_the_facts(self):
        out = render(width=70, session_id="s1")
        assert "claude-test" in out and "s1" in out
        assert all(len(line) <= 70 for line in out.splitlines())

    @pytest.mark.parametrize("width", [40, 80, 100, 160, 240])
    def test_nothing_overflows_the_terminal(self, width):
        skills = {"research": [f"skill-{i:02d}" for i in range(40)], "a-very-long-category-name": ["x"] * 30}
        out = render(width=width, skills=skills)
        assert max(len(line) for line in out.splitlines()) <= width

    def test_long_lists_are_truncated_with_a_count(self):
        out = render(width=100, skills={"research": [f"skill-{i:02d}" for i in range(60)]})
        assert "skill-00" in out and "more" in out and "skill-59" not in out

    def test_a_long_label_is_ellipsized_instead_of_widening_the_column(self):
        out = render(width=120, skills={"an-extremely-long-category-name-indeed": ["alpha"], "short": ["beta"]})
        assert "an-extremely-long…" in out and "indeed" not in out
        assert "alpha" in out and "beta" in out

    def test_the_section_header_carries_the_total(self):
        out = render(skills={"a": ["x", "y"], "b": ["z"]})
        assert "Skills" in out and "3" in out


class TestStyling:
    def test_active_skin_colours_are_used(self):
        from robo_cli.skin_engine import get_active_skin

        raw = render(colour=True, session_id="s")
        skin = get_active_skin()
        for key in ("banner_border", "banner_title", "banner_text"):
            r, g, b = (int(skin.get_color(key)[i:i + 2], 16) for i in (1, 3, 5))
            assert f"38;2;{r};{g};{b}" in raw, key

    def test_release_tag_makes_the_title_a_hyperlink(self):
        raw = render(colour=True, release=("v3.0.0", "https://example.test/releases/v3.0.0"))
        assert "\x1b]8;" in raw and "https://example.test/releases/v3.0.0" in raw

    def test_no_hyperlink_without_a_release(self):
        assert "\x1b]8;" not in render(colour=True, release=None)

    def test_public_names_are_still_importable_from_banner(self):
        for name in ("build_welcome_banner", "cprint", "_skin_color", "get_available_skills", "format_banner_version_label",
                     "_format_context_length", "_display_toolset_name", "ROBO_AGENT_LOGO", "ROBO_HERO",
                     "check_for_updates", "get_update_result", "prefetch_update_check", "get_latest_release_tag"):
            assert hasattr(banner, name), name
