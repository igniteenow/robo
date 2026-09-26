import { describe, expect, it } from 'vitest'

import { VAD_FRAME_MS, VoiceActivityDetector, type VoiceActivityEvent } from './voice-activity'

// Synthetic level traces, one 20 ms frame at a time. Each case is a room and a
// speaker; the assertions are when speech is confirmed and when it ends.

type Segment = [db: number | number[], ms: number, playing?: boolean]

interface Timeline {
  events: { at: number; event: Exclude<VoiceActivityEvent, null> }[]
  first: (event: Exclude<VoiceActivityEvent, null>) => number | undefined
}

// Speech is not flat: syllables, and short dips between them.
const SYLLABLES = [0, 3, -2, -8, 2, -4, 1, -14, 0, 2, -3, -20]

const talk = (base: number): number[] => SYLLABLES.map(offset => base + offset)

function run(detector: VoiceActivityDetector, segments: Segment[]): Timeline {
  const events: Timeline['events'] = []
  let now = 0

  for (const [db, ms, playing = false] of segments) {
    const levels = Array.isArray(db) ? db : [db]

    for (let elapsed = 0, index = 0; elapsed < ms; elapsed += VAD_FRAME_MS, index += 1) {
      const event = detector.feed(levels[index % levels.length], playing)

      if (event) {
        events.push({ at: now, event })
      }

      now += VAD_FRAME_MS
    }
  }

  return { events, first: name => events.find(entry => entry.event === name)?.at }
}

