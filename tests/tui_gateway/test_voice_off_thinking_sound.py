"""``/voice off`` must silence the ambient thinking sound at once.

The thinking sound (soft bubble blips while the agent works in voice mode)
is started per turn and stopped in that turn's ``finally``. Turning voice
off while a turn is still running used to leave it blipping until the turn
ended: the ``voice.toggle`` off branch never stopped the loop, and the
per-blip gate never asked whether voice mode was still enabled.
"""

import sys
import types

from tui_gateway import server


def test_voice_toggle_off_stops_thinking_sound(monkeypatch):
    calls: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "tools.voice_mode",
        types.SimpleNamespace(stop_thinking_sound=lambda: calls.append("stop")),
    )
    monkeypatch.setitem(
        sys.modules,
        "robo_cli.voice",
        types.SimpleNamespace(stop_continuous=lambda: None),
    )
    monkeypatch.setattr(server, "_tts_stream_stop", lambda user_barge=True: None)
    monkeypatch.setenv("ROBO_VOICE", "1")

    resp = server.dispatch(
        {"id": "voice-off", "method": "voice.toggle", "params": {"action": "off"}}
    )

    assert resp["result"]["enabled"] is False
    assert calls == ["stop"]


def test_voice_toggle_off_survives_missing_stop_hook(monkeypatch):
    """A voice_mode without the hook (older or stubbed module) must not break /voice off."""
    monkeypatch.setitem(sys.modules, "tools.voice_mode", types.SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "robo_cli.voice",
        types.SimpleNamespace(stop_continuous=lambda: None),
    )
    monkeypatch.setattr(server, "_tts_stream_stop", lambda user_barge=True: None)
    monkeypatch.setenv("ROBO_VOICE", "1")

    resp = server.dispatch(
        {"id": "voice-off", "method": "voice.toggle", "params": {"action": "off"}}
    )

    assert resp["result"]["enabled"] is False


def test_thinking_sound_gate_is_false_when_voice_mode_off(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "tools.voice_mode",
        types.SimpleNamespace(is_audio_output_active=lambda: False),
    )
    monkeypatch.setitem(
        sys.modules,
        "robo_cli.voice",
        types.SimpleNamespace(is_continuous_active=lambda: False),
    )

    monkeypatch.setenv("ROBO_VOICE", "1")
    assert server._thinking_sound_allowed() is True

    monkeypatch.setenv("ROBO_VOICE", "0")
    assert server._thinking_sound_allowed() is False


def test_thinking_sound_gate_yields_to_speech_and_mic(monkeypatch):
    monkeypatch.setenv("ROBO_VOICE", "1")

    monkeypatch.setitem(
        sys.modules,
        "tools.voice_mode",
        types.SimpleNamespace(is_audio_output_active=lambda: True),
    )
    monkeypatch.setitem(
        sys.modules,
        "robo_cli.voice",
        types.SimpleNamespace(is_continuous_active=lambda: False),
    )
    assert server._thinking_sound_allowed() is False

    monkeypatch.setitem(
        sys.modules,
        "tools.voice_mode",
        types.SimpleNamespace(is_audio_output_active=lambda: False),
    )
    monkeypatch.setitem(
        sys.modules,
        "robo_cli.voice",
        types.SimpleNamespace(is_continuous_active=lambda: True),
    )
    assert server._thinking_sound_allowed() is False


# ── Transcription cue + STT warm-up ────────────────────────────────────────
#
# By default the blips are no longer a turn-long ambient loop: they play only
# while a spoken recording is being transcribed, and stop the moment the
# transcript (or a silence / stop-phrase verdict) comes back. Typed prompts
# never trigger them. Voice-mode start also preloads the local STT model so
# the first recording is not the one that pays for loading it.


