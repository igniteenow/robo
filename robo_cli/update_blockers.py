"""Windows: close what still runs from this install, so ``robo update`` can go on.

Windows keeps a running program's files locked. While the desktop app, a
dashboard or another ``robo`` terminal is open, the update cannot replace the
venv's files, so it used to stop with a list of process ids and leave the user
to find and end them. Most people cannot do that from a list of PIDs.

``robo update`` now says in plain words what is still open and offers to close
it: the desktop app is asked to quit first and reopened when the update is
done, everything else running from this install is stopped. It asks before it
closes anything (``--yes`` answers for the user), and it keeps refusing, as
before, when nobody can answer or when the update was started from inside one
of the programs it would have to close.

Everything that touches a process is behind the small ``_``-prefixed functions
at the bottom, and those do nothing off Windows, so the decisions above them
can be tested on any machine.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

logger = logging.getLogger(__name__)

Holder = tuple[int, str, str]  # (pid, process name, command line prefix), as the venv scan reports it

# How long the desktop app gets to quit by itself before it is stopped.
DESKTOP_QUIT_SECONDS = 8.0
# Stop, look again, stop what came back: a supervisor can respawn a child once.
CLOSE_ROUNDS = 3


@dataclass
class ClosePlan:
    """What is in the way, grouped the way a person would name it."""

    desktop_pids: list[int] = field(default_factory=list)  # every process of the desktop app
    desktop_mode: str | None = None  # "packaged" | "source": how to reopen it
    others: list[Holder] = field(default_factory=list)  # top-level holders outside the desktop app
    lines: list[str] = field(default_factory=list)  # one line per thing, for the question


@dataclass
class CloseOutcome:
    remaining: list[Holder]  # still holding the install after all that
    asked: bool = False  # the user was shown the list (or --yes answered)
    declined: bool = False  # ... and said no
    inside_robo: bool = False  # not offered: the update runs inside what it would close
    reopen_desktop: str | None = None  # the desktop app was closed; reopen it this way
    closed_others: bool = False  # something other than the desktop app was stopped


def _norm(path: object) -> str:
    try:
        return os.path.normcase(str(Path(str(path)).resolve()))
    except (OSError, ValueError):
        return os.path.normcase(str(path))


def _under(path: str, roots: Sequence[str]) -> bool:
    return any(path == root or path.startswith(root.rstrip("\\/") + os.sep) for root in roots)


def describe_holder(holder: Holder) -> str:
    """A holder in words: what the user would call the thing that is open."""
    pid, name, cmdline = holder
    low = f" {cmdline.lower()} "
    exe = name.lower()
    try:
        from robo_cli._scan_venv_blockers import _is_pausable_gateway

        if _is_pausable_gateway(cmdline):
            return f"the messaging gateway (PID {pid})"
    except Exception:
        pass
    if exe in {"openconsole.exe", "winpty-agent.exe", "conhost.exe"}:
        return f"a terminal opened by Robo (PID {pid})"
    if _is_backend(holder):
        return f"the Robo dashboard / background server (PID {pid})"
    if "robo_cli" in low or "tui_gateway" in low or exe.startswith("robo"):
        return f"a Robo terminal session (PID {pid})"
    return f"another program running on Robo's Python: {name} (PID {pid})"


def _is_backend(holder: Holder) -> bool:
    """A ``dashboard`` / ``serve`` process: what the desktop app runs as its backend."""
    low = f" {holder[2].lower()} "
    return " dashboard " in low or " serve " in low


def make_plan(
    holders: Sequence[Holder],
    *,
    desktop: dict[int, str],
    ancestors_of: Callable[[int], list[int] | None],
) -> ClosePlan:
    """Group *holders*: the desktop app as one thing, the rest by their top process.

    *desktop* maps the pid of every running process of this install's desktop
    app to how the app was started ("packaged" / "source"). A holder that
    descends from one of them belongs to the app: the app supervises its
    backend and starts it again when it is stopped, so the app itself has to
    close. A holder that descends from another holder is that holder's child
    (launcher and worker, a backend and its terminal) and is not listed twice.
    """
    plan = ClosePlan()
    holder_pids = {int(pid) for pid, _name, _cmd in holders}
    in_desktop = False
    for holder in holders:
        pid = int(holder[0])
        chain = ancestors_of(pid) or []
        if pid in desktop or any(anc in desktop for anc in chain):
            in_desktop = True
            continue
        if any(anc in holder_pids for anc in chain):
            continue
        plan.others.append(holder)
    if in_desktop:
        plan.desktop_pids = sorted(desktop)
        modes = set(desktop.values())
        plan.desktop_mode = "packaged" if "packaged" in modes else "source"
        plan.lines.append("the Robo desktop app (it reopens when the update is done)")
    plan.lines.extend(describe_holder(holder) for holder in plan.others)
    return plan


def _may_answer(args: object) -> tuple[bool, bool]:
    """(``--yes`` was given, a person can be asked on this terminal)."""
    assume_yes = bool(getattr(args, "yes", False))
    try:
        interactive = all(
            stream is not None and stream.isatty() for stream in (sys.stdin, sys.stdout)
        )
    except Exception:
        interactive = False
    return assume_yes, interactive


def can_offer(args: object) -> bool:
    """True when closing can be offered at all: someone, or ``--yes``, can say yes."""
    assume_yes, interactive = _may_answer(args)
    return assume_yes or interactive


def offer_to_close(
    holders: Sequence[Holder],
    args: object,
    *,
    redetect: Callable[[], list[Holder]],
    project_root: Path | None = None,
    venv_dir: Path | None = None,
    out: Callable[[str], None] = print,
    input_fn: Callable[[str], str] = input,
    sleep: Callable[[float], None] = time.sleep,
) -> CloseOutcome:
    """Offer to close *holders*; close them on a yes. Never raises.

    Returns what is still in the way. Nothing is touched when nobody can
    answer, when the answer is no, or when this update itself runs inside
    Robo (its desktop terminal, a chat's shell): closing that would cut the
    branch the update sits on.
    """
    holders = list(holders)
    outcome = CloseOutcome(remaining=holders)
    if not holders:
        return outcome
    try:
        assume_yes, interactive = _may_answer(args)
        if not (assume_yes or interactive):
            return outcome

        if project_root is None or venv_dir is None:
            from robo_cli import main as cli_main

            project_root = cli_main.PROJECT_ROOT if project_root is None else project_root
            venv_dir = cli_main._project_venv_dir() if venv_dir is None else venv_dir
        venv_root = _norm(venv_dir)
        desktop_roots = _desktop_roots(Path(project_root))
        if _inside_robo(venv_root, list(desktop_roots)):
            outcome.inside_robo = True
            return outcome

        plan = make_plan(holders, desktop=_desktop_processes(desktop_roots), ancestors_of=_ancestor_pids)
        if not plan.lines:
            return outcome

        out("")
        out("Robo is still open, and Windows cannot update files that are in use:")
        for line in plan.lines:
            out(f"    - {line}")
        out("  Chats are saved as you go. A reply that is being written right now, or a")
        out("  command one of them is running, stops with it.")
        outcome.asked = True
        if assume_yes:
            out("  Closing them to continue (--yes).")
        else:
            try:
                answer = input_fn("Close them and continue the update? [Y/n] ")
            except (EOFError, KeyboardInterrupt, OSError):
                answer = "n"
            if str(answer).strip().lower() not in {"", "y", "yes"}:
                outcome.declined = True
                return outcome

        announced = False
        remaining = holders
        for round_no in range(CLOSE_ROUNDS):
            if not remaining:
                break
            desktop = _desktop_processes(desktop_roots)
            current = make_plan(remaining, desktop=desktop, ancestors_of=_ancestor_pids)
            # The app owns what is left (its backend), or what was stopped came
            # back and the app is the only thing that could have restarted it
            # (the first look could not read the process tree): the app itself
            # has to close, or its backend returns within seconds.
            if desktop and (current.desktop_pids or (round_no > 0 and any(map(_is_backend, remaining)))):
                if outcome.reopen_desktop is None:
                    out("→ Closing the Robo desktop app...")
                    outcome.reopen_desktop = "packaged" if "packaged" in set(desktop.values()) else "source"
                _close_desktop_app(sorted(desktop), sleep=sleep)
                remaining = list(redetect())
                if not remaining:
                    break
                current = make_plan(
                    remaining, desktop=_desktop_processes(desktop_roots), ancestors_of=_ancestor_pids
                )
            targets = current.others or remaining
            if not announced:
                other = "other " if outcome.reopen_desktop else ""
                out(f"→ Stopping {len(targets)} {other}Robo process(es)...")
                announced = True
            outcome.closed_others = True
            for pid, _name, _cmd in targets:
                _kill_tree(int(pid))
            sleep(1.0)
            remaining = list(redetect())

        outcome.remaining = remaining
        if not remaining:
            out("  ✓ Nothing else is using this install")
        return outcome
    except Exception as exc:  # the old refusal is always a safe answer
        logger.debug("Offering to close the update's blockers failed: %s", exc)
        try:
            outcome.remaining = list(redetect())
        except Exception:
            outcome.remaining = holders
        return outcome


# ---------------------------------------------------------------------------
# Process access. Windows only: each of these is a no-op anywhere else.
# ---------------------------------------------------------------------------


def _on_windows() -> bool:
    # The real platform, not ``robo_cli.main._is_windows`` (tests patch that
    # one to walk the Windows branches on Linux): nothing below may ever stop
    # a process on a machine where the pids came from a test.
    return sys.platform == "win32"


def _desktop_roots(project_root: Path) -> dict[str, str]:
    """Where this install's desktop app runs from -> how it was started."""
    roots: dict[str, str] = {}
    try:
        from robo_cli import main as cli_main

        desktop_dir = Path(project_root) / "apps" / "desktop"
        for source_mode, mode in ((False, "packaged"), (True, "source")):
            for root in cli_main._desktop_build_lock_roots(desktop_dir, Path(project_root), source_mode=source_mode):
                roots[_norm(root)] = mode
    except Exception as exc:
        logger.debug("Could not resolve the desktop app's folders: %s", exc)
    return roots


def _desktop_processes(roots: dict[str, str]) -> dict[int, str]:
    """pid -> mode for every running process of this install's desktop app."""
    if not roots or not _on_windows():
        return {}
    try:
        import psutil
    except Exception:
        return {}
    found: dict[int, str] = {}
    me = os.getpid()
    try:
        for proc in psutil.process_iter(["pid", "exe"]):
            try:
                pid, exe = proc.info.get("pid"), proc.info.get("exe")
            except Exception:
                continue
            if not exe or pid is None or int(pid) == me:
                continue
            exe_norm = _norm(exe)
            for root, mode in roots.items():
                if _under(exe_norm, [root]):
                    found[int(pid)] = mode
                    break
    except Exception as exc:
        logger.debug("Could not list the desktop app's processes: %s", exc)
    return found


def _ancestor_pids(pid: int) -> list[int] | None:
    """Pids of *pid*'s ancestors, nearest first; ``None`` when they cannot be read."""
    if not _on_windows():
        return None
    try:
        import psutil

        return [int(anc.pid) for anc in psutil.Process(int(pid)).parents()]
    except Exception:
        return None


def nested_in_robo(
    ancestors: Sequence[tuple[str, str]], venv_root: str, desktop_roots: Sequence[str]
) -> bool:
    """True when *ancestors* show this update running inside something it would close.

    *ancestors* are ``(normalized exe path, lowercased command line)`` of this
    process's ancestors, nearest first. The nearest ones are this command's
    own launcher (``robo.exe``, the venv's ``python.exe`` redirector, the
    desktop's update window that runs the update as its child) and are
    skipped. Any Robo process further up means the update was typed into the
    desktop app's terminal, a chat's shell or a dashboard terminal: closing
    "everything else" there would close the window the update runs in.
    """
    own_launcher = True
    for exe, cmdline in ancestors:
        in_venv = bool(exe) and _under(exe, [venv_root])
        if own_launcher and (
            (in_venv and os.path.basename(exe).startswith(("robo", "python")))
            or "update_window.py" in cmdline
        ):
            continue
        own_launcher = False
        if in_venv or (exe and _under(exe, list(desktop_roots))):
            return True
        if "robo_cli" in cmdline or "tui_gateway" in cmdline:
            return True
    return False


def _inside_robo(venv_root: str, desktop_roots: Sequence[str]) -> bool:
    """``nested_in_robo`` for this process. Unreadable tree: yes (closing nothing is safe)."""
    if not _on_windows():
        return False
    try:
        import psutil

        parents = psutil.Process().parents()
    except Exception:
        return True
    ancestors: list[tuple[str, str]] = []
    for anc in parents:
        try:
            exe = _norm(anc.exe() or "")
        except Exception:
            exe = ""
        try:
            cmdline = " ".join(anc.cmdline() or []).lower()
        except Exception:
            cmdline = ""
        ancestors.append((exe, cmdline))
    return nested_in_robo(ancestors, venv_root, desktop_roots)


def _close_desktop_app(pids: Sequence[int], *, sleep: Callable[[float], None] = time.sleep) -> None:
    """Ask the desktop app to quit; stop what is left after a moment.

    ``taskkill`` without ``/F`` posts a close request to the app's windows,
    the same as clicking X: the app saves its state and stops its own backend.
    If it is still there after ``DESKTOP_QUIT_SECONDS`` (it asks "keep
    running?" while a reply is being written), its processes are stopped.
    """
    if not pids or not _on_windows():
        return
    try:
        import psutil
    except Exception:
        return
    procs = []
    for pid in pids:
        try:
            procs.append(psutil.Process(int(pid)))
        except Exception:
            continue
    if not procs:
        return
    own = {int(proc.pid) for proc in procs}
    try:
        from robo_cli._subprocess_compat import windows_hide_flags

        flags = windows_hide_flags()
    except Exception:
        flags = 0
    for proc in procs:
        try:
            parent = proc.ppid()
        except Exception:
            parent = None
        if parent in own:
            continue  # a renderer / helper: the main process closes it
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid)],
                capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=10,
                creationflags=flags,
            )
        except Exception as exc:
            logger.debug("Could not ask desktop process %s to close: %s", proc.pid, exc)
    try:
        _gone, alive = psutil.wait_procs(procs, timeout=DESKTOP_QUIT_SECONDS)
    except Exception:
        alive = procs
    for proc in alive:
        try:
            proc.kill()
        except Exception:
            continue
    if alive:
        try:
            psutil.wait_procs(alive, timeout=5)
        except Exception:
            pass
    sleep(0.5)  # let Windows release the file handles


def _kill_tree(pid: int) -> None:
    """Stop *pid* and everything it started. Already gone is fine."""
    if not _on_windows():
        return
    try:
        from gateway.status import terminate_pid

        terminate_pid(int(pid), force=True)
    except Exception as exc:
        logger.debug("Could not stop process %s: %s", pid, exc)