describe('VoiceActivityDetector', () => {
  it('quiet room: confirms speech within ~200 ms and ends 650 ms after the last word', () => {
    const timeline = run(new VoiceActivityDetector(), [
      [-65, 1_000],
      [talk(-24), 1_500],
      [-65, 1_500]
    ])

    expect(timeline.first('candidate')).toBe(1_000)
    expect(timeline.first('start')).toBeGreaterThanOrEqual(1_000 + 180)
    expect(timeline.first('start')).toBeLessThanOrEqual(1_000 + 300)
    expect(timeline.first('end')).toBeGreaterThanOrEqual(2_500 + 630)
    expect(timeline.first('end')).toBeLessThanOrEqual(2_500 + 700)
    expect(timeline.events.map(entry => entry.event)).toEqual(['candidate', 'start', 'end'])
  })

  it('a click or a cough is not speech', () => {
    const timeline = run(new VoiceActivityDetector(), [
      [-65, 1_000],
      [-15, 20], // click
      [-65, 800],
      [-20, 120], // cough
      [-65, 1_000]
    ])

    expect(timeline.first('start')).toBeUndefined()
    expect(timeline.events.filter(entry => entry.event === 'blip')).toHaveLength(2)
  })

  it('typing — short sparse clicks — never confirms', () => {
    const typing: number[] = []

    for (let index = 0; index < 8; index += 1) {
      typing.push(index === 0 ? -20 : -65)
    }

    const timeline = run(new VoiceActivityDetector(), [
      [-65, 1_000],
      [typing, 4_000]
    ])

    expect(timeline.first('start')).toBeUndefined()
  })

  it('a breath between sentences keeps the turn; a real pause ends it', () => {
    const timeline = run(new VoiceActivityDetector(), [
      [-65, 600],
      [talk(-24), 1_000],
      [-65, 400], // breath
      [talk(-24), 1_000],
      [-65, 1_200]
    ])

    expect(timeline.events.map(entry => entry.event)).toEqual(['candidate', 'start', 'end'])
    expect(timeline.first('end')).toBeGreaterThanOrEqual(3_000 + 630)
  })

  it('a lone click in the pause does not restart the count; two voiced frames do', () => {
    const clicked = run(new VoiceActivityDetector(), [
      [-65, 600],
      [talk(-24), 800],
      [-65, 300],
      [-20, 20],
      [-65, 1_000]
    ])

    expect(clicked.first('end')).toBeLessThanOrEqual(1_400 + 700)

    const resumed = run(new VoiceActivityDetector(), [
      [-65, 600],
      [talk(-24), 800],
      [-65, 300],
      [-20, 40],
      [-65, 1_000]
    ])

    expect(resumed.first('end')).toBeGreaterThanOrEqual(1_400 + 340 + 630)
  })

  it('noisy room: steady noise is the floor, and the pause after speech is still heard', () => {
    const detector = new VoiceActivityDetector()

    const timeline = run(detector, [
      [-40, 2_000], // fan
      [talk(-14), 1_200],
      [-40, 1_500]
    ])

    expect(detector.floorDb).toBeGreaterThan(-45)
    expect(timeline.first('start')).toBeGreaterThanOrEqual(2_000)
    // (The last syllable's own dip already counts toward the pause.)
    expect(timeline.first('end')).toBeGreaterThanOrEqual(3_200 + 600)
    expect(timeline.first('end')).toBeLessThanOrEqual(3_200 + 700)
  })

  it('a fan switching on is learned within seconds instead of reading as endless speech', () => {
    const detector = new VoiceActivityDetector()

    const timeline = run(detector, [
      [-65, 1_000],
      [[-42, -41, -43], 10_000]
    ])

    // At most one short false utterance while the floor catches up — then quiet.
    expect(timeline.events.filter(entry => entry.event === 'start').length).toBeLessThanOrEqual(1)

    const ended = timeline.first('end')

    if (timeline.first('start') !== undefined) {
      expect(ended).toBeDefined()
      expect(ended!).toBeLessThan(1_000 + 5_000)
    }

    expect(timeline.events.filter(entry => entry.at > 7_000)).toEqual([])
  })

  it("Robo's own echo while it talks does not count as the user", () => {
    const timeline = run(new VoiceActivityDetector(), [
      [-65, 1_000],
      // The reply leaks back ~25 dB above the room after echo cancellation.
      [talk(-40), 6_000, true]
    ])

    expect(timeline.first('start')).toBeUndefined()
  })

  it('the user talking over the reply is confirmed within ~300 ms', () => {
    const detector = new VoiceActivityDetector()

    const timeline = run(detector, [
      [-65, 1_000],
      [talk(-40), 2_000, true],
      [talk(-18), 1_000, true]
    ])

    const start = timeline.first('start')

    expect(start).toBeDefined()
    expect(start!).toBeGreaterThanOrEqual(3_000 + 280)
    expect(start!).toBeLessThanOrEqual(3_000 + 450)
    expect(detector.startedDuringPlayback).toBe(true)
  })

  it('nothing is confirmed in the first moments of a reply while the echo is learned', () => {
    const timeline = run(new VoiceActivityDetector(), [
      [-65, 1_000],
      [talk(-18), 400, true]
    ])

    expect(timeline.first('start')).toBeUndefined()
  })

  it('an utterance that never pauses is cut at the length cap', () => {
    const timeline = run(new VoiceActivityDetector({ maxUtteranceMs: 5_000 }), [
      [-65, 500],
      [talk(-20), 7_000]
    ])

    expect(timeline.first('max')).toBeGreaterThanOrEqual(500 + 4_980)
    expect(timeline.first('max')).toBeLessThanOrEqual(500 + 5_020)
  })

  it("a stream's opening digital silence does not set the floor", () => {
    // A fresh stream delivers zeros before the microphone's audio arrives;
    // taking them for the room made the room itself read as speech.
    const timeline = run(new VoiceActivityDetector(), [
      [-120, 300],
      [[-48, -47, -49], 3_000]
    ])

    expect(timeline.first('start')).toBeUndefined()
  })

  it('tracks voiced time and length of the utterance', () => {
    const detector = new VoiceActivityDetector()

    run(detector, [
      [-65, 500],
      [-24, 1_000],
      [-65, 700]
    ])

    expect(detector.speechMs).toBe(1_000)
    expect(detector.active).toBe(false)
  })
})
