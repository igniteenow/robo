import { atom } from 'nanostores'

import { $voicePlayback } from './voice-playback'

// Where the time goes in a spoken turn, measured from the renderer's own
// clock: you stop talking → your words are back (STT) → the first reply text
// (the model) → the first sound (TTS) → done. Shown under the caption in the
// voice view and logged per turn, so "it lags" always comes with numbers.

export type VoiceTimingMark = 'done' | 'firstAudio' | 'firstText' | 'heard' | 'listening' | 'submitted' | 'transcribed'

/** How the reply's audio arrived: chunked PCM, one file per sentence, or the
 *  whole reply in one go (an older backend, or a provider without streaming). */
export type VoicePlaybackMode = 'pcm' | 'sentence' | 'whole'

export interface VoiceTurnTiming {
  marks: Partial<Record<VoiceTimingMark, number>>
  playback: null | VoicePlaybackMode
}

const EMPTY: VoiceTurnTiming = { marks: {}, playback: null }

export const $voiceTurnTiming = atom<VoiceTurnTiming>(EMPTY)

/** Record a moment of the current turn. `heard` starts a new turn. */
export function markVoiceTurn(mark: VoiceTimingMark, at: number = Date.now()): void {
  const current = $voiceTurnTiming.get()

  if (mark === 'heard') {
    $voiceTurnTiming.set({ marks: { heard: at, listening: current.marks.listening }, playback: null })

    return
  }

  if (current.marks[mark] !== undefined && mark !== 'listening') {
    return // first occurrence wins (first text, first audio)
  }

  $voiceTurnTiming.set({ ...current, marks: { ...current.marks, [mark]: at } })

  if (mark === 'firstAudio') {
    const line = describeVoiceTiming($voiceTurnTiming.get())

    if (line) {
      console.info(`[voice] ${line}`)
    }
  }
}

export function setVoicePlaybackMode(mode: VoicePlaybackMode): void {
  const current = $voiceTurnTiming.get()

  if (current.playback !== mode) {
    $voiceTurnTiming.set({ ...current, playback: mode })
  }
}

export function resetVoiceTiming(): void {
  $voiceTurnTiming.set(EMPTY)
}

const seconds = (ms: number) => `${(Math.max(0, ms) / 1000).toFixed(1)} s`

export interface VoiceTimingCopy {
  firstWord: string
  sentence: string
  streamed: string
  total: string
  voice: string
  whole: string
  words: string
}

export const VOICE_TIMING_COPY_EN: VoiceTimingCopy = {
  firstWord: 'first word',
  sentence: 'sentence by sentence',
  streamed: 'streamed',
  total: 'total',
  voice: 'voice',
  whole: 'whole reply at once',
  words: 'words'
}

/**
 * One line of numbers for the turn so far, e.g.
 * "words 1.2 s · first word 2.8 s · voice 0.7 s · total 4.7 s · sentence by sentence".
 * Null until the turn has anything to say.
 */
export function describeVoiceTiming(
  timing: VoiceTurnTiming,
  copy: VoiceTimingCopy = VOICE_TIMING_COPY_EN
): null | string {
  const { firstAudio, firstText, heard, transcribed } = timing.marks
  const parts: string[] = []

  if (heard !== undefined && transcribed !== undefined) {
    parts.push(`${copy.words} ${seconds(transcribed - heard)}`)
  }

  if (transcribed !== undefined && firstText !== undefined) {
    parts.push(`${copy.firstWord} ${seconds(firstText - transcribed)}`)
  }

  if (firstText !== undefined && firstAudio !== undefined) {
    parts.push(`${copy.voice} ${seconds(firstAudio - firstText)}`)
  }

  if (heard !== undefined && firstAudio !== undefined) {
    parts.push(`${copy.total} ${seconds(firstAudio - heard)}`)
  }

  if (timing.playback === 'sentence') {
    parts.push(copy.sentence)
  } else if (timing.playback === 'pcm') {
    parts.push(copy.streamed)
  } else if (timing.playback === 'whole') {
    parts.push(copy.whole)
  }

  return parts.length ? parts.join(' · ') : null
}

// The first audible sound of a reply is the playback store flipping to
// 'speaking'; listen (not subscribe: no replay of the current value).
$voicePlayback.listen(state => {
  if (state.status === 'speaking' && state.source === 'voice-conversation') {
    markVoiceTurn('firstAudio')
  }
})
