"""Tests for robo_cli.skin_engine. Copyright (c) 2026 Ignitee Now."""

import pytest
import yaml


@pytest.fixture(autouse=True)
def reset_skin_state():
    from robo_cli import skin_engine

    skin_engine._active_skin = None
    skin_engine._active_skin_name = "default"
    yield
    skin_engine._active_skin = None
    skin_engine._active_skin_name = "default"


def _user_dir(tmp_path, monkeypatch, files):
    skins_dir = tmp_path / "skins"
    skins_dir.mkdir()
    for filename, content in files.items():
        text = content if isinstance(content, str) else yaml.dump(content)
        (skins_dir / filename).write_text(text, encoding="utf-8")
    monkeypatch.setattr("robo_cli.skin_engine._skins_dir", lambda: skins_dir)
    return skins_dir


class TestSkinConfig:
    def test_brand_skin_has_required_fields(self):
        from robo_cli.skin_engine import REQUIRED_COLOR_KEYS, load_skin

        skin = load_skin("robo")
        assert skin.name == "robo"
        assert skin.tool_prefix == "│"
        assert not [k for k in REQUIRED_COLOR_KEYS if not skin.get_color(k)]
        assert skin.get_branding("agent_name") == "Robo"
        assert skin.get_branding("prompt_symbol")

    def test_get_color_and_branding_fall_back(self):
        from robo_cli.skin_engine import load_skin

        skin = load_skin("robo")
        assert skin.get_color("no_such_key", "#123456") == "#123456"
        assert skin.get_color("no_such_key") == ""
        assert skin.get_branding("no_such_key", "x") == "x"

    def test_spinner_wings_empty_for_brand_skin(self):
        from robo_cli.skin_engine import load_skin

        assert load_skin("robo").get_spinner_wings() == []

    def test_spinner_wings_are_pairs_and_skip_garbage(self):
        from robo_cli.skin_engine import SkinConfig, load_skin

        wings = load_skin("ember").get_spinner_wings()
        assert wings and all(isinstance(w, tuple) and len(w) == 2 for w in wings)
        odd = SkinConfig(spinner={"wings": [["a", "b"], "nope", ["only-one"], None, ("c", "d")]})
        assert odd.get_spinner_wings() == [("a", "b"), ("c", "d")]
        assert SkinConfig(spinner={"wings": "nope"}).get_spinner_wings() == []


class TestBuiltinSkins:
    def test_only_ignitee_now_skins_ship(self):
        from robo_cli.skin_engine import list_skins

        builtin = {s["name"] for s in list_skins() if s["source"] == "builtin"}
        assert builtin == {"robo", "ember", "midnight", "paper", "contrast"}

    @pytest.mark.parametrize("name", ["robo", "ember", "midnight", "paper", "contrast"])
    def test_every_builtin_loads_complete(self, name):
        from robo_cli.skin_engine import REQUIRED_COLOR_KEYS, load_skin

        skin = load_skin(name)
        assert skin.name == name
        assert skin.description
        for key in REQUIRED_COLOR_KEYS:
            value = skin.get_color(key)
            assert value.startswith("#") and len(value) == 7, f"{name}.{key} = {value!r}"
        assert skin.get_branding("agent_name") == "Robo"  # a skin restyles Robo; it does not rename it

    @pytest.mark.parametrize("gone", ["ares", "mono", "slate", "daylight", "warm-lightmode", "poseidon", "sisyphus", "charizard"])
    def test_inherited_skins_are_gone_and_fall_back_safely(self, gone):
        from robo_cli.skin_engine import list_skins, load_skin

        assert gone not in {s["name"] for s in list_skins()}
        assert load_skin(gone).name == "robo"  # an old config value must not crash start-up

    def test_brand_skin_gets_its_banner_art_from_the_shipped_yaml(self):
        from robo_cli.skin_engine import load_skin

        skin = load_skin("robo")
        assert "██" in skin.banner_logo
        assert skin.tool_emojis  # from the YAML, merged over the Python definition

    def test_shipped_yaml_does_not_own_colours(self):
        """Colours have one source of truth (the engine), so the contrast audit
        cannot be bypassed by editing the resource file."""
        from pathlib import Path

        import robo_runtime

        data = yaml.safe_load((Path(robo_runtime.__file__).parent / "resources/skins/robo.yaml").read_text(encoding="utf-8"))
        assert "colors" not in data and "light_colors" not in data


class TestAliasesAndFallbacks:
    @pytest.mark.parametrize("name", ["default", "DEFAULT", "", None, "  robo  "])
    def test_default_and_blank_mean_the_brand_skin(self, name):
        from robo_cli.skin_engine import load_skin

        assert load_skin(name).name == "robo"

    @pytest.mark.parametrize("name", ["../../etc/passwd", "a/b", "..", "x" * 200, "na me", "\x00"])
    def test_names_that_could_escape_the_skins_folder_are_refused(self, name, tmp_path, monkeypatch):
        from robo_cli.skin_engine import load_skin

        outside = tmp_path / "evil.yaml"
        outside.write_text(yaml.dump({"name": "evil", "branding": {"agent_name": "Evil"}}), encoding="utf-8")
        _user_dir(tmp_path, monkeypatch, {})
        skin = load_skin(name)
        assert skin.name == "robo" and skin.get_branding("agent_name") == "Robo"


