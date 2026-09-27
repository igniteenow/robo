"""A voice reply may carry real URLs: the screen keeps them, the ear never
hears them.

The voice-turn note (``SPOKEN_TURN_NOTE`` / the classic CLI voice prefix) used
to forbid URLs and markdown outright, which stripped links out of the on-screen
transcript and made the model spell URLs aloud as "dot com slash" — even when
the user explicitly asked for the real links. That blanket ban was never needed
to protect the audio: the streaming TTS path cleans every sentence through
``tools.tts_text_normalize`` before it is spoken. These tests pin that
invariant, so the note can safely ask for complete links on screen.
"""

from __future__ import annotations

import queue
import threading
from unittest.mock import patch

import tools.tts_streaming as ts
from tools import tts_tool
from tools.tts_text_normalize import prepare_spoken_text

REPLY_WITH_LINKS = (
    "Here are two cameras. The Arlo Pro 6 is about 125 dollars — "
    "[Arlo Pro 6](https://us.arlo.com/products/arlo-pro-6). "
    "The Reolink Argus 4 Pro is around 180 dollars, at "
    "https://reolink.com/us/product/argus-4-pro. Want the full spec sheet?"
)


def test_spoken_text_drops_links_but_keeps_the_words():
    spoken = prepare_spoken_text(REPLY_WITH_LINKS)
    assert "http" not in spoken.lower()
    assert "us.arlo.com" not in spoken
    assert "reolink.com" not in spoken
    # The human-readable label survives so the sentence still makes sense aloud.
    assert "Arlo Pro 6" in spoken
    assert "180 dollars" in spoken


class _CaptureStreamer(ts.StreamingTTSProvider):
    """Records the exact text handed to the audio backend for each sentence."""

    sample_rate = 24000

    def __init__(self, *_a, **_k):
        super().__init__({}, {})
        self.spoken: list[str] = []

    @staticmethod
    def available():
        return True

    def stream(self, text):
        self.spoken.append(text)
        yield b"\x00\x00"


def test_streaming_tts_never_sends_a_url_to_the_audio_backend():
    """The per-sentence streaming path is where TUI/desktop voice speaks, so
    prove the cleaning happens there and not only in the whole-reply helper."""
    streamer = _CaptureStreamer()

    q: queue.Queue = queue.Queue()
    # Feed it the reply in two deltas so a link spans the sentence boundary,
    # mirroring how tokens actually arrive.
    q.put(REPLY_WITH_LINKS[:80])
    q.put(REPLY_WITH_LINKS[80:])
    q.put(None)
    stop, done = threading.Event(), threading.Event()

    with patch("tools.tts_streaming.resolve_streaming_provider", return_value=streamer), \
         patch.object(tts_tool, "_import_sounddevice", side_effect=OSError("no audio")), \
         patch("platform.system", return_value="Linux"):
        tts_tool.stream_tts_to_speaker(q, stop, done)

    assert done.is_set()
    assert streamer.spoken, "the streamer should have been asked to speak something"
    joined = " ".join(streamer.spoken)
    assert "http" not in joined.lower(), f"a URL reached the audio backend: {streamer.spoken!r}"
    assert "us.arlo.com" not in joined
    assert "reolink.com" not in joined
    # And the actual content still got spoken.
    assert "Arlo Pro 6" in joined


def test_voice_note_no_longer_bans_urls_and_asks_for_them_on_screen():
    """A behavior guard on the note itself: it must not carry a blanket 'no
    URLs' ban (the old bug), and must tell the model the reply is also shown on
    screen so links belong there."""
    note = ts.SPOKEN_TURN_NOTE.lower()
    assert "no markdown, lists, headings, code or urls" not in note
    assert "screen" in note
    assert "url" in note  # it now speaks about URLs positively, not as a ban
