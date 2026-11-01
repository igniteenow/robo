"""Read-before-edit guard (agent/judgment.py ``read_before_edit``).

The first ``patch`` / ``write_file`` on an existing, non-empty, text file the
task has never read is stopped once with a plain "read it first" message; the
same call goes through on the next attempt. New files, empty files, binary
files, files already read in the task, non-local backends and a disabled
switch never block. The suite-wide conftest pins the guard off; these tests
opt back in.
"""

from __future__ import annotations

import json
import uuid

import pytest

from tools import file_tools
from tools.file_tools import patch_tool, read_file_tool, write_file_tool


@pytest.fixture
def guard_on(monkeypatch):
    monkeypatch.setenv("ROBO_READ_BEFORE_EDIT", "1")


@pytest.fixture
def task_id():
    tid = f"rbe-{uuid.uuid4().hex[:8]}"
    yield tid
    with file_tools._read_tracker_lock:
        file_tools._read_tracker.pop(tid, None)


def _patch(path, task_id, old="hello", new="goodbye"):
    return json.loads(
        patch_tool(mode="replace", path=str(path), old_string=old, new_string=new, task_id=task_id)
    )


def _write(path, task_id, content="replacement\n"):
    return json.loads(write_file_tool(str(path), content, task_id=task_id))


class TestBlocksOnceThenProceeds:
    def test_patch_on_unread_existing_file_is_stopped_once(self, tmp_path, guard_on, task_id):
        target = tmp_path / "app.py"
        target.write_text("hello\n")

        first = _patch(target, task_id)
        assert first.get("error")
        assert first.get("read_required") is True
        assert "Read" in first["error"] and "read_file" in first["error"]
        assert target.read_text() == "hello\n", "a stopped patch must not touch the file"

        second = _patch(target, task_id)
        assert not second.get("error"), second
        assert target.read_text() == "goodbye\n"

    def test_write_file_overwrite_of_unread_file_is_stopped_once(self, tmp_path, guard_on, task_id):
        target = tmp_path / "notes.txt"
        target.write_text("first draft\n")

        first = _write(target, task_id)
        assert first.get("error") and first.get("read_required") is True
        assert target.read_text() == "first draft\n"

        second = _write(target, task_id)
        assert not second.get("error"), second
        assert target.read_text() == "replacement\n"

    def test_stop_is_per_path_not_per_task(self, tmp_path, guard_on, task_id):
        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        a.write_text("hello\n")
        b.write_text("hello\n")

        assert _patch(a, task_id).get("read_required") is True
        # A different unread file is stopped on its own first attempt too.
        assert _patch(b, task_id).get("read_required") is True
        assert not _patch(a, task_id).get("error")
        assert not _patch(b, task_id).get("error")


