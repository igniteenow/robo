"""The classic CLI's "N updates behind" notice when the update check answers late.

The banner only includes the notice if the check answered within half a second
of start-up. A check that has to reach the network usually takes longer, and
the compact banner has no room for it, so the CLI prints it once it arrives.
"""

import threading
import time

import pytest

import cli as cli_mod


class _Printed:
    def __init__(self):
        self.lines = []

    def console(self):
        printed = self

        class _Console:
            def print(self, markup):
                printed.lines.append(markup)

        return _Console()


@pytest.fixture
def printed(monkeypatch):
    out = _Printed()
    monkeypatch.setattr(cli_mod, "ChatConsole", out.console)
    monkeypatch.setattr("robo_cli.config.recommended_update_command", lambda: "robo update")
    return out


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_the_notice_follows_when_the_answer_arrives_after_the_banner(printed, monkeypatch):
    answered = threading.Event()

    def get_update_result(timeout=0.5):
        if not answered.wait(timeout):
            return None
        return 3

    monkeypatch.setattr("robo_cli.banner.get_update_result", get_update_result)

    cli_mod._show_update_notice_when_known(already_shown=False, wait=5)
    assert printed.lines == []  # nothing yet: the check is still out

    answered.set()

    assert _wait_for(lambda: printed.lines)
    assert "3 updates behind" in printed.lines[0]
    assert "robo update" in printed.lines[0]


def test_an_answer_that_is_already_in_prints_right_away(printed, monkeypatch):
    """The compact banner has no update line, so the notice goes under it."""
    monkeypatch.setattr("robo_cli.banner.get_update_result", lambda timeout=0.5: 2)

    cli_mod._show_update_notice_when_known(already_shown=False)

    assert len(printed.lines) == 1
    assert "2 updates behind" in printed.lines[0]


def test_nothing_is_repeated_when_the_banner_already_said_it(printed, monkeypatch):
    monkeypatch.setattr("robo_cli.banner.get_update_result", lambda timeout=0.5: 2)

    cli_mod._show_update_notice_when_known(already_shown=True)

    assert printed.lines == []


@pytest.mark.parametrize("result", [0, None])
def test_nothing_is_said_when_up_to_date_or_unknown(printed, monkeypatch, result):
    monkeypatch.setattr("robo_cli.banner.get_update_result", lambda timeout=0.5: result)

    cli_mod._show_update_notice_when_known(already_shown=False, wait=0.2)
    time.sleep(0.4)

    assert printed.lines == []


def test_a_redrawn_banner_does_not_print_the_notice_twice(printed, monkeypatch):
    """/clear redraws the banner while the first check may still be out."""
    answered = threading.Event()

    def get_update_result(timeout=0.5):
        if not answered.wait(timeout):
            return None
        return 1

    monkeypatch.setattr("robo_cli.banner.get_update_result", get_update_result)

    cli_mod._show_update_notice_when_known(already_shown=False, wait=5)
    cli_mod._show_update_notice_when_known(already_shown=False, wait=5)
    answered.set()

    assert _wait_for(lambda: printed.lines)
    time.sleep(0.3)
    assert len(printed.lines) == 1
