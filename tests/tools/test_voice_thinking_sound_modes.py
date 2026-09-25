"""``voice.thinking_sound`` is a mode, and the default is a short cue.

The blips used to run for the whole turn whenever voice mode was on — every
typed prompt included — which read as noise. Now ``true`` (the default) means
"blip only while a spoken recording is being transcribed, silent the moment
the text is in", ``"ambient"`` restores the turn-long loop, ``false`` is off.
"""

import threading
import time
from unittest.mock import patch

import tools.voice_mode as vm


def _reset():
    vm.stop_thinking_sound()


def _with_cfg(value):
    return patch("robo_cli.config.load_config", return_value={"voice": {"thinking_sound": value}})


class TestMode:
    def test_default_is_cue(self):
        with patch("robo_cli.config.load_config", return_value={"voice": {}}):
            assert vm.thinking_sound_mode() == "cue"
            assert vm.thinking_sound_enabled() is True
            assert vm.thinking_sound_ambient() is False

    def test_booleans_keep_working(self):
        with _with_cfg(True):
            assert vm.thinking_sound_mode() == "cue"
        with _with_cfg(False):
            assert vm.thinking_sound_mode() == "off"
            assert vm.thinking_sound_enabled() is False

    def test_strings(self):
        for raw, mode in [
            ("ambient", "ambient"),
            ("Always", "ambient"),
            ("cue", "cue"),
            ("on", "cue"),
            ("off", "off"),
            ("never", "off"),
            ("false", "off"),
            ("true", "cue"),
        ]:
            with _with_cfg(raw):
                assert vm.thinking_sound_mode() == mode, raw

    def test_ambient_opt_in(self):
        with _with_cfg("ambient"):
            assert vm.thinking_sound_ambient() is True
            assert vm.thinking_sound_enabled() is True

    def test_malformed_voice_section_defaults_to_cue(self):
        with patch("robo_cli.config.load_config", return_value={"voice": "yes"}):
            assert vm.thinking_sound_mode() == "cue"
        with patch("robo_cli.config.load_config", side_effect=RuntimeError("boom")):
            assert vm.thinking_sound_mode() == "cue"


class TestTranscribingCue:
    def test_cue_refuses_when_off(self):
        _reset()
        with _with_cfg(False):
            assert vm.start_transcribing_cue() is False
        assert vm._thinking_stop is None

    def test_cue_starts_capped_loop_and_stop_silences(self):
        _reset()
        seen = {}

        def fake_start(should_play=None, max_seconds=None, *, owner="ambient"):
            seen["max_seconds"] = max_seconds
            seen["should_play"] = should_play
            seen["owner"] = owner
            return True

        with _with_cfg(True), patch.object(vm, "start_thinking_sound", fake_start):
            assert vm.start_transcribing_cue() is True

        assert seen["max_seconds"] == vm.TRANSCRIBING_CUE_MAX_SECONDS
        assert seen["owner"] == "cue"
        # Blips yield to real speech audio.
        assert seen["should_play"]() is True
        vm.mark_audio_output_active(True)
        try:
            assert seen["should_play"]() is False
        finally:
            vm.mark_audio_output_active(False)

    def test_stop_cue_silences_the_loop_the_cue_started(self):
        _reset()
        with patch.object(vm, "thinking_sound_enabled", return_value=True), \
             patch.object(vm, "_sounddevice_output_allowed", return_value=False), \
             _with_cfg(True):
            assert vm.start_transcribing_cue() is True
            stop = vm._thinking_stop
            assert vm._thinking_owner == "cue"
            vm.stop_transcribing_cue()
            assert stop.is_set()
            assert vm._thinking_stop is None
            assert vm._thinking_owner is None
            vm.stop_transcribing_cue()  # idempotent

    def test_stop_cue_leaves_the_ambient_loop_alone(self):
        """thinking_sound: ambient — a spoken message mid-turn is transcribed
        while the turn-long loop runs; the cue "starts" (already running) and
        its stop must not silence the turn. Only the turn's own
        stop_thinking_sound() ends that loop."""
        _reset()
        with patch.object(vm, "thinking_sound_enabled", return_value=True), \
             patch.object(vm, "_sounddevice_output_allowed", return_value=False), \
             _with_cfg("ambient"):
            assert vm.start_thinking_sound() is True  # the turn's loop
            stop = vm._thinking_stop
            assert vm._thinking_owner == "ambient"
            assert vm.start_transcribing_cue() is True  # already running
            assert vm._thinking_owner == "ambient"
            vm.stop_transcribing_cue()
            assert not stop.is_set()
            assert vm._thinking_stop is stop
            vm.stop_thinking_sound()
            assert stop.is_set()
            assert vm._thinking_stop is None
            assert vm._thinking_owner is None


class TestLoopDeadline:
    def test_loop_ends_on_its_own_after_max_seconds(self):
        """A stuck STT backend can never leave the cue blipping forever."""
        _reset()

        class _SD:
            def play(self, *a, **k):
                pass

            def stop(self):
                pass

        class _NP:
            def linspace(self, *a, **k):
                return [0.0]

            def cumsum(self, x):
                return x

            def sin(self, x):
                return x

            def ones(self, n):
                return [1.0] * n

            def exp(self, x):
                return x

            int16 = int

        stop = threading.Event()
        # Registered as the running loop, the way start_thinking_sound does it.
        vm._thinking_stop, vm._thinking_owner = stop, "cue"
        with patch.object(vm, "_sounddevice_output_allowed", return_value=True), \
             patch.object(vm, "_import_audio", return_value=(_SD(), _NP())), \
             patch.object(vm, "_synth_thinking_blip", return_value=[0] * 160):
            t = threading.Thread(
                target=vm._thinking_sound_loop, args=(stop, lambda: False, 0.2), daemon=True
            )
            started = time.monotonic()
            t.start()
            t.join(timeout=5.0)
        assert not t.is_alive(), "loop ignored max_seconds"
        assert time.monotonic() - started < 5.0
        assert not stop.is_set()  # nobody asked it to stop; it timed out
        # ...and it unregistered itself, so the next start is not a no-op.
        assert vm._thinking_stop is None
        assert vm._thinking_owner is None