class TestNeverBlocks:
    def test_file_read_in_this_task_edits_straight_away(self, tmp_path, guard_on, task_id):
        target = tmp_path / "read_first.py"
        target.write_text("hello\n")

        read = json.loads(read_file_tool(str(target), task_id=task_id))
        assert "hello" in read.get("content", "")

        result = _patch(target, task_id)
        assert not result.get("error"), result
        assert target.read_text() == "goodbye\n"

    def test_a_partial_read_counts(self, tmp_path, guard_on, task_id):
        target = tmp_path / "big.py"
        target.write_text("\n".join(f"line {i}" for i in range(200)) + "\nhello\n")

        read_file_tool(str(target), offset=190, limit=20, task_id=task_id)

        assert not _patch(target, task_id).get("error")

    def test_new_file_is_not_an_edit(self, tmp_path, guard_on, task_id):
        target = tmp_path / "fresh.py"

        result = _write(target, task_id, "print('hi')\n")
        assert not result.get("error"), result
        assert target.read_text() == "print('hi')\n"

    def test_empty_file_has_nothing_to_read(self, tmp_path, guard_on, task_id):
        target = tmp_path / "empty.py"
        target.write_text("")

        assert not _write(target, task_id, "x = 1\n").get("error")

    def test_binary_files_are_exempt(self, tmp_path, guard_on, task_id):
        target = tmp_path / "blob.png"
        target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

        assert file_tools._check_unread_edit(str(target), task_id, "write_file") is None

    def test_other_tasks_reads_do_not_count_but_a_second_attempt_still_proceeds(
        self, tmp_path, guard_on, task_id
    ):
        target = tmp_path / "shared.py"
        target.write_text("hello\n")
        other = f"{task_id}-other"
        try:
            read_file_tool(str(target), task_id=other)
            assert _patch(target, task_id).get("read_required") is True
            assert not _patch(target, task_id).get("error")
        finally:
            with file_tools._read_tracker_lock:
                file_tools._read_tracker.pop(other, None)

    def test_disabled_by_env(self, tmp_path, monkeypatch, task_id):
        monkeypatch.setenv("ROBO_READ_BEFORE_EDIT", "0")
        target = tmp_path / "off.py"
        target.write_text("hello\n")

        assert not _patch(target, task_id).get("error")

    def test_disabled_by_config(self, tmp_path, monkeypatch, task_id):
        monkeypatch.delenv("ROBO_READ_BEFORE_EDIT", raising=False)
        monkeypatch.setattr(
            "robo_cli.config.load_config_readonly",
            lambda: {"agent": {"judgment": {"read_before_edit": False}}},
        )
        target = tmp_path / "cfg_off.py"
        target.write_text("hello\n")

        assert not _patch(target, task_id).get("error")

    def test_non_local_backend_is_skipped(self, tmp_path, guard_on, task_id, monkeypatch):
        monkeypatch.setattr(file_tools, "_terminal_env_type_for_task", lambda _tid="default": "ssh")
        target = tmp_path / "remote.py"
        target.write_text("hello\n")

        assert file_tools._check_unread_edit(str(target), task_id, "patch") is None

    def test_guard_failure_fails_open(self, tmp_path, guard_on, task_id, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("tracker exploded")

        monkeypatch.setattr(file_tools, "_resolve_path_for_task", boom)
        target = tmp_path / "boom.py"
        target.write_text("hello\n")

        assert file_tools._check_unread_edit(str(target), task_id, "patch") is None


class TestJudgmentConfig:
    def test_defaults_on(self, monkeypatch):
        from agent.judgment import judgment_enabled

        monkeypatch.delenv("ROBO_READ_BEFORE_EDIT", raising=False)
        monkeypatch.delenv("ROBO_EVIDENCE_CLAIMS", raising=False)
        assert judgment_enabled("read_before_edit", config={}) is True
        assert judgment_enabled("evidence_claims", config={}) is True
        assert judgment_enabled("not_a_feature", config={}) is False

    def test_env_beats_config(self, monkeypatch):
        from agent.judgment import judgment_enabled

        monkeypatch.setenv("ROBO_EVIDENCE_CLAIMS", "off")
        assert judgment_enabled("evidence_claims", config={"agent": {"judgment": {"evidence_claims": True}}}) is False
        monkeypatch.setenv("ROBO_EVIDENCE_CLAIMS", "1")
        assert judgment_enabled("evidence_claims", config={"agent": {"judgment": {"evidence_claims": False}}}) is True

    def test_section_bool_switches_everything(self, monkeypatch):
        from agent.judgment import judgment_enabled

        monkeypatch.delenv("ROBO_READ_BEFORE_EDIT", raising=False)
        assert judgment_enabled("read_before_edit", config={"agent": {"judgment": False}}) is False

    def test_default_config_ships_the_section(self):
        from robo_cli.config_defaults import DEFAULT_CONFIG

        section = DEFAULT_CONFIG["agent"]["judgment"]
        assert section["read_before_edit"] is True
        assert section["evidence_claims"] is True
