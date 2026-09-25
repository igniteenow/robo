import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setVoicePlaybackState } from './voice-playback'
import {
  $voiceTurnTiming,
  describeVoiceTiming,
  markVoiceTurn,
  resetVoiceTiming,
  setVoicePlaybackMode
} from './voice-timing'

// Every spoken turn comes with numbers: you stop → words back → first reply
// text → first sound. "It lags" then says where.

beforeEach(() => {
  resetVoiceTiming()
  vi.spyOn(console, 'info').mockImplementation(() => undefined)
})

afterEach(() => {
  resetVoiceTiming()
  vi.restoreAllMocks()
})

describe('voice timing', () => {
  it('describes a turn stage by stage, in seconds', () => {
    markVoiceTurn('listening', 0)
    markVoiceTurn('heard', 1_000)
    markVoiceTurn('transcribed', 2_200)
    markVoiceTurn('submitted', 2_250)
    markVoiceTurn('firstText', 5_000)
    setVoicePlaybackMode('sentence')
    markVoiceTurn('firstAudio', 5_700)

    expect(describeVoiceTiming($voiceTurnTiming.get())).toBe(
      'words 1.2 s · first word 2.8 s · voice 0.7 s · total 4.7 s · sentence by sentence'
    )
  })

  it('says nothing before the turn has anything to say, and grows as it goes', () => {
    expect(describeVoiceTiming($voiceTurnTiming.get())).toBeNull()

    markVoiceTurn('heard', 0)
    expect(describeVoiceTiming($voiceTurnTiming.get())).toBeNull()

    markVoiceTurn('transcribed', 900)
    expect(describeVoiceTiming($voiceTurnTiming.get())).toBe('words 0.9 s')
  })

  it('starts a fresh turn on "heard" and keeps the first of each later mark', () => {
    markVoiceTurn('heard', 0)
    markVoiceTurn('firstText', 100)
    markVoiceTurn('firstText', 900)
    expect($voiceTurnTiming.get().marks.firstText).toBe(100)

    markVoiceTurn('heard', 5_000)
    expect($voiceTurnTiming.get().marks).toEqual({ heard: 5_000, listening: undefined })
    expect($voiceTurnTiming.get().playback).toBeNull()
  })

  it('names how the audio arrived — and flags the old whole-reply path', () => {
    markVoiceTurn('heard', 0)
    markVoiceTurn('transcribed', 500)
    setVoicePlaybackMode('whole')
    expect(describeVoiceTiming($voiceTurnTiming.get())).toBe('words 0.5 s · whole reply at once')

    setVoicePlaybackMode('pcm')
    expect(describeVoiceTiming($voiceTurnTiming.get())).toContain('streamed')
  })

  it('takes the first sound from the playback store, for the voice chat only', () => {
    markVoiceTurn('heard', 0)
    setVoicePlaybackState({
      audioElement: null,
      messageId: null,
      sequence: 1,
      source: 'read-aloud',
      status: 'speaking'
    })
    expect($voiceTurnTiming.get().marks.firstAudio).toBeUndefined()

    setVoicePlaybackState({
      audioElement: null,
      messageId: null,
      sequence: 2,
      source: 'voice-conversation',
      status: 'speaking'
    })
    expect($voiceTurnTiming.get().marks.firstAudio).toBeTypeOf('number')
  })
})
