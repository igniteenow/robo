"""Windows-safe stdio configuration.

On Windows, Python's ``sys.stdout``/``sys.stderr`` default to the console's
active code page (often ``cp1252``, sometimes ``cp437``, occasionally ``cp932``
on Japanese locales, etc.).  Robo's banners, tool output feed, and slash
command listings all contain Unicode: box-drawing characters (``─┌┐└┘├┤``),
mathematical and geometric symbols (``◆ ◇ ◎ ▣ ⚔ ⚖ →``), and user-supplied
text in any language.  Printing those to a cp1252 console raises
``UnicodeEncodeError: 'charmap' codec can't encode character…`` and kills the
whole CLI before the REPL even opens.

The fix is to force UTF-8 on the Python side and also flip the console's
code page to UTF-8 (65001).  Both matter: Python-level only helps when
Python's stdout is a real TTY; code-page flipping lets subprocesses and
child Python ``print()`` calls agree on encoding.

This module is a no-op on every non-Windows platform, and idempotent.
Entry points (``cli.py`` ``main``, ``robo_cli/main.py`` CLI dispatch,
``gateway/run.py`` startup) call :func:`configure_windows_stdio` exactly
once early in startup.

Patterns cribbed from Claude Code (``src/utils/platform.ts``), OpenCode
(``packages/opencode/src/pty/index.ts`` env injection), and OpenAI Codex
(``codex-rs/core/src/unified_exec/process_manager.rs``).  None of those
actually flip the console code page — they rely on their runtime (Node or
Rust) writing UTF-16 to the Win32 console API and letting the terminal
sort it out.  Python doesn't get that luxury.
"""

from __future__ import annotations

import os
import sys

__all__ = ["configure_windows_stdio", "enable_windows_vt_mode", "is_windows"]


_CONFIGURED = False

# SetConsoleMode flag that makes the console interpret ANSI/VT escape codes
# (colors, cursor moves).  Windows Terminal turns it on for every app; the
# classic console window (conhost — the default on Windows Server) leaves it
# off, so colored output shows up as literal ``←[33m…`` text.
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_OUTPUT_HANDLE = -11
_STD_ERROR_HANDLE = -12


def is_windows() -> bool:
    """Return True iff running on native Windows (not WSL)."""
    return sys.platform == "win32"


def _enable_vt_processing(get_mode, set_mode) -> bool:
    """Turn on VT processing for the stdout and stderr consoles.

    ``get_mode(std_handle_id)`` returns the console mode, or ``None`` when
    that stream is not a console (redirected to a file or pipe).
    ``set_mode(std_handle_id, mode)`` returns True on success.

    Returns True when stdout is a console that now renders escape codes.
    """
    stdout_vt = False
    for std_id in (_STD_OUTPUT_HANDLE, _STD_ERROR_HANDLE):
        mode = get_mode(std_id)
        if mode is None:
            continue
        if mode & ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            enabled = True
        else:
            enabled = bool(set_mode(std_id, mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING))
        if std_id == _STD_OUTPUT_HANDLE:
            stdout_vt = enabled
    return stdout_vt


