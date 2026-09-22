"""Tests for robo_cli.tips. Copyright (c) 2026 Ignitee Now.

Beyond shape and randomness, these check that every tip is *true*: any command,
subcommand, skin or setting a tip names must really exist. A tip that survives a
rename or removal is a bug, and this suite turns it into a failing build.
"""

import re
from pathlib import Path

import pytest

from robo_cli import tips as tips_module
from robo_cli.tips import CURATED, MAX_TIP_LENGTH, TIPS, get_random_tip

ROOT = Path(__file__).resolve().parents[2]
URL = re.compile(r"https?://\S+")


def _commands():
    from robo_cli.commands import COMMAND_REGISTRY

    names = set()
    for command in COMMAND_REGISTRY:
        names.add(command.name)
        names.update(command.aliases or ())
    return names


def _subcommands():
    # Independent of the module under test: names only, from the argparse sources.
    found = set()
    for path in [*(ROOT / "robo_cli" / "subcommands").glob("*.py"), ROOT / "robo_cli" / "main.py"]:
        found.update(re.findall(r"\bsubparsers\.add_parser\(\s*[\"']([a-z][a-z0-9-]*)[\"']", path.read_text(encoding="utf-8")))
    # Plugins add their own `robo <name>` commands through register_cli_command().
    for path in (ROOT / "plugins").rglob("*.py"):
        found.update(re.findall(r"register_cli_command\(\s*name\s*=\s*[\"']([a-z][a-z0-9-]*)[\"']", path.read_text(encoding="utf-8", errors="ignore")))
    return found


class TestCorpus:
    def test_has_at_least_200_tips(self):
        assert len(TIPS) >= 200, f"Expected 200+ tips, got {len(TIPS)}"

    def test_all_four_sources_contribute(self):
        assert len(CURATED) >= 30
        assert sum(t.startswith("/") for t in TIPS) >= 60, "slash-command tips missing"
        assert sum(t.startswith("robo ") for t in TIPS) >= 30, "subcommand tips missing"
        assert sum(" in your .env: " in t for t in TIPS) >= 30, "setting tips missing"

    def test_every_tip_is_one_clean_line(self):
        for tip in TIPS:
            assert isinstance(tip, str) and tip == tip.strip() and tip
            assert "\n" not in tip and "  " not in tip, tip
            assert len(tip) <= MAX_TIP_LENGTH, f"{len(tip)} chars: {tip}"

    def test_no_tip_can_break_rich_markup(self):
        """Tips are printed inside ``[dim …]…[/]``; a bracket would be read as a tag."""
        for tip in TIPS:
            assert "[" not in tip and "]" not in tip, tip

    def test_no_duplicates(self):
        assert len(TIPS) == len(set(TIPS))

    def test_tips_do_not_name_other_projects(self):
        blob = " ".join(CURATED).lower()
        for word in ("nous", "openclaw", "clawdbot"):
            assert word not in blob
        # "Hermes" may appear only as the name of the model family Robo can use.
        assert all("hermes chat models" in t.lower() for t in CURATED if "hermes" in t.lower())


