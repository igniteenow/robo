"""Tests for robo_cli.design, the CLI design language. Copyright (c) 2026 Ignitee Now."""

import re

import pytest

from robo_cli import design as ui

ANSI = re.compile(r"\033\[[0-9;]*m")


def plain(text):
    return ANSI.sub("", text)


@pytest.fixture
def colour(monkeypatch):
    monkeypatch.setattr(ui, "should_use_color", lambda: True)
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.delenv("ROBO_ANSI16", raising=False)
    monkeypatch.delenv("ROBO_LIGHT", raising=False)
    monkeypatch.delenv("COLORFGBG", raising=False)


@pytest.fixture
def no_colour(monkeypatch):
    monkeypatch.setattr(ui, "should_use_color", lambda: False)


@pytest.fixture
def cols(monkeypatch):
    def set_width(n):
        monkeypatch.setattr(ui, "width", lambda default=80, maximum=100: n)
    return set_width


class TestContract:
    def test_every_name_the_call_sites_use_still_exists(self):
        for name in ("OK", "WARN", "ERR", "INFO", "STEP", "PROMPT", "BULLET", "RULE", "RULE_HEAVY", "ELLIPSIS", "PRODUCT",
                     "paint", "width", "title", "section", "rule", "kv", "kvs", "ok", "warn", "err", "info", "hint", "bullet",
                     "bullets", "table", "panel", "prompt_line", "choice_rows", "next_steps", "command", "done", "stderr", "_out"):
            assert hasattr(ui, name), name
        assert ui.PRODUCT == "ROBO"

    def test_the_wizard_helpers_route_through_it(self, capsys, no_colour):
        from robo_cli.cli_output import print_error, print_header, print_info, print_success, print_warning

        print_header("Provider"); print_info("i"); print_success("s"); print_warning("w"); print_error("e")
        out = capsys.readouterr().out
        assert ui.STEP + " Provider" in out and ui.OK + " s" in out and ui.WARN + " w" in out and ui.ERR + " e" in out


class TestColourRules:
    def test_no_colour_means_no_escape_codes(self, no_colour, capsys, cols):
        cols(90)
        ui.title("Setup", "sub", version="1.0", hero_art=True); ui.section("A", 1, 3); ui.ok("x"); ui.warn("y"); ui.err("z")
        ui.table(["A"], [["b"]]); ui.panel("P", ["l"]); ui.next_steps(["one"]); print(ui.prompt_line("Q", "d")); print(ui.gradient("ROBO"))
        assert "\033" not in capsys.readouterr().out

    def test_body_text_is_never_coloured(self, colour):
        assert ui.paint("hello", "text") == "hello"
        assert "38;2" not in ui.paint("hello", "strong") and "\033[1m" in ui.paint("hello", "strong")

    def test_dark_terminals_get_ember_and_light_terminals_get_burnt_ember(self, colour, monkeypatch):
        assert "38;2;239;138;34" in ui.paint("x", "accent")
        monkeypatch.setenv("ROBO_LIGHT", "1")
        assert "38;2;181;71;15" in ui.paint("x", "accent")
        monkeypatch.setenv("ROBO_LIGHT", "0")
        monkeypatch.setenv("COLORFGBG", "0;15")
        assert "38;2;239;138;34" in ui.paint("x", "accent"), "an explicit ROBO_LIGHT=0 wins over detection"
        monkeypatch.delenv("ROBO_LIGHT")
        assert "38;2;181;71;15" in ui.paint("x", "accent"), "COLORFGBG with a light background slot"

    def test_sixteen_colour_terminals_fall_back(self, colour, monkeypatch):
        monkeypatch.setenv("ROBO_ANSI16", "1")
        painted = ui.paint("x", "accent")
        assert "38;2" not in painted and painted != "x"
        assert "38;2" not in ui.gradient("ROBO")

    def test_gradient_runs_from_flame_to_ember(self, colour):
        shaded = ui.gradient("ROBO")
        assert plain(shaded) == "ROBO"
        assert shaded.index("38;2;213;39;52") < shaded.index("38;2;239;138;34")
        assert ui.gradient("") == ""

    @pytest.mark.parametrize("role", ["accent", "flame", "label", "indigo", "ok", "warn", "err", "muted", "text", "strong", "nonsense"])
    def test_paint_never_loses_text(self, colour, role):
        assert plain(ui.paint("keep me", role, bold=True, dim=True)) == "keep me"


