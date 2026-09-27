"""The window Robo shows while the desktop app's "Update now" installs an update.

On Windows the desktop app can't update itself while it runs: the app, its
backend and the venv's launchers are the files the update replaces. So "Update
now" quits the app and hands the update to this window. The window runs
``robo update`` as a hidden child process, turns the step lines it prints into
a progress bar with plain-language status, and ends on a finished screen (the
update reopens Robo itself) or an error screen with the details and a way
forward.

The desktop app starts this file with the venv's *base* interpreter and
``-I -S``, so the window holds no file inside the venv the update may rebuild,
and it imports only the standard library. Without a usable Tk it falls back to
running the same update in a console window, as before.

Usage::

    pythonw.exe -I -S update_window.py --python <venv python.exe> --root <checkout>
        --reopen packaged|source [--branch <branch>] [--wait-pid <app pid>]
"""

from __future__ import annotations

import argparse
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # no Tk in this Python: main() falls back to a console
    tk = None
    ttk = None

# Keep in sync with UPDATE_HANDOFF_ENV in robo_cli/update_cmd.py: the update
# waits for these pids (the desktop app) to exit before it touches anything.
UPDATE_HANDOFF_ENV = "ROBO_UPDATE_HANDOFF_PIDS"

# Same exit code robo_cli.update_lock.UPDATE_EXIT_CONCURRENT uses.
EXIT_CONCURRENT = 2

_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_CONSOLE = 0x00000010
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000

LOG_NAME = "desktop-update.log"


# ---------------------------------------------------------------------------
# Progress: what `robo update` prints -> where the update is
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Phase:
    key: str
    label: str
    start: float  # share of the bar done when this phase begins


PHASES: tuple[Phase, ...] = (
    Phase("waiting", "Waiting for Robo to close…", 0.00),
    Phase("preparing", "Getting ready…", 0.03),
    Phase("checking", "Checking for the latest version…", 0.07),
    Phase("downloading", "Downloading the update…", 0.11),
    Phase("python", "Installing Python components…", 0.18),
    Phase("node", "Installing app components…", 0.50),
    Phase("web", "Building the web dashboard…", 0.60),
    Phase("desktop", "Building the desktop app…", 0.68),
    Phase("finishing", "Finishing up…", 0.88),
    Phase("reopening", "Starting Robo…", 0.96),
)

_PHASE_INDEX = {phase.key: index for index, phase in enumerate(PHASES)}

# First match wins; a line only ever moves the bar forward.
_STEP_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), key)
    for pattern, key in (
        (r"^Updating Robo", "preparing"),
        (r"^◆ (Pre-update|Creating pre-update)", "preparing"),
        (r"^→ Stopping .*gateway", "preparing"),
        (r"^→ Fetching (updates|from origin|from upstream)", "checking"),
        (r"^→ Found \d+ new commit", "downloading"),
        (r"^→ (Pulling|Fetching upstream|Syncing fork|Local changes detected|Downloading latest|Extracting)", "downloading"),
        (r"^→ (Updating Python dependencies|Repairing Python dependencies|Finishing the dependency install|Recreating virtual environment)", "python"),
        (r"^→ Refreshing .*(lazy backend|memory provider)", "python"),
        (r"^→ Updating Node\.js dependencies", "node"),
        (r"^→ Building web UI", "web"),
        (r"^→ Checking if desktop app needs rebuilding", "desktop"),
        (r"^✓ (Code updated|Update complete|Already up to date|Dependencies repaired)", "finishing"),
        (r"^→ (Syncing bundled skills|Checking configuration)", "finishing"),
        (r"^→ Reopening Robo", "reopening"),
    )
)

# Steps worth mentioning on the finished screen: the update went through, but
# part of Robo didn't refresh.
_WARNING_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), note)
    for pattern, note in (
        (r"Update partially complete", "Some app components didn't update."),
        (r"Web UI build failed", "The web dashboard didn't rebuild."),
        (r"Desktop build failed", "The desktop app didn't rebuild."),
    )
)

