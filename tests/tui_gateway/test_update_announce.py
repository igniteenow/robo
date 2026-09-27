"""Sessions that start before the update check answers still get the notice.

A session's info carries the update check's answer only if it arrived within
half a second of the session starting; a check that reaches the network
usually takes longer. Once it answers, every open session's info is refreshed
so the TUI's "↑ N updates behind — run robo update" line appears at once.
"""

import threading

import pytest

import robo_cli.banner as banner
from tui_gateway import server


@pytest.fixture
def emitted(monkeypatch):
    events = []
    monkeypatch.setattr(server, "_emit", lambda event, sid, payload=None: events.append((event, sid, payload)))
    monkeypatch.setattr(server, "_session_info", lambda agent, session=None: {"update_behind": banner.get_update_result(0)})
    monkeypatch.setitem(server._sessions, "open", {"agent": object()})
    monkeypatch.setitem(server._sessions, "starting", {"agent": None})  # gets it when it finishes starting
    return events


@pytest.fixture
def check(monkeypatch):
    done = threading.Event()
    monkeypatch.setattr(banner, "_update_check_done", done)
    monkeypatch.setattr(banner, "_update_result", None)

    def answer(result):
        monkeypatch.setattr(banner, "_update_result", result)
        done.set()

    return answer


def test_open_sessions_hear_about_an_update_that_arrives_late(emitted, check):
    announcer = threading.Thread(target=server._announce_update_when_known, args=(5,), daemon=True)
    announcer.start()
    announcer.join(0.3)
    assert announcer.is_alive() and emitted == []  # still waiting for the check

    check(4)
    announcer.join(5)

    assert emitted == [("session.info", "open", {"update_behind": 4})]


@pytest.mark.parametrize("result", [0, None])
def test_nothing_is_sent_when_up_to_date_or_unknown(emitted, check, result):
    check(result)

    server._announce_update_when_known(wait=1)

    assert emitted == []


def test_a_check_that_never_answers_just_gives_up(emitted, check):
    server._announce_update_when_known(wait=0.2)

    assert emitted == []
