"""Run ``robo dashboard`` in the background so it outlives the terminal.

Before this, ``robo dashboard`` served from the terminal that started it:
closing that window (or logging out of the SSH session on a remote box) took
the dashboard down, and ``http://127.0.0.1:9119`` stopped answering. The
Desktop launcher already solved the same problem for Electron
(``robo_cli.main._launch_desktop_detached``); this module does the same for
the dashboard.

How it works: when ``robo dashboard`` is started from an interactive terminal,
the command does everything that needs the person at the keyboard (web UI
build, the username/password prompt for a network bind), then re-launches
itself as a detached child with ``--foreground --no-open --skip-build``. The
child gets its own session (POSIX ``start_new_session``; Windows
``CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB``),
no inherited stdio, and writes its output to
``<ROBO_HOME>/logs/dashboard-stdio.log``. The parent follows that log until the
child prints its ``ROBO_DASHBOARD_READY port=N`` line, opens the browser, and
exits. ``robo dashboard --stop`` / ``--status`` find the child by its
``robo_cli.main dashboard`` command line, exactly as before.

Everything that is not an interactive terminal keeps the old foreground
behaviour unchanged: the headless ``robo serve`` backend (what the Desktop app
spawns), anything with ``ROBO_DESKTOP=1``, containers (Docker/s6 supervise the
process), systemd units, Windows Scheduled Tasks, pipes and CI. ``--foreground``
opts out explicitly.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional, TextIO

READY_RE = re.compile(r"ROBO_DASHBOARD_READY port=(\d+)")

# How long the parent waits for the background dashboard to report ready.
# A cold start (skill sync, plugin + provider discovery, first imports on a
# slow Windows disk) can take a while; the child keeps starting even if we
# give up waiting.
READY_TIMEOUT_S = 180.0
# After the READY line, keep relaying the child's output briefly so the
# "Robo Web UI → …" and reachable-address lines show up in the terminal.
POST_READY_GRACE_S = 0.6
# Rotate the stdio log when it grows past this size at launch time.
LOG_ROTATE_BYTES = 5 * 1024 * 1024


def _is_tty(stream) -> bool:
    try:
        return bool(stream is not None and stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _in_container() -> bool:
    try:
        from robo_cli._startup_fast import is_container_startup_environment

        return bool(is_container_startup_environment())
    except Exception:
        return False


def should_run_in_background(
    args,
    *,
    headless: bool,
    env: Optional[dict] = None,
    stdin=None,
    stdout=None,
    in_container: Optional[bool] = None,
) -> bool:
    """True when this ``robo dashboard`` run should detach from the terminal.

    Only an interactive ``robo dashboard`` detaches. Every supervised or
    programmatic launch keeps the foreground behaviour its caller relies on.
    """
    env = os.environ if env is None else env
    if headless:
        return False  # `robo serve` — the Desktop/remote backend, never detached here
    if getattr(args, "foreground", False):
        return False
    if env.get("ROBO_DESKTOP") == "1":
        return False  # spawned by the Desktop app, which owns its lifetime
    if getattr(args, "status", False) or getattr(args, "stop", False):
        return False
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    if not (_is_tty(stdin) and _is_tty(stdout)):
        return False  # systemd, Scheduled Tasks, pipes, CI, `robo update` respawns
    if in_container is None:
        in_container = _in_container()
    if in_container:
        return False  # the container's init supervises the process
    return True


def dashboard_stdio_log_path() -> Path:
    """``<ROBO_HOME>/logs/dashboard-stdio.log`` — the background dashboard's output."""
    from robo_constants import get_robo_home

    log_dir = Path(get_robo_home()) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "dashboard-stdio.log"


def _rotate_log(log_path: Path) -> None:
    try:
        if log_path.exists() and log_path.stat().st_size > LOG_ROTATE_BYTES:
            old = log_path.with_name(log_path.name + ".1")
            try:
                old.unlink()
            except FileNotFoundError:
                pass
            log_path.rename(old)
    except OSError:
        pass  # a locked/unrenamable log must never block the launch