# The update's own word on what happened to the user's code after a failure.
_REASSURANCE = re.compile(r"^(Your code was not changed|Your checkout is on the new version)")

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_STEP_GLYPHS = ("→", "◆", "✓", "⚠", "✗")
_DETAIL_MAX = 80
_REASON_MAX = 240

# Seconds for the bar to cover most of a phase it has no news from. Long steps
# (dependency installs, the desktop build) keep creeping instead of freezing.
_CREEP_SECONDS = 40.0
_CREEP_SHARE = 0.9


def clean_line(raw: str) -> str:
    """One output line as the user would read it: no colour codes, no redraws."""
    text = _ANSI.sub("", raw)
    if "\r" in text:
        parts = [part for part in text.split("\r") if part.strip()]
        text = parts[-1] if parts else ""
    return text.strip()


def _step_text(line: str, limit: int = _DETAIL_MAX) -> str:
    """``→ Pulling updates...`` -> ``Pulling updates…``."""
    text = line.lstrip("".join(_STEP_GLYPHS)).strip()
    if text.endswith("..."):
        text = text[:-3].rstrip() + "…"
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


@dataclass
class UpdateProgress:
    """Follows ``robo update``'s output and says how far along it is.

    Pure: feed it lines and ask it for a fraction at a given time.
    """

    clock: Callable[[], float] = time.monotonic
    phase_index: int = 0
    detail: str = ""
    errors: list[str] = field(default_factory=list)
    reassurance: str = ""
    notes: list[str] = field(default_factory=list)
    already_current: bool = False
    reopen_failed: bool = False
    tail: deque = field(default_factory=lambda: deque(maxlen=12))

    def __post_init__(self) -> None:
        self.phase_started = self.clock()

    @property
    def phase(self) -> Phase:
        return PHASES[self.phase_index]

    @property
    def label(self) -> str:
        return self.phase.label

    def feed(self, raw: str) -> None:
        line = clean_line(raw)
        if not line:
            return
        self.tail.append(line)

        for pattern, key in _STEP_RULES:
            if pattern.search(line):
                index = _PHASE_INDEX[key]
                if index > self.phase_index:
                    self.phase_index = index
                    self.phase_started = self.clock()
                break

        if line.startswith(_STEP_GLYPHS):
            self.detail = _step_text(line)
        if line.startswith("✗"):
            self.errors.append(_step_text(line, _REASON_MAX))
        if _REASSURANCE.match(line):
            self.reassurance = line
        if line.startswith("✓ Already up to date"):
            self.already_current = True
        if line.startswith("Couldn't reopen Robo"):
            self.reopen_failed = True
        for pattern, note in _WARNING_RULES:
            if pattern.search(line) and note not in self.notes:
                self.notes.append(note)

    def fraction(self, now: float | None = None) -> float:
        """Share of the bar to fill: the phase's start plus a slow creep."""
        start = self.phase.start
        end = PHASES[self.phase_index + 1].start if self.phase_index + 1 < len(PHASES) else 1.0
        elapsed = max(0.0, (self.clock() if now is None else now) - self.phase_started)
        creep = _CREEP_SHARE * (1.0 - math.exp(-elapsed / _CREEP_SECONDS))
        return min(1.0, start + (end - start) * creep)

    def failure(self, returncode: int) -> tuple[str, str]:
        """Headline and explanation for an update that exited with *returncode*."""
        if returncode == EXIT_CONCURRENT and any("already running" in error for error in self.errors):
            return (
                "Another update is already running",
                "Wait for it to finish, then try again.",
            )
        label = self.phase.label.rstrip("…")
        doing = label[0].lower() + label[1:] if self.phase_index > 0 else "starting the update"
        reasons = self.errors[:3] or [line for line in self.tail if line.startswith("⚠")][-2:]
        explanation = f"Something went wrong while {doing}."
        if reasons:
            explanation += "\n\n" + "\n".join(reasons)
        if self.reassurance:
            explanation += "\n" + self.reassurance
        return "The update didn't finish", explanation


# ---------------------------------------------------------------------------
# Running the update
# ---------------------------------------------------------------------------


