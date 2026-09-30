"""Speech-to-text failures in the voice loop are reported, not swallowed.

Before this, a failing transcription (a broken local engine, a provider
error) was treated exactly like silence: the recording badge went away,
nothing was sent, and the user never learned why. ``start_continuous`` now
takes ``on_error`` and calls it with the error text on both transcription
paths — the VAD silence stop and the manual stop (Ctrl+B pressed again).
"""

from __future__ import annotations

import threading

import pytest


@pytest.fixture
def voice(monkeypatch):
    import robo_cli.voice as voice

    monkeypatch.setattr(voice, "_continuous_active", False)
    monkeypatch.setattr(voice, "_continuous_stopping", False)
    monkeypatch.setattr(voice, "_continuous_recorder", None)
    monkeypatch.setattr(voice, "_continuous_no_speech_count", 0)
    monkeypatch.setattr(voice, "_continuous_on_transcript", None)
    monkeypatch.setattr(voice, "_continuous_on_status", None)
    monkeypatch.setattr(voice, "_continuous_on_silent_limit", None)
    monkeypatch.setattr(voice, "_continuous_on_stop_phrase", None)
    monkeypatch.setattr(voice, "_continuous_on_error", None)
    monkeypatch.setattr(voice, "_continuous_auto_restart", False, raising=False)
    monkeypatch.setattr(voice, "_voice_busy_probe", None, raising=False)
    monkeypatch.setattr(voice, "is_whisper_hallucination", lambda _t: False)
    monkeypatch.setattr(voice, "is_voice_stop_phrase", lambda _t: False)

    class FakeRecorder:
        _silence_threshold = 200
        _silence_duration = 1.5
        is_recording = False

        def __init__(self):
            self.last_callback = None

        def start(self, on_silence_stop=None):
            self.last_callback = on_silence_stop
            self.is_recording = True

        def stop(self):
            self.is_recording = False
            return "/tmp/robo-voice-test.wav"

        def cancel(self):
            self.is_recording = False

    rec = FakeRecorder()
    monkeypatch.setattr(voice, "create_audio_recorder", lambda: rec)
    monkeypatch.setattr(voice.os.path, "isfile", lambda _p: False)
    voice._test_recorder = rec
    yield voice
    voice.stop_continuous()


def _start(voice, errors, transcripts, statuses=None):
    return voice.start_continuous(
        on_transcript=transcripts.append,
        on_status=(statuses.append if statuses is not None else None),
        auto_restart=False,
        on_error=errors.append,
    )


def test_failed_transcription_on_silence_stop_is_reported(voice, monkeypatch):
    monkeypatch.setattr(
        voice,
        "transcribe_recording",
        lambda _p: {
            "success": False,
            "transcript": "",
            "error": "Local transcription failed: open() got an unexpected keyword argument 'metadata_errors'",
        },
    )
    errors, transcripts, statuses = [], [], []
    _start(voice, errors, transcripts, statuses)

    voice._test_recorder.last_callback()  # VAD: the user stopped talking

    assert errors == [
        "Local transcription failed: open() got an unexpected keyword argument 'metadata_errors'"
    ]
    assert transcripts == []
    assert statuses[-1] == "idle"


def test_transcription_exception_on_silence_stop_is_reported(voice, monkeypatch):
    def boom(_p):
        raise RuntimeError("model file is corrupt")

    monkeypatch.setattr(voice, "transcribe_recording", boom)
    errors, transcripts = [], []
    _start(voice, errors, transcripts)

    voice._test_recorder.last_callback()

    assert errors == ["model file is corrupt"]
    assert transcripts == []


@pytest.mark.parametrize(
    "result",
    [
        {"success": True, "transcript": "what time is it in London"},
        {"success": True, "transcript": ""},  # silence is not an error
    ],
)
def test_success_and_silence_are_not_errors(voice, monkeypatch, result):
    monkeypatch.setattr(voice, "transcribe_recording", lambda _p: result)
    errors, transcripts = [], []
    _start(voice, errors, transcripts)

    voice._test_recorder.last_callback()

    assert errors == []
    assert transcripts == ([result["transcript"]] if result["transcript"] else [])


def test_failed_transcription_on_manual_stop_is_reported(voice, monkeypatch):
    """Ctrl+B pressed a second time: stop_continuous(force_transcribe=True)
    transcribes on a background thread."""
    monkeypatch.setattr(
        voice,
        "transcribe_recording",
        lambda _p: {"success": False, "transcript": "", "error": "Groq API key missing"},
    )
    done = threading.Event()
    errors, transcripts = [], []

    def on_status(state):
        if state == "idle":
            done.set()

    voice.start_continuous(
        on_transcript=transcripts.append,
        on_status=on_status,
        auto_restart=False,
        on_error=errors.append,
    )
    voice.stop_continuous(force_transcribe=True)

    assert done.wait(5), "the manual stop never finished"
    assert errors == ["Groq API key missing"]
    assert transcripts == []


def test_callers_without_on_error_still_work(voice, monkeypatch):
    monkeypatch.setattr(
        voice, "transcribe_recording", lambda _p: {"success": False, "error": "nope"}
    )
    transcripts = []
    voice.start_continuous(on_transcript=transcripts.append, auto_restart=False)

    voice._test_recorder.last_callback()  # must not raise

    assert transcripts == []


def test_a_raising_on_error_does_not_break_the_loop(voice, monkeypatch):
    monkeypatch.setattr(
        voice, "transcribe_recording", lambda _p: {"success": False, "error": "nope"}
    )
    statuses = []

    def bad_on_error(_text):
        raise RuntimeError("ui went away")

    voice.start_continuous(
        on_transcript=lambda _t: None,
        on_status=statuses.append,
        auto_restart=False,
        on_error=bad_on_error,
    )
    voice._test_recorder.last_callback()

    assert statuses[-1] == "idle"
