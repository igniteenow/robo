"""``warm_up_local_stt`` preloads faster-whisper when voice mode starts.

The model used to load lazily inside the FIRST transcription, so the first
spoken message of every session paid the whole load (plus the one-time
download) as a silent pause. Warm-up moves that to voice-mode start, on a
background thread, and must never do anything for cloud providers, when STT
is disabled, or when faster-whisper is not importable.
"""

from unittest.mock import patch

import tools.transcription_tools as tt


def _reset_model():
    tt._local_model = None
    tt._local_model_name = None


def test_loads_the_configured_local_model_once():
    _reset_model()
    loads = []

    def fake_load(model_name, device="auto", compute_type="auto", local_files_only=False):
        loads.append((model_name, device, compute_type, local_files_only))
        return object()

    cfg = {"enabled": True, "provider": "local", "local": {"model": "small", "device": "cpu", "compute_type": "int8"}}
    try:
        with patch.object(tt, "_HAS_FASTER_WHISPER", True), \
             patch.object(tt, "_load_stt_config", return_value=cfg), \
             patch.object(tt, "_load_local_whisper_model", fake_load):
            assert tt.warm_up_local_stt() is True
            assert tt.warm_up_local_stt() is True  # already loaded: no second load
    finally:
        _reset_model()

    # One load, from the local cache only — warm-up never downloads.
    assert loads == [("small", "cpu", "int8", True)]


def test_noop_when_faster_whisper_missing():
    _reset_model()
    with patch.object(tt, "_HAS_FASTER_WHISPER", False), \
         patch.object(tt, "_load_local_whisper_model", side_effect=AssertionError("must not load")):
        assert tt.warm_up_local_stt() is False
    assert tt._local_model is None


def test_noop_for_cloud_provider_or_disabled_stt():
    _reset_model()
    with patch.object(tt, "_HAS_FASTER_WHISPER", True), \
         patch.object(tt, "_load_local_whisper_model", side_effect=AssertionError("must not load")):
        with patch.object(tt, "_load_stt_config", return_value={"provider": "groq"}):
            assert tt.warm_up_local_stt() is False
        with patch.object(tt, "_load_stt_config", return_value={"enabled": False, "provider": "local"}):
            assert tt.warm_up_local_stt() is False
    assert tt._local_model is None


def test_load_failure_is_swallowed():
    """Model not on disk yet (local_files_only) or a broken runtime: skip quietly."""
    _reset_model()
    with patch.object(tt, "_HAS_FASTER_WHISPER", True), \
         patch.object(tt, "_load_stt_config", return_value={"provider": "local"}), \
         patch.object(tt, "_load_local_whisper_model", side_effect=RuntimeError("not cached")):
        assert tt.warm_up_local_stt() is False
    assert tt._local_model is None


def test_loader_passes_local_files_only_through(monkeypatch):
    import sys
    import types

    seen = []

    class _Model:
        def __init__(self, name, **kwargs):
            seen.append((name, kwargs))

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=_Model))
    with patch.object(tt, "_should_force_faster_whisper_cpu", return_value=False):
        tt._load_local_whisper_model("base", device="cpu", compute_type="int8", local_files_only=True)
        tt._load_local_whisper_model("base", device="cpu", compute_type="int8")

    assert seen == [
        ("base", {"device": "cpu", "compute_type": "int8", "local_files_only": True}),
        ("base", {"device": "cpu", "compute_type": "int8"}),
    ]