class TestScreens:
    def test_title_carries_the_mark_product_name_and_version(self, no_colour, capsys, cols):
        cols(80)
        ui.title("Setup", "first run", version="3.0.0")
        out = capsys.readouterr().out
        line = next(l for l in out.splitlines() if "SETUP" in l)
        assert line.startswith(ui.MARK + " ROBO · SETUP ") and line.endswith("3.0.0") and len(line) <= 80
        assert "first run" in out

    def test_hero_draws_the_block_wordmark(self, no_colour, capsys, cols):
        cols(90)
        ui.title("Setup", hero_art=True)
        out = capsys.readouterr().out
        assert out.count("█") > 40 and "by Ignitee Now" in out and "SETUP" in out

    def test_hero_degrades_on_a_narrow_terminal(self, no_colour, capsys, cols):
        cols(36)
        ui.hero()
        out = capsys.readouterr().out
        assert "█" not in out and "ROBO" in out
        assert all(len(l) <= 80 for l in out.splitlines())

    def test_hero_rows_use_the_flame_top_to_bottom(self, colour, capsys, cols):
        cols(90)
        ui.hero()
        out = capsys.readouterr().out
        assert out.index("38;2;245;161;58") < out.index("38;2;213;39;52")

    @pytest.mark.parametrize("step, total, filled", [(0, 6, 0), (1, 6, 3), (3, 6, 8), (6, 6, 16), (9, 6, 16), (1, 100, 1), (-2, 6, 0), (1, 0, 16)])
    def test_progress_track(self, no_colour, step, total, filled):
        track = ui.progress(step, total)
        assert track.count(ui.RULE_HEAVY) == filled
        assert track.count(ui.RULE_HEAVY) + track.count(ui.RULE) == 16

    def test_section_shows_progress_and_fits(self, no_colour, capsys, cols):
        cols(70)
        ui.section("A very long section name " * 5, 2, 6, note="why")
        out = capsys.readouterr().out
        assert "2/6" in out and "why" in out and ui.ELLIPSIS in out
        assert all(len(l) <= 70 for l in out.splitlines())

    def test_section_without_steps_gets_a_rule(self, no_colour, capsys, cols):
        cols(70)
        ui.section("Plain")
        out = capsys.readouterr().out
        assert ui.STEP + " Plain" in out and ui.RULE * 10 in out

    @pytest.mark.parametrize("columns", [40, 60, 100])
    def test_table_never_overflows(self, no_colour, capsys, cols, columns):
        cols(columns)
        ui.table(["Platform", "Status", "Notes"], [["Telegram", "connected", "x" * 300], ["a" * 80, "b" * 80, "c"], ["short"]])
        assert all(len(l) <= columns for l in capsys.readouterr().out.splitlines())

    def test_table_with_no_headers_or_rows_is_harmless(self, no_colour, capsys):
        ui.table([], [["x"]]); ui.table(["A"], []); ui.kvs([])
        assert "A" in capsys.readouterr().out

    def test_panel_is_a_closed_box_that_fits(self, no_colour, capsys, cols):
        cols(50)
        ui.panel("Summary", ["Model  claude", "y" * 200])
        lines = capsys.readouterr().out.splitlines()
        assert lines[0].startswith("┌") and lines[0].endswith("┐") and lines[-1].startswith("└") and lines[-1].endswith("┘")
        assert len({len(l) for l in lines}) == 1 and len(lines[0]) <= 50

    def test_empty_panel(self, no_colour, capsys):
        ui.panel("Empty", [])
        assert "Empty" in capsys.readouterr().out

    def test_prompt_line(self, no_colour):
        assert ui.prompt_line("Name", "robo", hint_text="a-z") == "  › Name [robo]  a-z: "
        assert ui.prompt_line("Name") == "  › Name: "

    def test_choice_rows_mark_exactly_one(self, no_colour):
        rows = ui.choice_rows(["a", "b", "c"], 1)
        assert [r.count(ui.MARK) for r in rows] == [0, 1, 0] and [r.count(ui.MARK_OFF) for r in rows] == [1, 0, 1]
        assert all(str(i + 1) in r for i, r in enumerate(rows))
        assert ui.choice_rows([], 0) == []

    def test_selection_is_clear_without_colour_too(self, colour):
        chosen, other = ui.choice_rows(["a", "b"], 0)
        assert "\033[1m" in chosen and plain(chosen).strip().startswith(ui.MARK)
        assert plain(other).strip().startswith(ui.MARK_OFF)

    def test_next_steps_and_done(self, no_colour, capsys):
        ui.next_steps(["first", "second"]); ui.done("Finished.")
        out = capsys.readouterr().out
        assert "1. first" in out and "2. second" in out and ui.OK + " Finished." in out

    def test_stderr_goes_to_stderr(self, capsys):
        ui.stderr("oops")
        captured = capsys.readouterr()
        assert captured.err.strip() == "oops" and captured.out == ""

    def test_width_is_clamped(self, monkeypatch):
        import os
        import shutil

        monkeypatch.setattr(shutil, "get_terminal_size", lambda fallback=(80, 24): os.terminal_size((500, 24)))
        assert ui.width() == 100
        monkeypatch.setattr(shutil, "get_terminal_size", lambda fallback=(80, 24): os.terminal_size((10, 24)))
        assert ui.width() == 40