def build_background_argv(
    args,
    *,
    profile_name: Optional[str],
    python: Optional[str] = None,
) -> list[str]:
    """argv for the detached child: the same dashboard, in the foreground.

    ``--foreground`` stops the child from detaching again, ``--no-open`` keeps
    the browser with the parent (it opens once, after READY), and
    ``--skip-build`` reuses the web UI the parent just built.
    """
    # "robo_cli.main dashboard" must stay adjacent: `--stop` / `--status`
    # and `robo update` find running dashboards by that cmdline substring.
    argv = [python or sys.executable, "-m", "robo_cli.main", "dashboard"]
    if profile_name and profile_name != "custom":
        # Pin the profile explicitly (-p is honoured after the subcommand): a
        # bare child would re-read the sticky active_profile file and could
        # land in a different profile.
        argv += ["-p", profile_name]
    argv += [
        "--host", str(getattr(args, "host", None) or "127.0.0.1"),
        "--port", str(getattr(args, "port", 9119)),
        "--foreground",
        "--no-open",
        "--skip-build",
    ]
    if getattr(args, "isolated", False):
        argv.append("--isolated")
    open_profile = getattr(args, "open_profile", "") or ""
    if open_profile:
        argv += ["--open-profile", open_profile]
    return argv


def build_background_env(env: Optional[dict] = None) -> dict:
    child_env = dict(os.environ if env is None else env)
    # The child writes to a file, not a console: flush every line so the
    # parent sees READY immediately, and keep the "→" glyphs encodable on
    # Windows code pages.
    child_env["PYTHONUNBUFFERED"] = "1"
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    return child_env


def spawn_detached(argv: list[str], *, env: dict, log_path: Path) -> subprocess.Popen:
    """Start ``argv`` in its own session with stdio going to ``log_path``."""
    def _spawn(extra: dict) -> subprocess.Popen:
        with open(log_path, "ab", buffering=0) as log_fh:
            return subprocess.Popen(
                argv,
                env=env,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                **extra,
            )

    if sys.platform == "win32":
        from robo_cli._subprocess_compat import (
            windows_detach_flags,
            windows_detach_flags_without_breakaway,
        )

        try:
            return _spawn({"creationflags": windows_detach_flags()})
        except OSError:
            # Some job objects refuse CREATE_BREAKAWAY_FROM_JOB; the hidden
            # own-console spawn is enough on its own there.
            return _spawn({"creationflags": windows_detach_flags_without_breakaway()})
    return _spawn({"start_new_session": True})


