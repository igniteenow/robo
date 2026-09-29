"""`robo dashboard` keeps serving after the terminal that started it closes.

An interactive launch hands the server to a detached child (own session, no
inherited stdio, output in ``logs/dashboard-stdio.log``); every supervised or
programmatic launch — ``robo serve``, the Desktop app, containers, services,
pipes — keeps the foreground behaviour. See robo_cli/dashboard_background.py.
"""

from __future__ import annotations

import os
import sys
import textwrap
import types

import pytest

from robo_cli import dashboard_background as bg


class _Tty:
    def __init__(self, tty: bool):
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _args(**over):
    base = dict(
        host="127.0.0.1", port=9119, no_open=True, open_profile="",
        isolated=False, foreground=False, status=False, stop=False,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def _decide(args=None, *, headless=False, env=None, tty=True, container=False):
    return bg.should_run_in_background(
        args or _args(),
        headless=headless,
        env=env if env is not None else {},
        stdin=_Tty(tty),
        stdout=_Tty(tty),
        in_container=container,
    )


# ── who detaches ──────────────────────────────────────────────────────────


def test_interactive_dashboard_runs_in_background():
    assert _decide() is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"headless": True},                          # `robo serve` (Desktop backend)
        {"env": {"ROBO_DESKTOP": "1"}},              # spawned by the Desktop app
        {"tty": False},                              # systemd / Scheduled Task / pipe / CI
        {"container": True},                         # Docker / s6 supervise it
        {"args": _args(foreground=True)},            # explicit opt-out
    ],
)
def test_supervised_and_programmatic_launches_stay_in_foreground(kwargs):
    assert _decide(**kwargs) is False


def test_child_argv_runs_the_same_dashboard_attached_and_never_redetaches():
    argv = bg.build_background_argv(
        _args(host="0.0.0.0", port=9200, isolated=True, open_profile="work"),
        profile_name="default",
        python="/py",
    )
    assert argv[:4] == ["/py", "-m", "robo_cli.main", "dashboard"]
    assert argv[4:6] == ["-p", "default"]
    rest = argv[6:]
    assert rest[rest.index("--host") + 1] == "0.0.0.0"
    assert rest[rest.index("--port") + 1] == "9200"
    for flag in ("--foreground", "--no-open", "--skip-build", "--isolated"):
        assert flag in rest
    assert rest[rest.index("--open-profile") + 1] == "work"


def test_child_argv_is_found_by_status_and_stop():
    """--status/--stop match cmdlines; the child's must parse as this bind."""
    from robo_cli.main import _parse_dashboard_runtime

    argv = bg.build_background_argv(
        _args(host="0.0.0.0", port=9200), profile_name="default", python="python"
    )
    assert _parse_dashboard_runtime(" ".join(argv)) == ("dashboard", "0.0.0.0", 9200)


def test_custom_home_is_not_pinned_to_a_named_profile():
    argv = bg.build_background_argv(_args(), profile_name="custom", python="py")
    assert "-p" not in argv


def test_parser_accepts_foreground():
    import argparse

    from robo_cli.subcommands.dashboard import build_dashboard_parser

    parser = argparse.ArgumentParser()
    build_dashboard_parser(parser.add_subparsers(dest="cmd"), cmd_dashboard=lambda a: None)
    assert parser.parse_args(["dashboard", "--foreground"]).foreground is True
    assert parser.parse_args(["dashboard"]).foreground is False


# ── waiting for the child ─────────────────────────────────────────────────


class _Proc:
    def __init__(self, code=None):
        self.code = code
        self.pid = 4242

    def poll(self):
        return self.code


class _Out:
    def __init__(self):
        self.lines: list[str] = []

    def write(self, text):
        self.lines.append(text)

    def flush(self):
        pass

    @property
    def text(self):
        return "".join(self.lines)


def _fake_clock():
    now = [0.0]

    def clock():
        return now[0]

    def sleep(dt):
        now[0] += dt

    return clock, sleep


def test_wait_relays_output_and_returns_the_port(tmp_path):
    log = tmp_path / "dashboard-stdio.log"
    log.write_bytes(b"old run\n")
    offset = log.stat().st_size
    log.write_bytes(
        b"old run\n\xe2\x86\x92 Skipping web UI build\nROBO_DASHBOARD_READY port=9133\n"
        b"  Robo Web UI \xe2\x86\x92 http://127.0.0.1:9133\n"
    )
    out = _Out()
    clock, sleep = _fake_clock()
    port, code = bg.wait_for_ready(_Proc(), log, offset, out=out, clock=clock, sleep=sleep)
    assert (port, code) == (9133, None)
    assert "Skipping web UI build" in out.text
    assert "Robo Web UI" in out.text
    assert "old run" not in out.text            # only this launch's output
    assert "ROBO_DASHBOARD_READY" not in out.text  # internal sentinel stays hidden