class TestSkinManagement:
    def test_set_active_skin(self):
        from robo_cli.skin_engine import get_active_skin, get_active_skin_name, set_active_skin

        skin = set_active_skin("ember")
        assert skin.name == "ember"
        assert get_active_skin_name() == "ember"
        assert get_active_skin().name == "ember"

    def test_active_skin_loads_lazily_and_alias_resolves(self):
        from robo_cli.skin_engine import get_active_skin

        assert get_active_skin().name == "robo"  # the fixture left the name as "default"

    def test_setting_an_unknown_skin_activates_the_brand_skin(self):
        from robo_cli.skin_engine import get_active_skin_name, set_active_skin

        assert set_active_skin("does-not-exist").name == "robo"
        assert get_active_skin_name() == "robo"

    @pytest.mark.parametrize(
        "config, expected",
        [({"display": {"skin": "midnight"}}, "midnight"), ({"display": {"skin": "default"}}, "robo"),
         ({"display": {}}, "robo"), ({}, "robo"), ({"display": None}, "robo"), ({"display": "x"}, "robo"),
         (None, "robo"), ({"display": {"skin": 42}}, "robo")],
    )
    def test_init_from_config_tolerates_any_shape(self, config, expected):
        from robo_cli.skin_engine import get_active_skin_name, init_skin_from_config

        init_skin_from_config(config)
        assert get_active_skin_name() == expected

    def test_list_skins_shape(self):
        from robo_cli.skin_engine import list_skins

        skins = list_skins()
        assert skins and all(set(s) == {"name", "description", "source"} for s in skins)
        assert "default" not in {s["name"] for s in skins}  # an alias, not a skin


class TestUserSkins:
    def test_load_user_skin_from_yaml(self, tmp_path, monkeypatch):
        from robo_cli.skin_engine import load_skin

        _user_dir(tmp_path, monkeypatch, {"custom.yaml": {
            "name": "custom", "description": "A custom test skin",
            "colors": {"banner_title": "#FF0000"}, "branding": {"agent_name": "Custom Agent"}, "tool_prefix": "▸",
        }})
        skin, brand = load_skin("custom"), load_skin("robo")
        assert skin.name == "custom"
        assert skin.get_color("banner_title") == "#FF0000"
        assert skin.get_branding("agent_name") == "Custom Agent"
        assert skin.tool_prefix == "▸"
        assert skin.get_color("banner_border") == brand.get_color("banner_border")  # inherited
        assert skin.get_branding("goodbye") == brand.get_branding("goodbye")  # inherited

    def test_user_skin_does_not_inherit_another_palettes_overlay_or_art(self, tmp_path, monkeypatch):
        from robo_cli.skin_engine import load_skin

        _user_dir(tmp_path, monkeypatch, {"plain.yml": {"name": "plain", "colors": {"banner_title": "#00FF00"}}})
        skin = load_skin("plain")
        assert skin.light_colors == {} and skin.dark_colors == {}
        assert skin.banner_logo == "" and skin.tool_emojis == {}

    def test_invalid_section_types_fall_back_to_defaults(self, tmp_path, monkeypatch):
        from robo_cli.skin_engine import load_skin

        _user_dir(tmp_path, monkeypatch, {"broken.yaml": {
            "name": "broken", "colors": ["not", "a", "mapping"], "spinner": "invalid",
            "branding": ["also", "invalid"], "tool_emojis": ["invalid"], "tool_prefix": "!",
            "banner_logo": ["not", "text"],
        }})
        skin, brand = load_skin("broken"), load_skin("robo")
        assert skin.name == "broken"
        assert skin.colors == brand.colors
        assert skin.get_branding("agent_name") == "Robo"
        assert skin.spinner == brand.spinner
        assert skin.tool_emojis == {}
        assert skin.banner_logo == ""
        assert skin.tool_prefix == "!"

    @pytest.mark.parametrize("content", ["::: not yaml :::\n\t- [", "- just\n- a list\n", "", "42"])
    def test_unreadable_skin_files_never_raise(self, content, tmp_path, monkeypatch):
        from robo_cli.skin_engine import list_skins, load_skin

        _user_dir(tmp_path, monkeypatch, {"bad.yaml": content})
        assert load_skin("bad").name == "robo"
        assert "bad" not in {s["name"] for s in list_skins()}

    def test_non_string_colour_values_are_ignored(self, tmp_path, monkeypatch):
        from robo_cli.skin_engine import load_skin

        _user_dir(tmp_path, monkeypatch, {"odd.yaml": {"name": "odd", "colors": {"banner_title": 123, "ui_ok": None, "ui_warn": "#ABCDEF"}}})
        skin, brand = load_skin("odd"), load_skin("robo")
        assert skin.get_color("banner_title") == brand.get_color("banner_title")
        assert skin.get_color("ui_warn") == "#ABCDEF"

    def test_list_skins_includes_user_skins(self, tmp_path, monkeypatch):
        from robo_cli.skin_engine import list_skins

        _user_dir(tmp_path, monkeypatch, {"pirate.yaml": {"name": "pirate", "description": "Arr matey"}})
        pirate = [s for s in list_skins() if s["name"] == "pirate"]
        assert pirate and pirate[0]["source"] == "user" and pirate[0]["description"] == "Arr matey"

    def test_user_skin_shadows_a_builtin_and_is_listed_once(self, tmp_path, monkeypatch):
        from robo_cli.skin_engine import list_skins, load_skin

        _user_dir(tmp_path, monkeypatch, {"ember.yaml": {"name": "ember", "branding": {"goodbye": "Mine."}}})
        assert load_skin("ember").get_branding("goodbye") == "Mine."
        entries = [s for s in list_skins() if s["name"] == "ember"]
        assert len(entries) == 1 and entries[0]["source"] == "user"