def _win32_console_mode_fns():
    """Return ``(get_mode, set_mode)`` backed by kernel32 console calls."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetConsoleMode.restype = wintypes.BOOL
    kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetConsoleMode.restype = wintypes.BOOL

    def get_mode(std_id: int):
        handle = kernel32.GetStdHandle(std_id)
        if not handle or handle == ctypes.c_void_p(-1).value:
            return None
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return None  # not a console (file / pipe)
        return mode.value

    def set_mode(std_id: int, mode: int) -> bool:
        handle = kernel32.GetStdHandle(std_id)
        if not handle or handle == ctypes.c_void_p(-1).value:
            return False
        return bool(kernel32.SetConsoleMode(handle, mode))

    return get_mode, set_mode


_TMPF_TRUETYPE = 0x04


def _console_font_is_raster():
    """True when stdout's console window uses a raster (bitmap) font.

    Raster fonts only have the OEM code page's glyphs, so ``◆ ╭ ━`` and most
    other symbols Robo draws show up as ``?``.  Returns None when stdout is
    not a console.
    """
    import ctypes
    from ctypes import wintypes

    class _ConsoleFontInfoEx(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.ULONG),
            ("nFont", wintypes.DWORD),
            ("dwFontSize", wintypes._COORD),
            ("FontFamily", wintypes.UINT),
            ("FontWeight", wintypes.UINT),
            ("FaceName", wintypes.WCHAR * 32),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.GetCurrentConsoleFontEx.argtypes = [
        wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(_ConsoleFontInfoEx),
    ]
    kernel32.GetCurrentConsoleFontEx.restype = wintypes.BOOL
    handle = kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
    if not handle or handle == ctypes.c_void_p(-1).value:
        return None
    info = _ConsoleFontInfoEx()
    info.cbSize = ctypes.sizeof(info)
    if not kernel32.GetCurrentConsoleFontEx(handle, False, ctypes.byref(info)):
        return None
    return not (info.FontFamily & _TMPF_TRUETYPE)


def windows_console_font_hint(environ=None, font_is_raster=None):
    """One-line hint when this console window cannot draw Robo's symbols.

    Returns None everywhere else: non-Windows, Windows Terminal / VS Code
    (they draw every symbol), a TrueType console font, or when the font
    cannot be read.  Never raises.
    """
    env = os.environ if environ is None else environ
    if not is_windows():
        return None
    if env.get("WT_SESSION") or env.get("TERM_PROGRAM"):
        return None
    try:
        raster = (font_is_raster or _console_font_is_raster)()
    except Exception:
        return None
    if not raster:
        return None
    return (
        "Note: this console window uses a raster font, so Robo's symbols show "
        "as '?'. Open Robo in Windows Terminal (search 'Terminal' in Start), "
        "or choose Consolas in this window's Properties > Font."
    )


def enable_windows_vt_mode() -> bool:
    """Make the Windows console render ANSI color and cursor codes.

    No-op on non-Windows.  Never raises.  Returns True when stdout is a
    console that renders escape codes (already on, or switched on here).
    Only the VT flag is added; every other console mode bit is kept.
    """
    if not is_windows():
        return False
    try:
        get_mode, set_mode = _win32_console_mode_fns()
        return _enable_vt_processing(get_mode, set_mode)
    except Exception:
        return False


def _flip_console_code_page_to_utf8() -> None:
    """Set the attached console's input and output code pages to UTF-8.

    Uses ``SetConsoleCP`` / ``SetConsoleOutputCP`` via ``ctypes``.  Failure
    is silent — if there's no attached console (e.g. Robo is running
    behind a redirected stdout, under a service, or inside a PTY-less CI
    runner) these calls simply return 0 and we move on.

    CP_UTF8 is 65001.
    """
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        # Best-effort; if there's no console attached these just fail silently.
        kernel32.SetConsoleCP(65001)
        kernel32.SetConsoleOutputCP(65001)
    except Exception:
        # ctypes import, missing kernel32, or non-Windows — any failure here
        # is non-fatal.  We've still reconfigured Python's own streams below.
        pass


def _reconfigure_stream(stream, *, encoding: str = "utf-8", errors: str = "replace") -> None:
    """Reconfigure a text stream to UTF-8 in place.

    Uses ``TextIOWrapper.reconfigure`` (Python 3.7+).  If the stream isn't
    a ``TextIOWrapper`` (e.g. it's been redirected to an ``io.StringIO``
    during tests), we skip rather than blow up.
    """
    try:
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            return
        reconfigure(encoding=encoding, errors=errors)
    except Exception:
        pass


def configure_windows_stdio() -> bool:
    """Force UTF-8 stdio on Windows.  No-op elsewhere.

    Idempotent — safe to call multiple times from different entry points.

    Returns ``True`` if anything was actually changed, ``False`` on
    non-Windows or on a repeat call.

    Set ``ROBO_DISABLE_WINDOWS_UTF8=1`` in the environment to opt out
    (for diagnosing encoding-related bugs by forcing the old cp1252 path).

    Also sets a sensible default ``EDITOR`` on Windows if none is already
    set — see :func:`_default_windows_editor`.
    """
    global _CONFIGURED

    if _CONFIGURED:
        return False
    if not is_windows():
        # Mark configured so repeated calls on POSIX are true no-ops.
        _CONFIGURED = True
        return False

    # Render colors instead of printing raw ``←[33m`` codes in the classic
    # console window (conhost, the Windows Server default).
    enable_windows_vt_mode()

    if os.environ.get("ROBO_DISABLE_WINDOWS_UTF8") in {"1", "true", "True", "yes"}:
        _CONFIGURED = True
        return False

    # Encourage every child Python process spawned by the agent to also use
    # UTF-8 for its stdio.  PYTHONIOENCODING wins over the locale-based
    # default in subprocesses.  Don't override an explicit user setting.
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # PYTHONUTF8 = 1 enables UTF-8 Mode globally for any Python subprocess
    # (PEP 540).  Again, don't override an explicit setting.
    os.environ.setdefault("PYTHONUTF8", "1")

    # Set EDITOR to a working Windows default if neither EDITOR nor VISUAL
    # is set.  prompt_toolkit's ``open_in_editor`` falls back to POSIX-only
    # paths (``/usr/bin/nano``, ``/usr/bin/vi``) that don't exist on
    # Windows — Ctrl+X Ctrl+E and ``/edit`` silently do nothing there
    # otherwise.  This happens even with full Git for Windows installed,
    # so it's not a MinGit-specific issue.
    _default_editor = _default_windows_editor()
    if _default_editor and not os.environ.get("EDITOR") and not os.environ.get("VISUAL"):
        os.environ["EDITOR"] = _default_editor

    # Augment PATH with the Robo-managed Git install directories so
    # subprocess calls (bash, rg, grep, etc.) resolve even in sessions
    # that started before the User PATH broadcast reached them.  When
    # install.ps1 adds these to User PATH via SetEnvironmentVariable,
    # already-running shells don't see the change — which means robo
    # launched from the install session won't find rg / bash / grep
    # even though they're "installed".  Prepending the known paths here
    # closes that gap.  No-op when the paths don't exist (e.g. system-Git
    # install without Robo-managed PortableGit).
    _augment_path_with_known_tools()

    # Flip the console code page first so that any subprocess that
    # inherits the console (e.g. a launched shell) also sees CP_UTF8.
    _flip_console_code_page_to_utf8()

    # Reconfigure Python's own stdio wrappers so ``print()`` calls from
    # this process round-trip emoji / box-drawing / non-Latin text.
    # ``errors="replace"`` means a genuinely unencodable byte sequence
    # gets a ``?`` rather than crashing the interpreter — we prefer
    # degraded output over a stack trace.
    _reconfigure_stream(sys.stdout)
    _reconfigure_stream(sys.stderr)
    # stdin is re-configured for completeness; Robo's interactive
    # input path uses prompt_toolkit which manages its own encoding,
    # but batch/pipe input benefits from UTF-8 decoding on stdin too.
    _reconfigure_stream(sys.stdin)

    _CONFIGURED = True
    return True


def _default_windows_editor() -> str:
    """Return a Windows-appropriate default for ``$EDITOR``.

    Priority order, first match wins:

    1. ``notepad`` — ships with every Windows install, no deps, works as a
       blocking editor (``subprocess.call(["notepad", file])`` blocks until
       the user closes the window).  This is the "always-works" default.

    The prompt_toolkit buffer's ``open_in_editor`` and Robo's
    ``robo config edit`` both honour ``$EDITOR``.  Users who prefer a
    different editor can override:

    - VSCode: ``$env:EDITOR = "code --wait"``  (``--wait`` is critical;
      without it the editor returns immediately and any input is lost)
    - Notepad++: ``$env:EDITOR = "'C:\\Program Files\\Notepad++\\notepad++.exe' -multiInst -nosession"``
    - Neovim: ``$env:EDITOR = "nvim"``  (if installed)

    Set this before launching Robo (User env var in Windows Settings, or
    export in a PowerShell profile) and Robo picks it up automatically.
    """
    import shutil

    # notepad.exe is always in %SystemRoot%\System32 on Windows, so shutil.which
    # will reliably find it.  Return the bare name so prompt_toolkit's shlex
    # split doesn't trip over a path containing spaces.
    if shutil.which("notepad"):
        return "notepad"
    # On the extreme off-chance notepad is missing (WinPE, Nano Server), fall
    # back to nothing and let prompt_toolkit's silent no-op do its thing.
    return ""



def _augment_path_with_known_tools() -> None:
    """Prepend well-known Robo-managed tool directories to os.environ['PATH'].

    Fixes the "User PATH was just updated but my process can't see it" gap on
    Windows.  When install.ps1 runs, it adds entries like
    ``%LOCALAPPDATA%\\robo\\git\\bin`` to the User PATH via
    ``SetEnvironmentVariable(..., "User")``.  That write propagates to newly
    *spawned* processes only — already-running shells (including the one the
    user invokes ``robo`` from right after install) retain their old PATH.

    Any subprocess Robo spawns — bash, ``rg``, ``grep``, ``npm`` — inherits
    that stale PATH and reports commands as missing even though they're on
    disk.  Symptom: ``search_files`` reports "rg/find not available" when
    the user clearly just installed ripgrep.

    Patch-up strategy: add the known Robo-managed tool directories to our
    PATH at startup so subprocess calls resolve correctly.  No-op on POSIX
    and when the directories don't exist.  The User PATH broadcast still
    happens in the background for future shells; this just smooths over
    the first-launch gap.
    """
    if not is_windows():
        return


    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if not local_appdata:
        return

    # Known tool dirs installed by scripts/install.ps1.  Kept in sync with
    # the PATH entries that installer adds to User scope — the two lists
    # should match so this prefill fully mirrors what a fresh shell would
    # see on next launch.
    candidate_dirs = [
        os.path.join(local_appdata, "robo", "git", "cmd"),
        os.path.join(local_appdata, "robo", "git", "bin"),
        os.path.join(local_appdata, "robo", "git", "usr", "bin"),
        # Robo venv Scripts directory — host of the robo.exe shim itself,
        # also where any pip-installed console scripts land.  Usually already
        # on PATH when the user invokes robo, but harmless to include.
        os.path.join(local_appdata, "robo", "robo-engineer", "venv", "Scripts"),
        # WinGet packages directory — where ``winget install`` drops CLI
        # shims by default (ripgrep lands here as rg.exe).  Covers the case
        # of a system-Git install + ripgrep-via-winget that isn't yet on
        # the spawning shell's PATH.
        os.path.join(local_appdata, "Microsoft", "WinGet", "Links"),
    ]

    existing = os.environ.get("PATH", "")
    existing_lower = {p.lower() for p in existing.split(os.pathsep) if p}
    prepend = []
    for d in candidate_dirs:
        if os.path.isdir(d) and d.lower() not in existing_lower:
            prepend.append(d)

    if prepend:
        os.environ["PATH"] = os.pathsep.join([*prepend, existing])