def test_wait_reports_a_child_that_died(tmp_path):
    log = tmp_path / "dashboard-stdio.log"
    log.write_bytes(b"ERROR: [Errno 98] address already in use")
    out = _Out()
    clock, sleep = _fake_clock()
    port, code = bg.wait_for_ready(_Proc(code=1), log, 0, out=out, clock=clock, sleep=sleep)
    assert (port, code) == (None, 1)
    assert "address already in use" in out.text


def test_wait_gives_up_without_killing_a_slow_child(tmp_path):
    log = tmp_path / "dashboard-stdio.log"
    log.write_bytes(b"")
    clock, sleep = _fake_clock()
    port, code = bg.wait_for_ready(
        _Proc(), log, 0, timeout=2.0, out=_Out(), clock=clock, sleep=sleep
    )
    assert (port, code) == (None, None)


# ── already running ───────────────────────────────────────────────────────


def test_finds_a_live_dashboard_on_the_same_port():
    from robo_cli.main import _parse_dashboard_runtime

    found = bg.find_running_dashboard(
        "127.0.0.1",
        9119,
        scan=lambda: [
            (11, "python -m robo_cli.main serve --port 9119"),
            (22, "python -m robo_cli.main dashboard --host 0.0.0.0 --port 9119"),
        ],
        parse=_parse_dashboard_runtime,
        listening=lambda host, port: True,
    )
    assert found == (22, "0.0.0.0")
    assert not bg.same_bind("0.0.0.0", "127.0.0.1")
    assert bg.same_bind("localhost", "127.0.0.1")


def test_a_dead_or_ephemeral_port_is_not_already_running():
    from robo_cli.main import _parse_dashboard_runtime

    scan = lambda: [(22, "robo dashboard --port 9119")]  # noqa: E731
    assert bg.find_running_dashboard(
        "127.0.0.1", 9119, scan=scan, parse=_parse_dashboard_runtime,
        listening=lambda h, p: False,
    ) is None
    assert bg.find_running_dashboard(
        "127.0.0.1", 0, scan=scan, parse=_parse_dashboard_runtime,
        listening=lambda h, p: True,
    ) is None


# ── cmd_dashboard wiring ──────────────────────────────────────────────────


def _wire(main_mod, monkeypatch):
    monkeypatch.setattr("robo_cli.profiles.get_active_profile_name", lambda: "default")
    monkeypatch.setattr(main_mod, "_sync_bundled_skills_quietly", lambda: None)
    monkeypatch.setitem(sys.modules, "fastapi", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace())
    monkeypatch.setitem(
        sys.modules, "robo_logging", types.SimpleNamespace(setup_logging=lambda **_k: None)
    )
    monkeypatch.setitem(
        sys.modules, "robo_cli.plugins", types.SimpleNamespace(discover_plugins=lambda: None)
    )
    mcp = []
    monkeypatch.setattr(
        "robo_cli.mcp_startup.start_background_mcp_discovery",
        lambda **_k: mcp.append(1),
    )
    started = []
    monkeypatch.setitem(
        sys.modules,
        "robo_cli.web_server",
        types.SimpleNamespace(
            start_server=lambda **k: started.append(k),
            _maybe_open_browser=lambda *a: None,
            should_require_auth=lambda host: False,
        ),
    )
    monkeypatch.setattr(main_mod, "_scan_dashboard_processes", lambda **_k: [])
    return started, mcp


