"""The progress heartbeat: a line every interval while a quiet step runs."""

from __future__ import annotations

import time

from robo_cli.progress_heartbeat import format_elapsed, heartbeat, heartbeat_line


def test_format_elapsed_reads_like_a_person_would_say_it():
    assert format_elapsed(0) == "0 s"
    assert format_elapsed(45.9) == "45 s"
    assert format_elapsed(90) == "1 min 30 s"
    assert format_elapsed(725) == "12 min 05 s"
    assert format_elapsed(-3) == "0 s"


def test_heartbeat_line_carries_label_elapsed_and_optional_hint():
    assert heartbeat_line("installing desktop packages", 90) == "  … installing desktop packages (1 min 30 s)"
    assert heartbeat_line("building", 5, "a few minutes") == "  … building (5 s) — a few minutes"


def test_heartbeat_emits_on_the_interval_with_the_hint_once_and_stops_at_exit():
    lines: list[str] = []
    with heartbeat("working", hint="first time takes a while", interval=0.05, write=lines.append):
        time.sleep(0.3)
    count_at_exit = len(lines)
    assert count_at_exit >= 2
    assert lines[0].startswith("  … working (") and lines[0].endswith(" — first time takes a while")
    assert all(" — " not in line for line in lines[1:])
    # Nothing more after the block ended.
    time.sleep(0.15)
    assert len(lines) == count_at_exit


def test_heartbeat_is_silent_for_a_step_shorter_than_the_interval():
    lines: list[str] = []
    with heartbeat("quick", interval=5.0, write=lines.append):
        pass
    assert lines == []


def test_heartbeat_survives_a_writer_that_raises():
    calls = {"n": 0}

    def broken(_line: str) -> None:
        calls["n"] += 1
        raise BrokenPipeError

    with heartbeat("working", interval=0.02, write=broken):
        time.sleep(0.2)
    # One attempt, then it gave up quietly; the block itself was unaffected.
    assert calls["n"] == 1


def test_heartbeat_default_writer_prints_whole_lines(capsys):
    with heartbeat("working", interval=0.02):
        time.sleep(0.1)
    out = capsys.readouterr().out
    assert out.startswith("  … working (")
    assert out.endswith("\n")
