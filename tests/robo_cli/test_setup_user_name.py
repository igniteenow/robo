"""`robo setup name` — what Robo calls the person (display.user_name)."""

import robo_cli.setup as wizard
from robo_cli.config_defaults import DEFAULT_CONFIG
from robo_cli.setup import SETUP_SECTIONS, normalize_user_name, setup_user_name


def _answers(monkeypatch, *answers):
    it = iter(answers)
    asked = []

    def fake_prompt(question, default=None, **kwargs):
        asked.append((question, default))
        return next(it)

    monkeypatch.setattr(wizard, "prompt", fake_prompt)
    return asked


def test_default_is_empty_and_the_section_is_registered():
    assert DEFAULT_CONFIG["display"]["user_name"] == ""
    assert [key for key, _, _ in SETUP_SECTIONS][0] == "name"


def test_normalize_trims_collapses_and_bounds():
    assert normalize_user_name("  Ahmi   Khan ") == "Ahmi Khan"
    assert normalize_user_name(None) == ""
    assert normalize_user_name(42) == "42"
    assert len(normalize_user_name("x" * 100)) == wizard.USER_NAME_MAX_CHARS


def test_sets_the_name_in_display(monkeypatch, capsys):
    asked = _answers(monkeypatch, "Ahmi")
    config = {}

    setup_user_name(config)

    assert config["display"]["user_name"] == "Ahmi"
    assert asked[0][1] is None  # no current name: no default shown
    assert "$Ahmi" in capsys.readouterr().out


def test_enter_keeps_the_current_name(monkeypatch):
    # prompt() returns the default when the person just presses Enter.
    asked = _answers(monkeypatch, "Ahmi Khan")
    config = {"display": {"user_name": "Ahmi Khan", "skin": "robo"}}

    setup_user_name(config)

    assert asked[0][1] == "Ahmi Khan"
    assert config["display"] == {"user_name": "Ahmi Khan", "skin": "robo"}


def test_dash_clears_the_name(monkeypatch):
    _answers(monkeypatch, "-")
    config = {"display": {"user_name": "Ahmi"}}

    setup_user_name(config)

    assert config["display"]["user_name"] == ""


def test_a_broken_display_section_is_replaced(monkeypatch):
    _answers(monkeypatch, "Ahmi")
    config = {"display": "oops"}

    setup_user_name(config)

    assert config["display"] == {"user_name": "Ahmi"}
