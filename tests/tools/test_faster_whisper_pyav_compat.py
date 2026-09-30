"""PyAV 19 compatibility for local speech-to-text (faster-whisper).

faster-whisper 1.2.1 decodes audio with
``av.open(path, mode="r", metadata_errors="ignore")``. PyAV 19.0.0 removed
that argument, so on an install that picked up PyAV 19 every local
transcription failed with ``TypeError: open() got an unexpected keyword
argument 'metadata_errors'`` — the TUI dropped every recording and the desktop
app showed "Local transcription failed".

These tests drive the real ``_transcribe_local`` / compat shim against stand-in
``av`` and ``faster_whisper.audio`` modules that behave like PyAV 19 (rejects
the argument) and PyAV 18 (accepts it), so they run without either package.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from tools import transcription_tools as tt

_REMOVED = "open() got an unexpected keyword argument 'metadata_errors'"


class _Opened:
    def __init__(self, path, kwargs):
        self.path = path
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_av(*, accepts_metadata_errors: bool):
    av = types.ModuleType("av")
    av.calls = []
    av.audio = types.SimpleNamespace(resampler="real resampler namespace")

    def open(path, mode="r", **kwargs):  # noqa: A001 - mirrors av.open
        av.calls.append(dict(kwargs, mode=mode))
        if not accepts_metadata_errors and "metadata_errors" in kwargs:
            raise TypeError(_REMOVED)
        return _Opened(path, dict(kwargs, mode=mode))

    av.open = open
    return av


@pytest.fixture
def fake_faster_whisper(monkeypatch):
    """Install stand-in ``faster_whisper`` + ``faster_whisper.audio`` modules."""

    def _install(av_module):
        pkg = types.ModuleType("faster_whisper")
        pkg.__path__ = []
        audio = types.ModuleType("faster_whisper.audio")
        audio.av = av_module

        def decode_audio(path):
            # Same call faster-whisper 1.2.1 makes; `av` is looked up in this
            # module's globals at call time, exactly like the real module.
            with audio.av.open(path, mode="r", metadata_errors="ignore") as container:
                return container

        audio.decode_audio = decode_audio
        pkg.audio = audio
        monkeypatch.setitem(sys.modules, "faster_whisper", pkg)
        monkeypatch.setitem(sys.modules, "faster_whisper.audio", audio)
        return audio

    return _install


def test_pyav_19_fails_without_the_shim(fake_faster_whisper):
    audio = fake_faster_whisper(_fake_av(accepts_metadata_errors=False))
    with pytest.raises(TypeError, match="metadata_errors"):
        audio.decode_audio("clip.wav")


def test_shim_makes_pyav_19_decode_work(fake_faster_whisper):
    av = _fake_av(accepts_metadata_errors=False)
    audio = fake_faster_whisper(av)

    tt._ensure_faster_whisper_pyav_compat()
    opened = audio.decode_audio("clip.wav")

    assert opened.path == "clip.wav"
    assert "metadata_errors" not in opened.kwargs
    assert opened.kwargs["mode"] == "r"
    # Everything else still comes from the real module.
    assert audio.av.audio is av.audio


def test_shim_leaves_older_pyav_calls_untouched(fake_faster_whisper):
    av = _fake_av(accepts_metadata_errors=True)
    audio = fake_faster_whisper(av)

    tt._ensure_faster_whisper_pyav_compat()
    opened = audio.decode_audio("clip.wav")

    assert opened.kwargs["metadata_errors"] == "ignore"
    assert len(av.calls) == 1  # one call, no retry


def test_shim_does_not_hide_unrelated_type_errors(fake_faster_whisper):
    av = types.ModuleType("av")

    def open(path, mode="r", **kwargs):  # noqa: A001
        raise TypeError("expected str, bytes or os.PathLike object, not int")

    av.open = open
    audio = fake_faster_whisper(av)

    tt._ensure_faster_whisper_pyav_compat()
    with pytest.raises(TypeError, match="PathLike"):
        audio.decode_audio(123)


def test_shim_is_installed_once(fake_faster_whisper):
    audio = fake_faster_whisper(_fake_av(accepts_metadata_errors=False))

    tt._ensure_faster_whisper_pyav_compat()
    first = audio.av
    tt._ensure_faster_whisper_pyav_compat()

    assert audio.av is first
    assert isinstance(first, tt._PyAVOpenCompat)


def test_shim_is_a_no_op_without_faster_whisper(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    tt._ensure_faster_whisper_pyav_compat()  # must not raise


def test_local_transcription_succeeds_on_pyav_19(fake_faster_whisper, tmp_path):
    """End to end through _transcribe_local: the model decodes the file via
    faster_whisper.audio (as the real WhisperModel.transcribe does)."""
    audio_mod = fake_faster_whisper(_fake_av(accepts_metadata_errors=False))
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"RIFF")

    segment = MagicMock()
    segment.text = "hello robo"
    info = MagicMock(language="en", duration=1.0)

    def transcribe(path, **kwargs):
        audio_mod.decode_audio(path)
        return [segment], info

    model = MagicMock()
    model.transcribe.side_effect = transcribe

    with patch.object(tt, "_HAS_FASTER_WHISPER", True), \
         patch.object(tt, "_local_model", model), \
         patch.object(tt, "_local_model_name", "base"), \
         patch.object(tt, "_load_stt_config", return_value={}), \
         patch.object(tt, "build_local_transcribe_kwargs", return_value={"language": "en"}), \
         patch.object(tt, "_join_confident_segments", return_value="hello robo"):
        result = tt._transcribe_local(str(clip), "base")

    assert result == {"success": True, "transcript": "hello robo", "provider": "local"}


def test_lazy_install_pins_pyav_to_the_locked_version():
    """The on-demand faster-whisper install must not float to the newest
    PyAV: pin it, and keep the pin equal to what uv.lock resolves."""
    import re
    from pathlib import Path

    from tools.lazy_deps import LAZY_DEPS

    specs = LAZY_DEPS["stt.faster_whisper"]
    av_specs = [s for s in specs if re.match(r"^av==", s)]
    assert av_specs, f"stt.faster_whisper must pin av: {specs}"

    lock = (Path(__file__).resolve().parents[2] / "uv.lock").read_text(encoding="utf-8")
    locked = re.search(r'\[\[package\]\]\nname = "av"\nversion = "([^"]+)"', lock)
    assert locked, "av is not in uv.lock"
    assert av_specs[0] == f"av=={locked.group(1)}"


def test_robo_update_moves_an_installed_pyav_19_back_to_the_pin(monkeypatch):
    """`robo update` refreshes active lazy backends via feature_missing(): an
    install that already picked up PyAV 19 must be flagged for repair, and
    only PyAV — faster-whisper, sounddevice and numpy stay untouched."""
    import importlib.metadata as md

    from tools import lazy_deps as ld

    pinned = {
        ld._pkg_name_from_spec(s): ld._specifier_from_spec(s).lstrip("=")
        for s in ld.LAZY_DEPS["stt.faster_whisper"]
    }
    installed = dict(pinned, av="19.0.0")

    def _version(pkg):
        if pkg in installed:
            return installed[pkg]
        raise md.PackageNotFoundError(pkg)

    monkeypatch.setattr(md, "version", _version)

    assert "stt.faster_whisper" in ld.active_features()
    assert ld.feature_missing("stt.faster_whisper") == (f"av=={pinned['av']}",)

    installed["av"] = pinned["av"]
    assert ld.feature_missing("stt.faster_whisper") == ()


def test_shim_runs_only_after_the_model_is_loaded(tmp_path):
    """Importing faster_whisper for the shim must not beat
    _load_local_whisper_model, which sets KMP_DUPLICATE_LIB_OK first (the
    Apple Silicon/Rosetta native-crash guard)."""
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"RIFF")
    order: list[str] = []

    info = MagicMock(language="en", duration=1.0)
    model = MagicMock()
    model.transcribe.side_effect = lambda *_a, **_k: (order.append("transcribe") or ([], info))

    def load(*_a, **_k):
        order.append("load")
        return model

    with patch.object(tt, "_HAS_FASTER_WHISPER", True), \
         patch.object(tt, "_local_model", None), \
         patch.object(tt, "_local_model_name", None), \
         patch.object(tt, "_load_local_whisper_model", side_effect=load), \
         patch.object(tt, "_ensure_faster_whisper_pyav_compat", side_effect=lambda: order.append("shim")), \
         patch.object(tt, "_load_stt_config", return_value={}), \
         patch.object(tt, "build_local_transcribe_kwargs", return_value={"language": "en"}), \
         patch.object(tt, "_join_confident_segments", return_value="ok"):
        result = tt._transcribe_local(str(clip), "base")

    assert result["success"] is True
    assert order == ["load", "shim", "transcribe"]