def _dash_args(**over):
    base = dict(
        host="127.0.0.1", port=9119, no_open=True, open_profile="", skip_build=True,
        headless_backend=False, tui=False, insecure=False, isolated=False,
        foreground=False, status=False, stop=False,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def test_interactive_launch_hands_off_before_serving(monkeypatch, tmp_path):
    import robo_cli.main as main_mod

    started, mcp = _wire(main_mod, monkeypatch)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>")
    monkeypatch.setenv("ROBO_WEB_DIST", str(dist))
    monkeypatch.setattr(bg, "should_run_in_background", lambda args, headless: True)
    launched = []

    def fake_launch(args, *, profile_name, open_browser):
        launched.append(profile_name)
        return 0

    monkeypatch.setattr(bg, "launch_dashboard_in_background", fake_launch)
    with pytest.raises(SystemExit) as exc:
        main_mod.cmd_dashboard(_dash_args())
    assert exc.value.code == 0
    assert launched == ["default"]
    assert started == []  # the detached child serves, not this process
    assert mcp == []      # MCP servers start in the child only


def test_foreground_launch_serves_in_process(monkeypatch, tmp_path):
    import robo_cli.main as main_mod

    started, _ = _wire(main_mod, monkeypatch)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>")
    monkeypatch.setenv("ROBO_WEB_DIST", str(dist))
    monkeypatch.setattr(bg, "should_run_in_background", lambda args, headless: False)
    main_mod.cmd_dashboard(_dash_args(foreground=True))
    assert len(started) == 1


def test_already_running_dashboard_is_reused(monkeypatch, capsys):
    import robo_cli.main as main_mod

    started, _ = _wire(main_mod, monkeypatch)
    monkeypatch.setattr(bg, "should_run_in_background", lambda args, headless: True)
    monkeypatch.setattr(
        main_mod, "_scan_dashboard_processes",
        lambda **_k: [(77, "python -m robo_cli.main dashboard --host 127.0.0.1 --port 9119")],
    )
    monkeypatch.setattr(main_mod, "_dashboard_listening", lambda h, p: True)
    with pytest.raises(SystemExit) as exc:
        main_mod.cmd_dashboard(_dash_args())
    assert exc.value.code == 0
    assert "already running" in capsys.readouterr().out
    assert started == []


def test_a_loopback_dashboard_blocks_a_network_bind_on_the_same_port(monkeypatch, capsys):
    import robo_cli.main as main_mod

    _wire(main_mod, monkeypatch)
    monkeypatch.setattr(bg, "should_run_in_background", lambda args, headless: True)
    monkeypatch.setattr(
        main_mod, "_scan_dashboard_processes",
        lambda **_k: [(77, "python -m robo_cli.main dashboard --port 9119")],
    )
    monkeypatch.setattr(main_mod, "_dashboard_listening", lambda h, p: True)
    with pytest.raises(SystemExit) as exc:
        main_mod.cmd_dashboard(_dash_args(host="0.0.0.0"))
    assert exc.value.code == 1
    assert "robo dashboard --stop" in capsys.readouterr().out


# ── Windows process scan without wmic ─────────────────────────────────────


def test_windows_scan_falls_back_to_psutil_when_wmic_is_missing(monkeypatch):
    from robo_cli import dashboard_procs

    monkeypatch.setattr(sys, "platform", "win32")

    def no_wmic(*_a, **_k):
        raise FileNotFoundError("wmic")

    monkeypatch.setattr(dashboard_procs.subprocess, "run", no_wmic)

    class _P:
        def __init__(self, pid, cmdline):
            self.info = {"pid": pid, "cmdline": cmdline}

    fake_psutil = types.SimpleNamespace(
        process_iter=lambda attrs: [
            _P(10, ["C:\\py\\python.exe", "-m", "robo_cli.main", "dashboard", "--port", "9119"]),
            _P(11, ["notepad.exe"]),
            _P(12, ["C:\\py\\python.exe", "-m", "robo_cli.main", "serve"]),
        ]
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    found = dashboard_procs._scan_dashboard_processes(exclude_pids={12})
    assert [pid for pid, _ in found] == [10]


# ── real detached process (POSIX) ─────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX session semantics")
def test_detached_child_has_its_own_session_and_reports_ready(tmp_path):
    script = tmp_path / "fake_dashboard.py"
    script.write_text(
        textwrap.dedent(
            """
            import time
            print("booting", flush=True)
            print("ROBO_DASHBOARD_READY port=9555", flush=True)
            print("  Robo Web UI -> http://127.0.0.1:9555", flush=True)
            time.sleep(30)
            """
        )
    )
    log = tmp_path / "dashboard-stdio.log"
    proc = bg.spawn_detached(
        [sys.executable, str(script)], env=bg.build_background_env(), log_path=log
    )
    try:
        out = _Out()
        port, code = bg.wait_for_ready(proc, log, 0, timeout=20, out=out)
        assert (port, code) == (9555, None)
        assert "Robo Web UI" in out.text
        # Own session: closing the launching terminal (SIGHUP to its session)
        # cannot reach it.
        assert os.getsid(proc.pid) != os.getsid(0)
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_scan_never_reports_our_own_launcher(monkeypatch):
    """A venv launcher shares our command line; --stop must not kill it."""
    from robo_cli import dashboard_procs

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(dashboard_procs, "_ancestor_pids", lambda: {111})

    class _Run:
        returncode = 0
        stdout = (
            "111 python -m robo_cli.main dashboard --stop\n"
            "222 python -m robo_cli.main dashboard --port 9119\n"
        )

    monkeypatch.setattr(dashboard_procs.subprocess, "run", lambda *a, **k: _Run())
    assert [pid for pid, _ in dashboard_procs._scan_dashboard_processes()] == [222]
