"""Operators can switch off third-party skill registries; first-party ones stay."""

import pytest

from tools import skills_hub


@pytest.fixture(autouse=True)
def _no_config(monkeypatch):
    monkeypatch.delenv("ROBO_SKILLS_DISABLED_SOURCES", raising=False)
    import robo_cli.config as cfg

    monkeypatch.setattr(cfg, "load_config_readonly", lambda *a, **k: {}, raising=False)


def _ids():
    return [src.source_id() for src in skills_hub.create_source_router()]


def test_everything_on_by_default():
    ids = _ids()
    assert "clawhub" in ids and "lobehub" in ids and "official" in ids


def test_env_var_disables_named_registries(monkeypatch):
    monkeypatch.setenv("ROBO_SKILLS_DISABLED_SOURCES", "ClawHub, lobehub")
    ids = _ids()
    assert "clawhub" not in ids and "lobehub" not in ids
    assert "github" in ids


def test_config_key_disables_named_registries(monkeypatch):
    import robo_cli.config as cfg

    monkeypatch.setattr(
        cfg, "load_config_readonly",
        lambda *a, **k: {"skills": {"disabled_hub_sources": ["clawhub"]}},
        raising=False,
    )
    assert "clawhub" not in _ids()


def test_first_party_sources_cannot_be_disabled(monkeypatch):
    monkeypatch.setenv("ROBO_SKILLS_DISABLED_SOURCES", "official,robo-index,url,not-a-source")
    ids = _ids()
    assert {"official", "robo-index", "url"} <= set(ids)


def test_unreadable_config_never_breaks_the_hub(monkeypatch):
    import robo_cli.config as cfg

    def boom(*a, **k):
        raise RuntimeError("corrupt yaml")

    monkeypatch.setattr(cfg, "load_config_readonly", boom, raising=False)
    assert "clawhub" in _ids()