def _voice_stubs(monkeypatch):
    """Stub the audio stack under voice.record so its callbacks can be driven."""
    captured: dict = {}
    cue: list[str] = []

    def start_continuous(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setitem(
        sys.modules,
        "robo_cli.voice",
        types.SimpleNamespace(
            start_continuous=start_continuous,
            stop_continuous=lambda force_transcribe=False: None,
            set_voice_busy_probe=lambda probe: None,
            is_continuous_active=lambda: False,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "tools.wake_word",
        types.SimpleNamespace(pause_listening=lambda owner=None: False, resume_listening=lambda owner=None: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "tools.voice_mode",
        types.SimpleNamespace(
            start_transcribing_cue=lambda: cue.append("start") or True,
            stop_transcribing_cue=lambda: cue.append("stop"),
            stop_thinking_sound=lambda: cue.append("stop"),
            is_audio_output_active=lambda: False,
        ),
    )
    emitted: list = []
    monkeypatch.setattr(server, "_voice_emit", lambda event, payload=None: emitted.append((event, payload)))
    monkeypatch.setattr(server, "_resume_voice_wake", lambda: None)
    monkeypatch.setattr(server, "_load_cfg", lambda: {})
    monkeypatch.setenv("ROBO_VOICE", "1")
    return captured, cue, emitted


def test_voice_record_cue_runs_only_while_transcribing(monkeypatch):
    captured, cue, emitted = _voice_stubs(monkeypatch)

    resp = server.dispatch(
        {"id": "rec", "method": "voice.record", "params": {"action": "start", "session_id": "sid"}}
    )
    assert resp["result"]["status"] == "recording"
    assert cue == []  # recording itself is silent

    captured["on_status"]("listening")
    assert cue == []

    captured["on_status"]("transcribing")
    assert cue == ["start"]

    captured["on_transcript"]("also check auth.log")
    assert cue[-1] == "stop"
    assert ("voice.transcript", {"text": "also check auth.log"}) in emitted

    captured["on_status"]("idle")
    assert cue[-1] == "stop"


def test_voice_record_cue_stops_on_silence_and_stop_phrase(monkeypatch):
    captured, cue, emitted = _voice_stubs(monkeypatch)
    monkeypatch.setattr(server, "_tts_stream_stop", lambda user_barge=True: None)
    server.dispatch(
        {"id": "rec", "method": "voice.record", "params": {"action": "start", "session_id": "sid"}}
    )

    captured["on_status"]("transcribing")
    captured["on_silent_limit"]()
    assert cue == ["start", "stop"]
    assert ("voice.transcript", {"no_speech_limit": True}) in emitted

    captured["on_status"]("transcribing")
    captured["on_stop_phrase"]("stop")
    assert cue == ["start", "stop", "start", "stop"]
    assert ("voice.transcript", {"stop_phrase": True, "text": "stop"}) in emitted


def test_transcribing_cue_helpers_are_quiet_off_voice_mode(monkeypatch):
    calls: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "tools.voice_mode",
        types.SimpleNamespace(
            start_transcribing_cue=lambda: calls.append("start") or True,
            stop_transcribing_cue=lambda: calls.append("stop"),
        ),
    )
    monkeypatch.setenv("ROBO_VOICE", "0")
    server._start_transcribing_cue()
    assert calls == []  # voice mode off: never start
    server._stop_transcribing_cue()
    assert calls == ["stop"]  # stopping is always safe

    monkeypatch.setenv("ROBO_VOICE", "1")
    server._start_transcribing_cue()
    assert calls == ["stop", "start"]


def test_transcribing_cue_helpers_survive_missing_audio_stack(monkeypatch):
    monkeypatch.setitem(sys.modules, "tools.voice_mode", types.SimpleNamespace())
    monkeypatch.setenv("ROBO_VOICE", "1")
    server._start_transcribing_cue()
    server._stop_transcribing_cue()  # neither raises


def test_voice_toggle_on_warms_up_stt_off_the_rpc_thread(monkeypatch):
    warmed: list[str] = []
    monkeypatch.setattr(server, "_warm_up_stt_in_background", lambda: warmed.append("warm"))
    monkeypatch.setitem(sys.modules, "tools.voice_mode", types.SimpleNamespace(voice_stop_hint=lambda: ""))
    monkeypatch.setenv("ROBO_VOICE", "0")

    resp = server.dispatch({"id": "on", "method": "voice.toggle", "params": {"action": "on"}})

    assert resp["result"]["enabled"] is True
    assert warmed == ["warm"]


def test_voice_toggle_off_does_not_warm_up(monkeypatch):
    warmed: list[str] = []
    monkeypatch.setattr(server, "_warm_up_stt_in_background", lambda: warmed.append("warm"))
    monkeypatch.setitem(
        sys.modules, "tools.voice_mode", types.SimpleNamespace(stop_thinking_sound=lambda: None)
    )
    monkeypatch.setitem(
        sys.modules, "robo_cli.voice", types.SimpleNamespace(stop_continuous=lambda: None)
    )
    monkeypatch.setattr(server, "_tts_stream_stop", lambda user_barge=True: None)
    monkeypatch.setenv("ROBO_VOICE", "1")

    server.dispatch({"id": "off", "method": "voice.toggle", "params": {"action": "off"}})

    assert warmed == []


def test_warm_up_runs_helper_on_daemon_thread(monkeypatch):
    import threading

    # The helper refuses to spawn under pytest (no background model loads in
    # the test process); lift that guard for this one call.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    done = threading.Event()
    monkeypatch.setitem(
        sys.modules,
        "tools.transcription_tools",
        types.SimpleNamespace(warm_up_local_stt=lambda: done.set() or True),
    )

    server._warm_up_stt_in_background()

    assert done.wait(2.0), "warm-up helper never ran"


def test_warm_up_never_raises_when_helper_is_missing(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setitem(sys.modules, "tools.transcription_tools", types.SimpleNamespace())
    server._warm_up_stt_in_background()  # thread swallows the AttributeError


def test_warm_up_is_skipped_inside_the_test_process(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/x.py::test_y (call)")
    calls: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "tools.transcription_tools",
        types.SimpleNamespace(warm_up_local_stt=lambda: calls.append("warm")),
    )
    server._warm_up_stt_in_background()
    import time

    time.sleep(0.05)
    assert calls == []