def wait_for_ready(
    proc,
    log_path: Path,
    start_offset: int,
    *,
    timeout: float = READY_TIMEOUT_S,
    grace: float = POST_READY_GRACE_S,
    out: Optional[TextIO] = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[Optional[int], Optional[int]]:
    """Relay the child's new log output until it reports READY.

    Returns ``(port, None)`` on success, ``(None, exit_code)`` when the child
    exited first, and ``(None, None)`` on timeout (child still running).
    """
    out = sys.stdout if out is None else out
    pos = start_offset
    pending = b""
    port: Optional[int] = None
    ready_at: Optional[float] = None
    deadline = clock() + timeout

    def _drain() -> None:
        nonlocal pos, pending, port, ready_at
        try:
            with open(log_path, "rb") as fh:
                fh.seek(pos)
                chunk = fh.read()
        except OSError:
            return
        if not chunk:
            return
        pos += len(chunk)
        pending += chunk
        *lines, pending = pending.split(b"\n")
        for raw in lines:
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            match = READY_RE.search(line)
            if match and port is None:
                port = int(match.group(1))
                ready_at = clock()
                continue  # internal sentinel — not for the person
            try:
                print(line, file=out, flush=True)
            except (UnicodeEncodeError, OSError, ValueError):
                pass

    while True:
        _drain()
        now = clock()
        if ready_at is not None and now - ready_at >= grace:
            return port, None
        code = proc.poll()
        if code is not None:
            _drain()
            if pending:
                try:
                    print(pending.decode("utf-8", errors="replace"), file=out, flush=True)
                except (UnicodeEncodeError, OSError, ValueError):
                    pass
            if port is not None:
                return port, None
            return None, code
        if now >= deadline and ready_at is None:
            return None, None
        sleep(0.1)


def _display_host(host: str) -> str:
    return "127.0.0.1" if host in ("0.0.0.0", "::", "") else host


def launch_dashboard_in_background(
    args,
    *,
    profile_name: Optional[str],
    open_browser: Optional[Callable[[str, int, bool, str], None]] = None,
    timeout: float = READY_TIMEOUT_S,
) -> int:
    """Start the detached dashboard, wait for READY, open the browser.

    Returns this command's exit code: 0 once the dashboard is serving.
    """
    host = str(getattr(args, "host", None) or "127.0.0.1")
    log_path = dashboard_stdio_log_path()
    _rotate_log(log_path)
    try:
        start_offset = log_path.stat().st_size
    except OSError:
        start_offset = 0

    argv = build_background_argv(args, profile_name=profile_name)
    print("→ Starting the Robo dashboard in the background…", flush=True)
    try:
        proc = spawn_detached(argv, env=build_background_env(), log_path=log_path)
    except OSError as exc:
        print(f"✗ Could not start the dashboard in the background: {exc}")
        print("  Run it in this terminal instead:  robo dashboard --foreground")
        return 1

    try:
        port, exit_code = wait_for_ready(proc, log_path, start_offset, timeout=timeout)
    except KeyboardInterrupt:
        # Ctrl+C while it is still starting means "never mind".
        try:
            proc.terminate()
        except OSError:
            pass
        print("\n  Cancelled — the dashboard was stopped.")
        return 130

    if port is None:
        if exit_code is not None:
            print(f"✗ The dashboard stopped while starting (exit code {exit_code}).")
            print(f"  Full output: {log_path}")
            return exit_code or 1
        print("⚠ The dashboard is still starting in the background.")
        print("  Check it with:  robo dashboard --status")
        print(f"  Output:         {log_path}")
        return 1

    if open_browser is not None and not getattr(args, "no_open", False):
        try:
            open_browser(host, port, True, getattr(args, "open_profile", "") or "")
        except Exception:
            pass

    print()
    print(f"✓ Robo dashboard is running in the background (PID {proc.pid}).")
    if host in ("0.0.0.0", "::"):
        print(f"  Open on this computer:  http://127.0.0.1:{port}")
        print("  From other devices:     use a 'Reachable from other machines' address above")
    else:
        print(f"  Open:  http://{_display_host(host)}:{port}")
    print("  It keeps running after you close this terminal.")
    print("  Stop it:          robo dashboard --stop")
    print(f"  Output:           {log_path}")
    print("  Run it attached:  robo dashboard --foreground")
    return 0


def find_running_dashboard(
    host: str,
    port: int,
    *,
    scan: Callable[[], list[tuple[int, str]]],
    parse: Callable[[str], Optional[tuple[str, str, int]]],
    listening: Callable[[str, int], bool],
) -> Optional[tuple[int, str]]:
    """Return ``(pid, host)`` of a live Robo dashboard already serving ``port``."""
    if not port:
        return None  # --port 0 asks for a fresh ephemeral port
    try:
        processes = scan()
    except Exception:
        return None
    for pid, command in processes:
        runtime = parse(command)
        if runtime is None:
            continue
        mode, running_host, running_port = runtime
        if mode != "dashboard" or running_port != port:
            continue
        if listening(running_host, running_port):
            return pid, running_host
    return None


def _normalize_host(host: str) -> str:
    host = (host or "127.0.0.1").strip().strip("[]").lower()
    return "127.0.0.1" if host == "localhost" else host


def same_bind(a: str, b: str) -> bool:
    return _normalize_host(a) == _normalize_host(b)
