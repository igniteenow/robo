import { describe, expect, it } from 'vitest'

import { CALIBRATION_MS, SpeechEndpointer, type SpeechEndpointEvent, TRIGGER_CEILING } from './speech-endpointer'

// Synthetic level traces at a 16 ms cadence (a display frame). Each case is a
// room + a speaker; the assertions are when the turn starts and ends.

const FRAME_MS = 16
const OPTIONS = { idleSilenceMs: 12_000, maxSpeechMs: 30_000, minLevel: 0.075, silenceMs: 650 }

/** Feed a trace of (level, durationMs) segments; return the first event and when it fired. */
function run(
  endpointer: SpeechEndpointer,
  segments: [level: number, ms: number][]
): { at: number; event: SpeechEndpointEvent; heardAt: null | number } {
  let now = 0
  let heardAt: null | number = null

  for (const [level, ms] of segments) {
    for (let elapsed = 0; elapsed < ms; elapsed += FRAME_MS) {
      const event = endpointer.feed(level, now)

      if (heardAt === null && endpointer.heardSpeech) {
        heardAt = now
      }

      if (event) {
        return { at: now, event, heardAt }
      }

      now += FRAME_MS
    }
  }

  return { at: now, event: null, heardAt }
}

describe('SpeechEndpointer', () => {
  it('quiet room: a sentence, then the pause ends the turn', () => {
    const endpointer = new SpeechEndpointer(OPTIONS, 0)

    const result = run(endpointer, [
      [0.01, 500], // room
      [0.35, 1_500], // talking
      [0.01, 2_000] // quiet again
    ])

    expect(result.heardAt).not.toBeNull()
    expect(result.heardAt!).toBeGreaterThanOrEqual(500)
    expect(result.heardAt!).toBeLessThan(700)
    expect(result.event).toBe('end')
    // The turn ends silenceMs after the last word, not later.
    expect(result.at).toBeGreaterThanOrEqual(2_000 + OPTIONS.silenceMs)
    expect(result.at).toBeLessThan(2_000 + OPTIONS.silenceMs + 100)
  })

  it('noisy room: noise above the fixed threshold is not a word, and the pause after speech still ends the turn', () => {
    // A fan / mic boost at 0.10 — above the old fixed 0.075 threshold, which
    // used to mean "speech" forever.
    const endpointer = new SpeechEndpointer(OPTIONS, 0)

    const result = run(endpointer, [
      [0.1, 1_000], // noise only
      [0.4, 1_200], // talking over it
      [0.1, 2_000] // noise only again
    ])

    expect(result.heardAt!).toBeGreaterThanOrEqual(1_000)
    expect(result.heardAt!).toBeLessThan(1_200)
    expect(result.event).toBe('end')
    expect(result.at).toBeLessThan(2_200 + OPTIONS.silenceMs + 100)
    expect(endpointer.trigger).toBeGreaterThan(0.1)
    expect(endpointer.release).toBeGreaterThan(0.1)
  })

  it('noisy room with nobody talking: gives up as idle instead of hearing the noise as speech', () => {
    const endpointer = new SpeechEndpointer(OPTIONS, 0)

    const result = run(endpointer, [[0.1, 13_000]])

    expect(result.heardAt).toBeNull()
    expect(result.event).toBe('idle')
    expect(result.at).toBeGreaterThanOrEqual(OPTIONS.idleSilenceMs)
  })

  it('a click is not a word; a sustained level is', () => {
    const endpointer = new SpeechEndpointer(OPTIONS, 0)

    run(endpointer, [
      [0.01, 500],
      [0.6, FRAME_MS * 2], // two loud frames
      [0.01, 500]
    ])
    expect(endpointer.heardSpeech).toBe(false)

    run(endpointer, [[0.3, 200]])
    expect(endpointer.heardSpeech).toBe(true)
  })

  it('a word spoken in the first instant is still caught, and does not become the floor', () => {
    const endpointer = new SpeechEndpointer(OPTIONS, 0)

    const result = run(endpointer, [
      [0.4, CALIBRATION_MS + 400], // talking from the very first frame
      [0.01, 2_000]
    ])

    expect(result.heardAt!).toBeLessThan(CALIBRATION_MS)
    expect(endpointer.noiseFloor).toBeLessThan(0.02)
    expect(result.event).toBe('end')
  })

  it('the trigger never climbs out of reach of speech', () => {
    const endpointer = new SpeechEndpointer(OPTIONS, 0)

    run(endpointer, [[0.5, 3_000]]) // a very loud room
    expect(endpointer.trigger).toBeLessThanOrEqual(TRIGGER_CEILING)
    expect(endpointer.trigger).toBeLessThan(0.3)
  })

  it('caps a turn once speech began, however loud the room stays', () => {
    const endpointer = new SpeechEndpointer({ ...OPTIONS, maxSpeechMs: 5_000 }, 0)

    const result = run(endpointer, [
      [0.01, 300],
      [0.4, 20_000] // never quiet again
    ])

    expect(result.event).toBe('end')
    expect(result.at).toBeGreaterThanOrEqual(300 + 5_000)
    expect(result.at).toBeLessThan(300 + 5_000 + 200)
  })
})
