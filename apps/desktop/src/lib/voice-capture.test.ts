import { describe, expect, it } from 'vitest'

import { SPEECH_SAMPLE_RATE } from './pcm-audio'
import { type CapturedUtterance, meterLevel, utteranceToWav, VoiceCaptureCore } from './voice-capture'

// The capture engine's pure core: 16 kHz samples in, utterances out. The
// microphone wiring (openVoiceCapture) only feeds it.

const RATE = SPEECH_SAMPLE_RATE

/** Deterministic room noise at roughly `db` dBFS. */
function noise(seconds: number, db: number, seed = 1): Float32Array {
  const out = new Float32Array(Math.round(RATE * seconds))
  const amplitude = 10 ** (db / 20) * Math.sqrt(3)
  let state = seed

  for (let index = 0; index < out.length; index += 1) {
    state = (state * 1_103_515_245 + 12_345) % 2 ** 31
    out[index] = amplitude * ((state / 2 ** 31) * 2 - 1)
  }

  return out
}

/** A voiced sound with syllable-like loudness, at roughly `db` dBFS. */
function voice(seconds: number, db = -20): Float32Array {
  const out = new Float32Array(Math.round(RATE * seconds))
  const amplitude = 10 ** (db / 20) * Math.SQRT2

  for (let index = 0; index < out.length; index += 1) {
    const t = index / RATE
    const syllable = 0.6 + 0.4 * Math.abs(Math.sin(Math.PI * 4 * t))

    out[index] = amplitude * syllable * Math.sin(2 * Math.PI * 180 * t)
  }

  return out
}

function capture(options: { playing?: boolean } = {}) {
  const utterances: CapturedUtterance[] = []
  const starts: { startedDuringPlayback: boolean }[] = []
  let blips = 0
  let lastLevel = 0

  const core = new VoiceCaptureCore({
    onBlip: () => (blips += 1),
    onLevel: level => (lastLevel = level),
    onSpeechStart: info => starts.push(info),
    onUtterance: utterance => utterances.push(utterance)
  })

  const feed = (samples: Float32Array, playing = options.playing ?? false) => {
    // Arbitrary chunking, like the audio thread's.
    for (let offset = 0; offset < samples.length; offset += 341) {
      core.push(samples.subarray(offset, offset + 341), playing)
    }
  }

  return {
    blips: () => blips,
    core,
    feed,
    level: () => lastLevel,
    starts,
    utterances
  }
}

describe('VoiceCaptureCore', () => {
  it('cuts one utterance: lead-in, the speech, and a short tail of the pause', () => {
    const ear = capture()

    ear.feed(noise(1, -65))
    ear.feed(voice(1.2))
    ear.feed(noise(1, -65, 7))

    expect(ear.starts).toEqual([{ startedDuringPlayback: false }])
    expect(ear.utterances).toHaveLength(1)

    const [utterance] = ear.utterances
    const seconds = utterance.samples.length / RATE

    expect(utterance.endedBy).toBe('silence')
    expect(utterance.sampleRate).toBe(RATE)
    // ~0.4 s lead-in + 1.2 s speech + ~0.3 s tail.
    expect(seconds).toBeGreaterThan(1.75)
    expect(seconds).toBeLessThan(2.05)
    expect(utterance.speechMs).toBeGreaterThan(1_000)
  })

  it('keeps the moment before speech was detected (the first syllable)', () => {
    const ear = capture()

    ear.feed(noise(1, -65))
    ear.feed(voice(1))
    ear.feed(noise(1, -65, 3))

    const samples = ear.utterances[0].samples
    const leadIn = samples.subarray(0, Math.round(RATE * 0.35))
    const peak = (values: Float32Array) => values.reduce((max, value) => Math.max(max, Math.abs(value)), 0)

    // The lead-in is room noise; the speech follows it in full.
    expect(peak(leadIn)).toBeLessThan(0.01)
    expect(peak(samples.subarray(Math.round(RATE * 0.42), Math.round(RATE * 0.5)))).toBeGreaterThan(0.05)
  })

  it('a click is not an utterance', () => {
    const ear = capture()

    ear.feed(noise(1, -65))
    ear.feed(voice(0.03, -10))
    ear.feed(noise(1, -65, 5))

    expect(ear.utterances).toEqual([])
    expect(ear.starts).toEqual([])
    expect(ear.blips()).toBe(1)
  })

  it('"Send now" mid-speech hands over what was said so far', () => {
    const ear = capture()

    ear.feed(noise(1, -65))
    ear.feed(voice(0.8))
    ear.core.flush()

    expect(ear.utterances).toHaveLength(1)
    expect(ear.utterances[0].endedBy).toBe('flush')
    expect(ear.utterances[0].speechMs).toBeGreaterThan(500)
    expect(ear.core.inUtterance).toBe(false)
  })

  it('"Send now" with no speech detected sends the recent audio, once', () => {
    const ear = capture()

    ear.feed(noise(12, -65))
    ear.core.flush()
    ear.core.flush()

    expect(ear.utterances).toHaveLength(1)
    expect(ear.utterances[0].speechMs).toBe(0)
    // Bounded: only the last few seconds, not the whole wait.
    expect(ear.utterances[0].samples.length / RATE).toBeLessThanOrEqual(8.01)
  })

  it('reset drops the utterance in progress', () => {
    const ear = capture()

    ear.feed(noise(1, -65))
    ear.feed(voice(0.6))
    ear.core.reset()
    ear.feed(noise(1, -65, 9))

    expect(ear.utterances).toEqual([])
  })

  it('marks speech that began while Robo was talking', () => {
    const ear = capture()

    ear.feed(noise(1, -65))
    ear.feed(noise(1, -62, 4), true) // the reply's quiet residual echo
    ear.feed(voice(1, -18), true)
    ear.feed(noise(1, -65, 6))

    expect(ear.starts).toEqual([{ startedDuringPlayback: true }])
    expect(ear.utterances[0].startedDuringPlayback).toBe(true)
  })

  it('reports a meter level', () => {
    const ear = capture()

    ear.feed(voice(0.2, -20))

    expect(ear.level()).toBeGreaterThan(0.6)
    expect(meterLevel(-100)).toBe(0)
    expect(meterLevel(0)).toBe(1)
  })

  it('wraps an utterance as a WAV the transcriber accepts', () => {
    const blob = utteranceToWav({
      endedBy: 'silence',
      sampleRate: RATE,
      samples: new Float32Array(1_600),
      speechMs: 100,
      startedDuringPlayback: false
    })

    expect(blob.type).toBe('audio/wav')
    expect(blob.size).toBe(44 + 3_200)
  })
})