def build_update_command(python: str, branch: str | None, reopen: str) -> list[str]:
    """The ``robo update`` the window runs: the same one "Update now" always ran."""
    branch_args = ["--branch", branch] if branch and branch != "main" else []
    return [python, "-m", "robo_cli.main", "update", "--yes", *branch_args, "--reopen-desktop", reopen]


def build_open_command(python: str, reopen: str) -> list[str]:
    """``robo desktop`` for the "Open Robo" button after a failed update."""
    return [python, "-m", "robo_cli.main", "desktop", *(["--source"] if reopen == "source" else [])]


def update_env(base: dict[str, str], wait_pid: int | None) -> dict[str, str]:
    """Environment for the update child: UTF-8 output, no prompts, who to wait for."""
    env = dict(base)
    env.pop(UPDATE_HANDOFF_ENV, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    # Its console is hidden: a git credential prompt there would wait forever.
    # Failing says why instead (Git Credential Manager's own dialog still works).
    env["GIT_TERMINAL_PROMPT"] = "0"
    if wait_pid:
        env[UPDATE_HANDOFF_ENV] = str(wait_pid)
    return env


def _hidden_child_flags() -> tuple[int, ...]:
    """Creation flags to try, in order: a hidden console, outside any job if allowed."""
    if sys.platform != "win32":
        return (0,)
    return (_CREATE_NO_WINDOW | _CREATE_BREAKAWAY_FROM_JOB, _CREATE_NO_WINDOW)


class UpdateRunner:
    """Runs the update in the background and reports its output on a queue.

    Events are ``("line", text)`` and, once, ``("exit", returncode)``. The exit
    is reported when the process ends, not when its output closes: anything
    the update leaves running (the reopened app, a restarted gateway) may keep
    the pipe open.
    """

    def __init__(self, command: list[str], *, cwd: str, env: dict[str, str]):
        self.command = command
        self.cwd = cwd
        self.env = env
        self.events: queue.Queue = queue.Queue()
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        error: OSError | None = None
        for flags in _hidden_child_flags():
            try:
                # stdin is a pipe closed straight away, not DEVNULL: Windows
                # reports NUL as a terminal, and the update would think it
                # has someone to ask.
                self.process = subprocess.Popen(
                    self.command,
                    cwd=self.cwd,
                    env=self.env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                )
                break
            except OSError as exc:  # e.g. a job that refuses breakaway
                error = exc
        else:
            assert error is not None
            raise error
        self.process.stdin.close()
        reader = threading.Thread(target=self._read, daemon=True)
        reader.start()
        threading.Thread(target=self._wait, args=(reader,), daemon=True).start()

    def _read(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for raw in iter(self.process.stdout.readline, b""):
            self.events.put(("line", raw.decode("utf-8", errors="replace").rstrip("\r\n")))

    def _wait(self, reader: threading.Thread) -> None:
        assert self.process is not None
        returncode = self.process.wait()
        reader.join(timeout=1.5)
        self.events.put(("exit", returncode))

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self) -> None:
        """End the update and everything it started (the user asked to)."""
        if not self.running:
            return
        assert self.process is not None
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(self.process.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
                check=False,
            )
        else:
            self.process.kill()


def run_update_in_console(command: list[str], *, cwd: str, env: dict[str, str]) -> bool:
    """Fallback without Tk: run the same update in a console window."""
    if sys.platform != "win32":
        return False
    for flags in (_CREATE_NEW_CONSOLE | _CREATE_BREAKAWAY_FROM_JOB, _CREATE_NEW_CONSOLE):
        try:
            subprocess.Popen(command, cwd=cwd, env=env, creationflags=flags)
            return True
        except OSError:
            continue
    return False


def open_robo(python: str, reopen: str, cwd: str) -> bool:
    """Start the desktop app without tying it to this window."""
    flags = 0
    if sys.platform == "win32":
        flags = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(
            build_open_command(python, reopen),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        return True
    except OSError:
        return False


def log_path(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    home = env.get("ROBO_HOME") or str(Path.home() / ".robo")
    return Path(home) / "logs" / LOG_NAME


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

# Robo's navy / ember palette (robo_cli/skin_engine.py, "robo" skin).
COLORS = {
    "bg": "#0E1437",
    "surface": "#141A45",
    "raised": "#1C2358",
    "border": "#2A2C73",
    "title": "#FFE9D6",
    "text": "#E6E3F5",
    "dim": "#8C91BD",
    "accent": "#EF8A22",
    "accent_hover": "#F59A3A",
    "accent_text": "#0E1437",
    "ok": "#3FBF7F",
    "bad": "#F0626E",
}

SUCCESS_CLOSE_MS = 4000
_TICK_MS = 100


def _prepare_process_for_ui() -> None:
    """Sharp text on high-DPI screens and Robo's own taskbar icon (Windows)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("IgniteeNow.Robo.Updater")
    except Exception:
        pass


class UpdateWindow:
    """The updater window: progress while it runs, then done or what went wrong."""

    def __init__(self, root, *, python: str, checkout: str, reopen: str, branch: str | None, env: dict[str, str]):
        self.root = root
        self.python = python
        self.checkout = checkout
        self.reopen = reopen
        self.branch = branch
        self.env = env
        self.runner: UpdateRunner | None = None
        self.progress = UpdateProgress()
        self.log_lines: list[str] = []
        self.log_file = log_path(env)
        self.details_open = False
        self.state = "running"
        self.stopped = False

        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self._fonts()
        self._style()
        self._layout()

        root.title("Robo Update")
        root.configure(bg=COLORS["bg"])
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.bind("<Return>", lambda _e: self._primary_action())
        root.bind("<Escape>", lambda _e: self._on_close())
        self._set_icon()
        self._center()
        # Come up in front of the app that is closing, then behave normally.
        root.attributes("-topmost", True)
        root.after(1500, lambda: root.attributes("-topmost", False))
        root.focus_force()

    # -- construction -------------------------------------------------------

    def px(self, value: float) -> int:
        return int(round(value * self.scale))

    def _fonts(self) -> None:
        from tkinter import font as tkfont

        families = set(tkfont.families(self.root))
        base = "Segoe UI" if "Segoe UI" in families else tkfont.nametofont("TkDefaultFont").actual("family")
        strong = "Segoe UI Semibold" if "Segoe UI Semibold" in families else base
        mono = "Consolas" if "Consolas" in families else tkfont.nametofont("TkFixedFont").actual("family")
        self.font_title = (strong, 14)
        self.font_body = (base, 10)
        self.font_small = (base, 9)
        self.font_link = (base, 9, "underline")
        self.font_button = (strong, 10)
        self.font_mono = (mono, 9)

    def _style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        c = COLORS
        style.configure(
            "Robo.Horizontal.TProgressbar",
            troughcolor=c["raised"], background=c["accent"], bordercolor=c["raised"],
            lightcolor=c["accent"], darkcolor=c["accent"], thickness=self.px(8),
        )
        for name, color in (("Ok", c["ok"]), ("Bad", c["bad"])):
            style.configure(
                f"Robo{name}.Horizontal.TProgressbar",
                troughcolor=c["raised"], background=color, bordercolor=c["raised"],
                lightcolor=color, darkcolor=color, thickness=self.px(8),
            )
        style.configure(
            "Robo.Vertical.TScrollbar", background=c["raised"], troughcolor=c["surface"],
            bordercolor=c["surface"], arrowcolor=c["dim"], lightcolor=c["raised"], darkcolor=c["raised"],
        )
        style.map("Robo.Vertical.TScrollbar", background=[("active", c["border"])])
        padding = (self.px(16), self.px(7))
        style.configure(
            "Robo.Primary.TButton", font=self.font_button, padding=padding,
            background=c["accent"], foreground=c["accent_text"], bordercolor=c["accent"],
            lightcolor=c["accent"], darkcolor=c["accent"], focuscolor=c["accent"], relief="flat",
        )
        style.map(
            "Robo.Primary.TButton",
            background=[("pressed", c["accent"]), ("active", c["accent_hover"])],
            lightcolor=[("active", c["accent_hover"])], darkcolor=[("active", c["accent_hover"])],
        )
        style.configure(
            "Robo.Secondary.TButton", font=self.font_button, padding=padding,
            background=c["raised"], foreground=c["text"], bordercolor=c["border"],
            lightcolor=c["raised"], darkcolor=c["raised"], focuscolor=c["raised"], relief="flat",
        )
        style.map(
            "Robo.Secondary.TButton",
            background=[("pressed", c["raised"]), ("active", c["border"])],
            lightcolor=[("active", c["border"])], darkcolor=[("active", c["border"])],
        )

    def _label(self, parent, *, font, fg, **kwargs):
        return tk.Label(parent, font=font, fg=fg, bg=COLORS["bg"], anchor="w", justify="left", **kwargs)

    def _link(self, parent, text, command):
        link = tk.Label(parent, text=text, font=self.font_link, fg=COLORS["dim"], bg=COLORS["bg"], cursor="hand2")
        link.bind("<Button-1>", lambda _e: command())
        link.bind("<Enter>", lambda _e: link.configure(fg=COLORS["text"]))
        link.bind("<Leave>", lambda _e: link.configure(fg=COLORS["dim"]))
        return link

    def _layout(self) -> None:
        c = COLORS
        width = self.px(470)
        outer = tk.Frame(self.root, bg=c["bg"], padx=self.px(24), pady=self.px(22))
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=c["bg"])
        header.pack(fill="x")
        self.logo = self._load_logo(self.px(52))
        if self.logo is not None:
            tk.Label(header, image=self.logo, bg=c["bg"]).pack(side="left", padx=(0, self.px(16)))
        text = tk.Frame(header, bg=c["bg"])
        text.pack(side="left", fill="x", expand=True)
        self.title_label = self._label(text, text="Updating Robo", font=self.font_title, fg=c["title"])
        self.title_label.pack(fill="x")
        self.status_label = self._label(
            text, text=self.progress.label, font=self.font_body, fg=c["text"],
            wraplength=width - self.px(70),
        )
        self.status_label.pack(fill="x", pady=(self.px(2), 0))

        self.bar = ttk.Progressbar(
            outer, style="Robo.Horizontal.TProgressbar", mode="determinate",
            maximum=1000, length=width,
        )
        self.bar.pack(fill="x", pady=(self.px(20), 0))
        self.detail_label = self._label(outer, text="", font=self.font_small, fg=c["dim"], wraplength=width)
        self.detail_label.pack(fill="x", pady=(self.px(8), 0))

        footer = tk.Frame(outer, bg=c["bg"])
        footer.pack(fill="x", pady=(self.px(18), 0))
        self.details_link = self._link(footer, "Show details", self._toggle_details)
        self.details_link.pack(side="left")
        self.buttons = tk.Frame(footer, bg=c["bg"])
        self.buttons.pack(side="right")

        self.details = tk.Frame(outer, bg=c["bg"])
        box = tk.Frame(self.details, bg=c["border"], padx=1, pady=1)
        box.pack(fill="both", expand=True, pady=(self.px(14), 0))
        self.log_text = tk.Text(
            box, height=14, width=1, wrap="word", font=self.font_mono, bg=c["surface"], fg=c["text"],
            insertbackground=c["text"], relief="flat", borderwidth=0, padx=self.px(10), pady=self.px(8),
            highlightthickness=0,
        )
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.log_text.yview, style="Robo.Vertical.TScrollbar")
        self.log_text.configure(yscrollcommand=scroll.set, state="disabled")
        scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        below = tk.Frame(self.details, bg=c["bg"])
        below.pack(fill="x", pady=(self.px(6), 0))
        self.copy_link = self._link(below, "Copy details", self._copy_details)
        self.copy_link.pack(side="right", anchor="n", padx=(self.px(12), 0))
        self._label(
            below, text=f"Log file: {self.log_file}", font=self.font_small, fg=c["dim"],
            wraplength=width - self.px(100),
        ).pack(side="left", fill="x", expand=True)

        self._set_buttons([])

    def _load_logo(self, size: int):
        icon = Path(self.checkout) / "apps" / "desktop" / "assets" / "icon.png"
        try:
            image = tk.PhotoImage(file=str(icon))
            factor = max(1, round(image.width() / size))
            return image.subsample(factor, factor)
        except Exception:
            return None

    def _set_icon(self) -> None:
        assets = Path(self.checkout) / "apps" / "desktop" / "assets"
        try:
            if sys.platform == "win32":
                self.root.iconbitmap(default=str(assets / "icon.ico"))
            elif self.logo is not None:
                self.root.iconphoto(True, self.logo)
        except Exception:
            pass

    def _center(self) -> None:
        self.root.update_idletasks()
        width, height = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = (self.root.winfo_screenwidth() - width) // 2
        y = max(0, (self.root.winfo_screenheight() - height) // 3)
        self.root.geometry(f"+{x}+{y}")

    def _set_buttons(self, specs: list[tuple[str, Callable[[], None], bool]]) -> None:
        for child in self.buttons.winfo_children():
            child.destroy()
        self._primary = None
        for text, command, primary in specs:
            style = "Robo.Primary.TButton" if primary else "Robo.Secondary.TButton"
            ttk.Button(self.buttons, text=text, command=command, style=style, cursor="hand2").pack(
                side="left", padx=(self.px(8), 0)
            )
            if primary:
                self._primary = command

    # -- running ------------------------------------------------------------

    def start(self, *, wait_pid: int | None) -> None:
        self.state = "running"
        self.stopped = False
        # With nobody to wait for (a retry: the app is already closed) the
        # update starts straight away.
        self.progress = UpdateProgress(phase_index=0 if wait_pid else _PHASE_INDEX["preparing"])
        self.title_label.configure(text="Updating Robo")
        self.status_label.configure(text=self.progress.label)
        self.detail_label.configure(text="")
        self.bar.configure(style="Robo.Horizontal.TProgressbar")
        self._set_buttons([])
        command = build_update_command(self.python, self.branch, self.reopen)
        self._append_log("$ robo " + " ".join(command[3:]))
        self.runner = UpdateRunner(command, cwd=self.checkout, env=update_env(self.env, wait_pid))
        try:
            self.runner.start()
        except OSError as exc:
            line = f"✗ Couldn't start the update: {exc}"
            self.progress.feed(line)
            self._append_log(line)
            self._show_failure(-1)
            return
        self.root.after(_TICK_MS, self._tick)

    def _tick(self) -> None:
        runner = self.runner
        if runner is None:
            return
        finished = self._drain(runner)
        if finished is None:
            try:
                self.status_label.configure(text=self.progress.label)
                self.detail_label.configure(text=self.progress.detail)
                self.bar["value"] = int(self.progress.fraction() * 1000)
            except Exception:
                pass  # a display hiccup; the next tick redraws

        if finished is None:
            self.root.after(_TICK_MS, self._tick)
        elif finished == 0:
            self._show_success()
        else:
            self._show_failure(finished)

    def _drain(self, runner: UpdateRunner) -> int | None:
        """Take in everything the update printed since the last tick."""
        finished = None
        while True:
            try:
                kind, value = runner.events.get_nowait()
            except queue.Empty:
                return finished
            if kind != "line":
                finished = value
                continue
            # One odd line must never stall the window or lose the exit.
            try:
                self.progress.feed(value)
                self._append_log(value)
            except Exception:
                pass

    def _show_success(self) -> None:
        self.state = "done"
        self.bar.configure(style="RoboOk.Horizontal.TProgressbar")
        self.bar["value"] = 1000
        if self.progress.already_current:
            title = "Robo is already up to date"
        else:
            title = "Robo is up to date"
        if self.progress.reopen_failed:
            status = "The update is installed, but Robo didn't start by itself."
            self._set_buttons([("Close", self._close, False), ("Open Robo", self._open_robo, True)])
        elif self.progress.notes:
            status = "The update is installed. " + " ".join(self.progress.notes) + " See details."
            self._set_buttons([("Close", self._close, True)])
        else:
            status = "Update installed. Robo is starting…"
            self._set_buttons([("Close", self._close, True)])
            self.root.after(SUCCESS_CLOSE_MS, self._close)
        self.title_label.configure(text=title)
        self.status_label.configure(text=status)
        self.detail_label.configure(text="")
        self._write_log()

    def _show_failure(self, returncode: int) -> None:
        self.state = "failed"
        if self.stopped:
            headline = "The update was stopped"
            explanation = "Robo may not start until an update finishes. Choose Try again to finish it now."
        else:
            headline, explanation = self.progress.failure(returncode)
        self.bar.configure(style="RoboBad.Horizontal.TProgressbar")
        self.title_label.configure(text=headline)
        self.status_label.configure(text=explanation)
        self.detail_label.configure(text="")
        self._set_buttons([
            ("Close", self._close, False),
            ("Open Robo", self._open_robo, False),
            ("Try again", self._retry, True),
        ])
        self._write_log()

    # -- actions --------------------------------------------------------------

    def _primary_action(self) -> None:
        if self._primary is not None:
            self._primary()

    def _retry(self) -> None:
        self._append_log("")
        self._append_log("— Trying again —")
        # The app is closed by now, so there is nobody left to wait for.
        self.start(wait_pid=None)

    def _open_robo(self) -> None:
        open_robo(self.python, self.reopen, self.checkout)
        self._close()

    def _on_close(self) -> None:
        if self.state == "running" and self.runner is not None and self.runner.running:
            from tkinter import messagebox

            if messagebox.askyesno(
                "Stop the update?",
                "Robo is still updating. Stopping now can leave Robo unable to start "
                "until an update finishes.\n\nStop the update anyway?",
                icon="warning",
                default="no",
                parent=self.root,
            ):
                self._stop()
            return
        self._close()

    def _stop(self) -> None:
        if self.runner is None or not self.runner.running:
            return
        self.stopped = True
        self._append_log("— Update stopped —")
        self.runner.stop()

    def _close(self) -> None:
        self._write_log()
        self.root.destroy()

    def _toggle_details(self) -> None:
        self.details_open = not self.details_open
        if self.details_open:
            self.details.pack(fill="both", expand=True)
            self.details_link.configure(text="Hide details")
            self.log_text.see("end")
        else:
            self.details.pack_forget()
            self.details_link.configure(text="Show details")

    def _copy_details(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(self.log_lines))
        self.copy_link.configure(text="Copied")
        self.root.after(1500, lambda: self.copy_link.configure(text="Copy details"))

    def _append_log(self, line: str) -> None:
        self.log_lines.append(line)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.configure(state="disabled")
        if self.details_open:
            self.log_text.see("end")

    def _write_log(self) -> None:
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self.log_file.write_text("\n".join(self.log_lines) + "\n", encoding="utf-8")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install a Robo update with a progress window.")
    parser.add_argument("--python", required=True, help="The venv interpreter that runs `robo update`.")
    parser.add_argument("--root", required=True, help="The Robo checkout to update.")
    parser.add_argument("--reopen", choices=("packaged", "source"), default="packaged")
    parser.add_argument("--branch", default=None)
    parser.add_argument("--wait-pid", type=int, default=None, help="Wait for this process (the app) to exit.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    env = dict(os.environ)
    command = build_update_command(args.python, args.branch, args.reopen)

    root = None
    if tk is not None:
        _prepare_process_for_ui()
        try:
            root = tk.Tk()
        except Exception:
            root = None
    if root is None:
        # No usable Tk: the update still runs, in a console window.
        launched = run_update_in_console(command, cwd=args.root, env=update_env(env, args.wait_pid))
        return 0 if launched else 1

    try:
        window = UpdateWindow(
            root, python=args.python, checkout=args.root, reopen=args.reopen, branch=args.branch, env=env,
        )
    except Exception:
        # The window couldn't be built: the update still has to run.
        try:
            root.destroy()
        except Exception:
            pass
        launched = run_update_in_console(command, cwd=args.root, env=update_env(env, args.wait_pid))
        return 0 if launched else 1

    try:
        window.start(wait_pid=args.wait_pid)
        root.mainloop()
    except Exception:
        if window.runner is None or window.runner.process is None:
            launched = run_update_in_console(command, cwd=args.root, env=update_env(env, args.wait_pid))
            return 0 if launched else 1
    # Non-zero only when no update was started: the desktop app then starts
    # one in a console instead.
    return 0


if __name__ == "__main__":
    sys.exit(main())
