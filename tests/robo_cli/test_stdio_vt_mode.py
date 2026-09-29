"""Windows console VT mode: colors render instead of printing ``←[33m`` text.

Windows Terminal turns VT processing on for every app; the classic console
window (conhost — the Windows Server default) leaves it off, so every
colored line Robo prints (setup menus, doctor, banners) showed up as raw
escape codes there.
"""

from __future__ import annotations

import sys

import pytest

from robo_cli import stdio

VT = stdio.ENABLE_VIRTUAL_TERMINAL_PROCESSING
OUT = stdio._STD_OUTPUT_HANDLE
ERR = stdio._STD_ERROR_HANDLE


class FakeConsole:
    def __init__(self, modes, *, set_ok=True):
        self.modes = dict(modes)  # std id -> mode, missing = not a console
        self.set_ok = set_ok
        self.set_calls = []

    def get_mode(self, std_id):
        return self.modes.get(std_id)

    def set_mode(self, std_id, mode):
        self.set_calls.append((std_id, mode))
        if self.set_ok:
            self.modes[std_id] = mode
        return self.set_ok


def test_turns_vt_on_for_stdout_and_stderr_keeping_other_mode_bits():
    console = FakeConsole({OUT: 0x0003, ERR: 0x0001})

    assert stdio._enable_vt_processing(console.get_mode, console.set_mode) is True

    assert console.modes[OUT] == 0x0003 | VT
    assert console.modes[ERR] == 0x0001 | VT


def test_already_on_is_left_alone():
    console = FakeConsole({OUT: 0x0003 | VT, ERR: 0x0003 | VT})

    assert stdio._enable_vt_processing(console.get_mode, console.set_mode) is True

    assert console.set_calls == []


def test_redirected_stdout_reports_false_and_is_not_touched():
    console = FakeConsole({ERR: 0x0003})  # stdout is a file/pipe

    assert stdio._enable_vt_processing(console.get_mode, console.set_mode) is False

    assert all(std_id != OUT for std_id, _ in console.set_calls)


def test_console_that_refuses_vt_reports_false():
    console = FakeConsole({OUT: 0x0003, ERR: 0x0003}, set_ok=False)

    assert stdio._enable_vt_processing(console.get_mode, console.set_mode) is False


def test_non_windows_is_a_noop(monkeypatch):
    monkeypatch.setattr(stdio, "is_windows", lambda: False)

    def must_not_run():
        raise AssertionError("console API must not be touched off Windows")

    monkeypatch.setattr(stdio, "_win32_console_mode_fns", must_not_run)

    assert stdio.enable_windows_vt_mode() is False


def test_console_api_failure_never_raises(monkeypatch):
    monkeypatch.setattr(stdio, "is_windows", lambda: True)

    def boom():
        raise OSError("no kernel32")

    monkeypatch.setattr(stdio, "_win32_console_mode_fns", boom)

    assert stdio.enable_windows_vt_mode() is False


def test_configure_windows_stdio_turns_vt_on(monkeypatch):
    calls = []
    monkeypatch.setattr(stdio, "_CONFIGURED", False)
    monkeypatch.setattr(stdio, "is_windows", lambda: True)
    monkeypatch.setattr(stdio, "enable_windows_vt_mode", lambda: calls.append("vt") or True)
    monkeypatch.setattr(stdio, "_flip_console_code_page_to_utf8", lambda: None)
    monkeypatch.setattr(stdio, "_augment_path_with_known_tools", lambda: None)
    monkeypatch.setattr(stdio, "_reconfigure_stream", lambda *a, **k: None)
    monkeypatch.setenv("EDITOR", "notepad")
    for name in ("PYTHONIOENCODING", "PYTHONUTF8", "ROBO_DISABLE_WINDOWS_UTF8"):
        monkeypatch.delenv(name, raising=False)

    stdio.configure_windows_stdio()

    assert calls == ["vt"]


@pytest.mark.skipif(sys.platform != "win32", reason="real kernel32 console API")
def test_real_console_api_on_windows_does_not_raise():
    # Under pytest stdout is captured (not a console); the call must still
    # return a bool without raising.
    assert stdio.enable_windows_vt_mode() in (True, False)


class TestConsoleFontHint:
    """Raster console fonts (Windows Server's default conhost window) only
    have the OEM code page's glyphs, so Robo's symbols show up as '?'."""

    def _windows(self, monkeypatch):
        monkeypatch.setattr(stdio, "is_windows", lambda: True)

    def test_raster_font_gets_a_hint_naming_windows_terminal(self, monkeypatch):
        self._windows(monkeypatch)

        hint = stdio.windows_console_font_hint(environ={}, font_is_raster=lambda: True)

        assert hint and "Windows Terminal" in hint

    def test_truetype_font_gets_no_hint(self, monkeypatch):
        self._windows(monkeypatch)

        assert stdio.windows_console_font_hint(environ={}, font_is_raster=lambda: False) is None

    def test_unreadable_font_gets_no_hint(self, monkeypatch):
        self._windows(monkeypatch)

        assert stdio.windows_console_font_hint(environ={}, font_is_raster=lambda: None) is None

        def boom():
            raise OSError("no console")

        assert stdio.windows_console_font_hint(environ={}, font_is_raster=boom) is None

    def test_windows_terminal_and_vscode_never_get_a_hint(self, monkeypatch):
        self._windows(monkeypatch)

        for env in ({"WT_SESSION": "abc"}, {"TERM_PROGRAM": "vscode"}):
            assert stdio.windows_console_font_hint(environ=env, font_is_raster=lambda: True) is None

    def test_non_windows_never_gets_a_hint(self, monkeypatch):
        monkeypatch.setattr(stdio, "is_windows", lambda: False)

        assert stdio.windows_console_font_hint(environ={}, font_is_raster=lambda: True) is None

    @pytest.mark.skipif(sys.platform != "win32", reason="real kernel32 console API")
    def test_real_font_query_on_windows_does_not_raise(self):
        hint = stdio.windows_console_font_hint()
        assert hint is None or isinstance(hint, str)