class TestTipsAreTrue:
    def test_every_slash_command_mentioned_exists(self):
        known = _commands()
        for tip in TIPS:
            for name in re.findall(r"(?<![\w/.:-])/([a-z][a-z0-9_-]*)", URL.sub("", tip)):
                assert name in known, f"unknown command /{name} in tip: {tip}"

    def test_every_robo_subcommand_mentioned_exists(self):
        known = _subcommands()
        for tip in TIPS:
            for name in re.findall(r"\brobo ([a-z][a-z0-9-]*)", tip):
                if name == "skin":  # "the robo skin" is prose; `robo skin` is also a real subcommand
                    continue
                assert name in known, f"unknown subcommand 'robo {name}' in tip: {tip}"

    def test_every_skin_mentioned_exists(self):
        from robo_cli.skin_engine import load_skin

        for tip in TIPS:
            for name in re.findall(r"/skin ([a-z][a-z-]*)", tip):
                if name in {"next", "list"}:
                    continue
                assert load_skin(name).name == name, f"unknown skin {name!r} in tip: {tip}"
        listed = re.search(r"ships five skins: ([a-z, ]+) and ([a-z]+)\.", " ".join(CURATED))
        assert listed, "the skin-list tip changed shape; update this test"
        from robo_cli.skin_engine import list_skins

        named = {n.strip() for n in listed.group(1).split(",")} | {listed.group(2)}
        assert named == {s["name"] for s in list_skins() if s["source"] == "builtin"}

    def test_every_setting_mentioned_exists(self):
        from robo_cli.config_defaults import OPTIONAL_ENV_VARS

        for tip in TIPS:
            match = re.match(r"([A-Z][A-Z0-9_]+) in your \.env: ", tip)
            if match:
                assert match.group(1) in OPTIONAL_ENV_VARS, tip

    def test_documented_switches_are_real(self):
        """Curated tips name a few switches by hand; make sure the code reads them."""
        for needle, rel in [
            ("ROBO_NO_UPDATE_CHECK", "robo_cli/banner.py"),
            ("ROBO_SKILLS_DISABLED_SOURCES", "tools/skills_hub.py"),
            ("disabled_hub_sources", "tools/skills_hub.py"),
            ("--dry-run", "robo_cli/agent_import.py"),
            ('"html"', "robo_cli/main.py"),
        ]:
            assert any(needle.strip('"') in t for t in CURATED) or needle == '"html"', needle
            assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{needle} not found in {rel}"

    def test_generated_tips_follow_the_registry(self, monkeypatch):
        """Remove a command from the registry and its tip goes with it."""
        import robo_cli.commands as commands

        victim = next(c for c in commands.COMMAND_REGISTRY if c.name == "wake")
        monkeypatch.setattr(commands, "COMMAND_REGISTRY", [c for c in commands.COMMAND_REGISTRY if c is not victim])
        rebuilt = tips_module._build()
        assert not any(t.startswith("/wake:") for t in rebuilt)
        assert any(t.startswith("/wake:") for t in TIPS)

    def test_a_broken_registry_never_breaks_startup(self, monkeypatch):
        monkeypatch.setattr(tips_module, "_command_tips", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        rebuilt = tips_module._build()
        assert len(rebuilt) >= len(CURATED)


class TestGetRandomTip:
    def test_returns_tip_from_corpus(self):
        tip = get_random_tip()
        assert isinstance(tip, str) and tip in TIPS

    def test_randomness(self):
        assert len({get_random_tip() for _ in range(50)}) >= 10

    def test_exclude_recent_avoids_repeats(self):
        tips_module._recent.clear()
        drawn = [get_random_tip(exclude_recent=20) for _ in range(60)]
        for index in range(1, len(drawn)):
            assert drawn[index] not in drawn[max(0, index - 20):index]

    def test_exclude_recent_larger_than_corpus_still_returns(self, monkeypatch):
        monkeypatch.setattr(tips_module, "TIPS", ["only one"])
        tips_module._recent.clear()
        assert get_random_tip(exclude_recent=5) == "only one"
        assert get_random_tip(exclude_recent=5) == "only one"

    def test_empty_corpus_has_a_fallback(self, monkeypatch):
        monkeypatch.setattr(tips_module, "TIPS", [])
        assert "/help" in get_random_tip()


class TestTipIntegration:
    @pytest.mark.parametrize("colour", ["#8C91BD", "#5C6088"])
    def test_tip_display_format(self, colour):
        """The exact markup cli.py builds must contain one closing tag, whatever the tip."""
        for tip in TIPS:
            markup = f"[dim {colour}]✦ Tip: {tip}[/]"
            assert markup.count("[/]") == 1 and markup.count("[") == 2
