"""Regression tests for the Tools & Keys GitHub PAT save/remove path (#40041).

Users following generic docs add ``export GITHUB_TOKEN=ghp_...`` to
``~/.robo/.env``. ``load_env()`` parses the export prefix (#6659), so every
UI shows the token as set (green light) — but ``save_env_value`` /
``remove_env_value`` only matched plain ``KEY=`` lines. Result: the UI could
neither replace nor remove the token (delete 404s as "not found in .env";
save appends a duplicate line that a later delete removes while the export
line silently resurrects the old value).

Fake tokens are constructed at runtime — no key-shaped literals on disk.
"""

import pytest
from fastapi.testclient import TestClient

from robo_cli.web_server import _SESSION_TOKEN, app

client = TestClient(app)
HEADERS = {"X-Robo-Session-Token": _SESSION_TOKEN}

# Classic-PAT-shaped token, constructed at runtime (36 chars after prefix).
OLD_PAT = "ghp_" + "A" * 36
NEW_PAT = "ghp_" + "B" * 36


@pytest.fixture
def robo_home(monkeypatch, tmp_path):
    home = tmp_path / "pat_home"
    home.mkdir()
    monkeypatch.setenv("ROBO_HOME", str(home))
    from robo_cli.config import invalidate_env_cache

    invalidate_env_cache()
    return home


def _write_env_raw(home, text):
    home.joinpath(".env").write_text(text, encoding="utf-8")
    from robo_cli.config import invalidate_env_cache

    invalidate_env_cache()


def test_classic_pat_save_via_endpoint_succeeds(robo_home):
    """Saving a ghp_* classic PAT through the env endpoint must not 500 —
    GITHUB_TOKEN is a REST/Skills-Hub credential, not a Copilot one."""
    resp = client.put(
        "/api/env", json={"key": "GITHUB_TOKEN", "value": NEW_PAT}, headers=HEADERS
    )
    assert resp.status_code == 200, resp.text

    from robo_cli.config import load_env

    assert load_env()["GITHUB_TOKEN"] == NEW_PAT






def test_plain_line_save_and_remove_still_work(robo_home):
    """Sanity: the ordinary KEY= path is unchanged."""
    from robo_cli.config import load_env, remove_env_value, save_env_value

    save_env_value("GITHUB_TOKEN", OLD_PAT)
    assert load_env()["GITHUB_TOKEN"] == OLD_PAT
    save_env_value("GITHUB_TOKEN", NEW_PAT)
    env_text = robo_home.joinpath(".env").read_text(encoding="utf-8")
    assert env_text.count("GITHUB_TOKEN") == 1
    assert remove_env_value("GITHUB_TOKEN") is True
    assert "GITHUB_TOKEN" not in load_env()


