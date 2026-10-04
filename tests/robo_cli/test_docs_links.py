"""Every link to Robo's documentation is a real web address.

There is no documentation website. The guides are rendered by GitHub, so a
"Setup guide" button, a ``Docs:`` line in the terminal or a settings hint
must point there. Before this, most of them printed a repository path
(``website/docs/...``): the desktop silently ignored it, the dashboard opened
a second copy of itself, and the terminal showed a path that exists nowhere
on an installed machine.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from robo_cli.docs_links import DOCS_HOME_URL, docs_url

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "website" / "docs"
GH_BLOB = "https://github.com/igniteenow/robo/blob/main/website/docs"
GH_TREE = "https://github.com/igniteenow/robo/tree/main/website/docs"


# ---------------------------------------------------------------------------
# docs_url
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path, expected",
    [
        ("user-guide/messaging/whatsapp.md", f"{GH_BLOB}/user-guide/messaging/whatsapp.md"),
        ("/user-guide/messaging/whatsapp.md", f"{GH_BLOB}/user-guide/messaging/whatsapp.md"),
        ("website/docs/user-guide/features/hooks.md", f"{GH_BLOB}/user-guide/features/hooks.md"),
        (
            "user-guide/messaging/webhooks.md#configuring-routes",
            f"{GH_BLOB}/user-guide/messaging/webhooks.md#configuring-routes",
        ),
        ("", GH_TREE),
        ("developer-guide", f"{GH_TREE}/developer-guide"),
        ("user-guide/secrets/", f"{GH_TREE}/user-guide/secrets"),
    ],
)
def test_docs_url_builds_the_github_page(path, expected):
    assert docs_url(path) == expected


def test_docs_home_is_the_docs_folder_on_github():
    assert DOCS_HOME_URL == GH_TREE
    assert docs_url() == DOCS_HOME_URL


# ---------------------------------------------------------------------------
# Every docs link the product hands out points at a page that exists
# ---------------------------------------------------------------------------

def _docs_links_in(text: str) -> list[str]:
    links = re.findall(r"https://github\.com/igniteenow/robo/(?:blob|tree)/main/website/docs[^\s`'\")\]>]*", text)
    # A sentence may end right after a link.
    return [link.rstrip(".,;:") for link in links]


def _page_exists(url: str) -> bool:
    rel = url.split("/website/docs", 1)[1].lstrip("/").split("#", 1)[0]
    return (DOCS_ROOT / rel).exists() if rel else DOCS_ROOT.is_dir()


def test_every_messaging_card_links_to_a_real_robo_guide():
    from robo_cli.web_server import _PLATFORM_OVERRIDES, _build_catalog_entry

    for platform_id in _PLATFORM_OVERRIDES:
        url = _build_catalog_entry(platform_id)["docs_url"]
        assert url.startswith(GH_BLOB + "/"), f"{platform_id}: {url!r}"
        assert _page_exists(url), f"{platform_id}: no such guide {url}"
        # The old links pointed at other people's projects.
        assert "whatsmeow" not in url and "bbernhard" not in url


def test_whatsapp_card_opens_robo_whatsapp_guide():
    from robo_cli.web_server import _build_catalog_entry

    assert _build_catalog_entry("whatsapp")["docs_url"] == f"{GH_BLOB}/user-guide/messaging/whatsapp.md"


def test_every_platform_in_the_catalog_has_a_display_position():
    from robo_cli.web_server import _PLATFORM_ORDER, _PLATFORM_OVERRIDES

    assert set(_PLATFORM_OVERRIDES) <= set(_PLATFORM_ORDER)


def test_oauth_cards_never_hand_out_a_repository_path():
    from robo_cli.web_server import _OAUTH_PROVIDER_CATALOG

    for entry in _OAUTH_PROVIDER_CATALOG:
        url = entry["docs_url"]
        assert url.startswith("https://"), f"{entry['id']}: {url!r}"
        if url.startswith(GH_BLOB):
            assert _page_exists(url), f"{entry['id']}: no such guide {url}"


def test_signal_field_hint_names_the_daemon_robo_talks_to():
    from robo_cli.web_server import _MESSAGING_ENV_FALLBACKS

    hint = _MESSAGING_ENV_FALLBACKS["SIGNAL_HTTP_URL"]
    assert hint["url"] == f"{GH_BLOB}/user-guide/messaging/signal.md"
    assert "daemon" in hint["description"]


@pytest.mark.parametrize(
    "command",
    [["fallback", "--help"], ["secrets", "--help"], ["egress", "--help"], ["kanban", "--help"]],
)
def test_help_text_links_to_github_not_a_repo_path(command, tmp_path):
    import os
    import sys

    # A real subprocess, so argparse's own wrapping is exercised. Keep the
    # system environment (Windows needs SYSTEMROOT and friends) but point every
    # home at a scratch directory so no user config can change the help text.
    env = {k: v for k, v in os.environ.items() if not k.startswith("ROBO_")}
    env.update({
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "ROBO_HOME": str(tmp_path / ".robo"),
        "COLUMNS": "100",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    })
    out = subprocess.run(
        [sys.executable, "-m", "robo_cli.main", *command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, cwd=str(REPO_ROOT), env=env,
    ).stdout
    assert "website/docs/" not in out.replace(GH_BLOB, "")
    links = _docs_links_in(out)
    assert links, out[-400:]
    for url in links:
        assert _page_exists(url), url


def test_source_no_longer_prints_repo_paths_as_links():
    """A ``website/docs/...`` string inside a print(), an f-string shown to the
    user or a ``docs_url`` value is a link nobody can follow."""
    offenders = []
    pattern = re.compile(r"""(print[^\n]*|docs_url[^\n]*|_DOCS_URL[^\n]*)website/docs/""")
    for path in list((REPO_ROOT / "robo_cli").glob("*.py")) + [
        REPO_ROOT / "tools" / "mcp_oauth.py",
        REPO_ROOT / "plugins" / "platforms" / "slack" / "adapter.py",
        REPO_ROOT / "plugins" / "platforms" / "google_chat" / "adapter.py",
    ]:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if pattern.search(line) and "github.com/igniteenow" not in line:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_agent_is_told_where_the_documentation_really_is():
    from agent import prompt_builder

    text = Path(prompt_builder.__file__).read_text(encoding="utf-8")
    assert "the documentation at website/docs/index.mdx" not in text
    assert GH_TREE in text


def test_bundled_skills_link_to_github_pages_that_exist():
    skill_root = REPO_ROOT / "skills" / "autonomous-ai-agents" / "robo-engineer"
    offenders = []
    for path in [skill_root / "SKILL.md", *(skill_root / "references").glob("*.md")]:
        text = path.read_text(encoding="utf-8")
        links = _docs_links_in(text)
        bare = text
        for url in links:
            bare = bare.replace(url, "")
        if "website/docs" in bare:
            offenders.append(f"{path.relative_to(REPO_ROOT)}: still cites a repository path")
        for url in links:
            if not _page_exists(url):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {url}")
    assert not offenders, "\n".join(offenders)
