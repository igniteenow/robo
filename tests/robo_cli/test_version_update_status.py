"""`robo version` reports whether an update is available.

The update check returns a commit count, 0 when current, -1 when behind by an
amount a shallow clone can't count (what the install scripts produce), and
None when it couldn't check. Only the last one may stay silent.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from robo_cli import main as cli_main


@pytest.mark.parametrize(
    ("behind", "expected", "absent"),
    [
        (3, "Update available: 3 commits behind", None),
        (1, "Update available: 1 commit behind", None),
        (-1, "Update available — run", "commits behind"),
        (0, "Up to date", "Update available"),
    ],
)
def test_version_reports_update_status(behind, expected, absent, capsys):
    with patch("robo_cli.slash_exec.execute_command", return_value=SimpleNamespace(text="Robo v0")), patch(
        "robo_cli.banner.check_for_updates", return_value=behind
    ):
        cli_main._print_version_info()

    out = capsys.readouterr().out
    assert expected in out
    if absent:
        assert absent not in out


def test_version_stays_quiet_when_the_check_failed(capsys):
    with patch("robo_cli.slash_exec.execute_command", return_value=SimpleNamespace(text="Robo v0")), patch(
        "robo_cli.banner.check_for_updates", return_value=None
    ):
        cli_main._print_version_info()

    out = capsys.readouterr().out
    assert "Update available" not in out
    assert "Up to date" not in out
