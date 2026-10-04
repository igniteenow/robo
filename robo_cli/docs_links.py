"""Links to Robo's documentation.

The guides live in the repository under ``website/docs/``. Nothing serves
them as a website, so every link handed to a person (a "Setup guide" button,
a ``Docs:`` line in the terminal, a settings hint) points at the page on
GitHub, where the markdown renders. One place decides the address so that
no surface prints a repository path as if it were a link.
"""

from __future__ import annotations

__all__ = ["DOCS_HOME_URL", "docs_url"]

_REPO = "https://github.com/igniteenow/robo"
_DOCS_DIR = "website/docs"

#: The documentation folder, rendered by GitHub.
DOCS_HOME_URL = f"{_REPO}/tree/main/{_DOCS_DIR}"


def docs_url(path: str = "") -> str:
    """The page for ``path``, a file under ``website/docs`` such as
    ``user-guide/messaging/whatsapp.md`` (a ``#fragment`` is kept).

    An empty path, or a folder, gives the folder listing.
    """
    page = path.strip().lstrip("/")
    if page.startswith(f"{_DOCS_DIR}/"):
        page = page[len(_DOCS_DIR) + 1:]
    if not page:
        return DOCS_HOME_URL
    base, _, fragment = page.partition("#")
    if base.endswith("/") or "." not in base.rsplit("/", 1)[-1]:
        url = f"{_REPO}/tree/main/{_DOCS_DIR}/{base.rstrip('/')}"
    else:
        url = f"{_REPO}/blob/main/{_DOCS_DIR}/{base}"
    return f"{url}#{fragment}" if fragment else url