class TestDisplayIntegration:
    def test_tool_message_uses_skin_prefix(self):
        from agent.display import get_cute_tool_message
        from robo_cli.skin_engine import set_active_skin

        set_active_skin("ember")
        msg = get_cute_tool_message("terminal", {"command": "ls"}, 0.5)
        assert msg.startswith("▸")
        assert "┊" not in msg


class TestCliBrandingHelpers:
    def test_helpers_read_the_active_skin(self):
        from robo_cli.skin_engine import get_active_goodbye, get_active_help_header, get_active_prompt_symbol, set_active_skin

        set_active_skin("ember")
        assert get_active_goodbye() == "Embers banked. Robo standing by."
        assert get_active_prompt_symbol() == "▲"
        assert get_active_help_header() == "ROBO COMMAND DECK"

    def test_prompt_toolkit_style_overrides_cover_tui_classes(self):
        from robo_cli.skin_engine import get_prompt_toolkit_style_overrides, set_active_skin

        set_active_skin("ember")
        required = {
            "input-area", "placeholder", "prompt", "prompt-working", "hint", "input-rule", "image-badge",
            "status-bar", "status-bar-strong", "status-bar-dim", "status-bar-good", "status-bar-warn",
            "status-bar-bad", "status-bar-critical",
            "completion-menu", "completion-menu.completion", "completion-menu.completion.current",
            "completion-menu.meta.completion", "completion-menu.meta.completion.current",
            "voice-status", "voice-status-recording",
            "clarify-border", "clarify-title", "clarify-question", "clarify-choice", "clarify-selected",
            "clarify-active-other", "clarify-countdown",
            "sudo-prompt", "sudo-border", "sudo-title", "sudo-text",
            "approval-border", "approval-title", "approval-desc", "approval-cmd", "approval-choice", "approval-selected",
        }
        overrides = get_prompt_toolkit_style_overrides()
        assert required <= set(overrides)
        assert all(isinstance(v, str) and v for v in overrides.values())

    @pytest.mark.parametrize("name", ["robo", "ember", "midnight", "paper", "contrast"])
    def test_prompt_toolkit_style_overrides_use_skin_colors(self, name):
        from robo_cli.skin_engine import get_active_skin, get_prompt_toolkit_style_overrides, set_active_skin

        set_active_skin(name)
        skin, o = get_active_skin(), get_prompt_toolkit_style_overrides()
        bar = skin.get_color("status_bar_bg")
        assert o["prompt"] == skin.get_color("prompt")
        assert o["input-rule"] == skin.get_color("input_rule")
        assert o["prompt-working"] == f"{skin.get_color('banner_dim')} italic"
        assert o["status-bar"] == f"bg:{bar} {skin.get_color('status_bar_text')}"
        assert o["status-bar-strong"] == f"bg:{bar} {skin.get_color('status_bar_strong')} bold"
        assert o["status-bar-critical"] == f"bg:{bar} {skin.get_color('status_bar_critical')} bold"
        assert o["clarify-title"] == f"{skin.get_color('banner_title')} bold"
        assert o["sudo-prompt"] == f"{skin.get_color('ui_error')} bold"
        assert o["approval-title"] == f"{skin.get_color('ui_warn')} bold"
        assert o["voice-status"] == f"bg:{skin.get_color('voice_status_bg')} {skin.get_color('ui_label')}"

    def test_status_bar_text_falls_back_to_banner_text(self, tmp_path, monkeypatch):
        from robo_cli import skin_engine

        skin = skin_engine.load_skin("robo")
        skin.colors.pop("status_bar_text")
        monkeypatch.setattr(skin_engine, "_active_skin", skin)
        o = skin_engine.get_prompt_toolkit_style_overrides()
        assert o["status-bar"] == f"bg:{skin.get_color('status_bar_bg')} {skin.get_color('banner_text')}"
