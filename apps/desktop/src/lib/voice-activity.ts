/**
 * voice-activity.ts — is the user talking, and when have they finished?
 *
 * Fed one 20 ms frame level (dBFS) at a time by the voice chat's capture
 * engine (lib/voice-capture), for as long as the conversation is open. The
 * microphone never closes between turns, so this one detector decides when a
 * turn starts, when it ends, and when the user is talking over Robo.
 *
 * - The noise FLOOR is a low percentile of the last few seconds of levels —
 *   the room between words. It keeps tracking all the time, so a fan that
 *   switches on raises it within seconds instead of reading as one endless
 *   sentence (the old endpointer only learned the room once per turn).
 * - A word STARTS at floor + 15 dB. A single loud frame (a click, a tap) is
 *   only a candidate: speech is confirmed once most of a short window is
 *   voiced — 200 ms of it normally, 300 ms while Robo is talking.
 * - While Robo's reply is audible the trigger also clears its residual echo
 *   (what the echo canceller leaves of it), learned from the playback itself,
 *   so Robo does not interrupt itself.
 * - The utterance ENDS after `endSilenceMs` below floor + 9 dB. A lone click
 *   in that pause does not restart the count; two voiced frames in a row do.
 *
 * Pure and clock-free: time is counted in frames, so it is unit-tested with
 * synthetic level traces.
 */

/** Length of one frame fed to the detector, in ms. */
export const VAD_FRAME_MS = 20

export interface VoiceActivityOptions {
  /** Voiced time that confirms speech has started (ms). */
  startConfirmMs: number
  /** The same while Robo's reply is audible (ms). */
  playbackStartConfirmMs: number
  /** Quiet after speech that ends the utterance (ms). */
  endSilenceMs: number
  /** An utterance ends this long after it began, whatever the level (ms). */
  maxUtteranceMs: number
}

export const DEFAULT_VOICE_ACTIVITY: VoiceActivityOptions = {
  endSilenceMs: 650,
  maxUtteranceMs: 30_000,
  playbackStartConfirmMs: 300,
  startConfirmMs: 200
}

/**
 * - `candidate`: a voiced frame; speech may be starting (keep its audio).
 * - `start`: speech confirmed.
 * - `blip`: the candidate faded before it was confirmed (a click, a cough).
 * - `end`: the pause after speech ended the utterance.
 * - `max`: the utterance ran for `maxUtteranceMs` and was cut.
 */
export type VoiceActivityEvent = 'blip' | 'candidate' | 'end' | 'max' | 'start' | null

/** Level history the floor is taken from: ~3 s of frames. */
const FLOOR_WINDOW = 150
/** The floor is this percentile of the window — the quiet between words. */
const FLOOR_PERCENTILE = 0.05
/** At or below this a frame is digital silence (a stream starting up), not a room. */
const NO_SIGNAL_DB = -90
/** The first frame seeds the window, clamped into this range. */
const SEED_FLOOR_MIN_DB = -75
const SEED_FLOOR_MAX_DB = -40
const SEED_FRAMES = 10

const START_MARGIN_DB = 15
const RELEASE_MARGIN_DB = 9
/** Bounds on the start threshold: sensitive in a quiet room, reachable in a loud one. */
const START_MIN_DB = -55
const START_MAX_DB = -22
const RELEASE_MIN_DB = -62

/** Confirmation window = confirm time × this: "most of a short window". */
const CONFIRM_WINDOW_FACTOR = 1.5
/** An onset that has not confirmed by now is not speech starting. */
const ONSET_MAX_MS = 1_000
/** Consecutive voiced frames that break a pause after speech. */
const RESUME_FRAMES = 2

/** Echo: a high percentile of recent playback levels, over ~1.5 s. */
const ECHO_WINDOW = 75
const ECHO_PERCENTILE = 0.9
const ECHO_MARGIN_DB = 8
/** Speech over playback must still be reachable when the echo is loud. */
const PLAYBACK_START_MAX_DB = -18
/** Each reply's first moments only teach the echo (the canceller is settling). */
const PLAYBACK_GRACE_MS = 500
/** Playback that resumes after less than this is the same reply (no new grace). */
const PLAYBACK_GAP_MS = 1_000

type Phase = 'onset' | 'quiet' | 'speech'

function percentile(values: Float32Array, count: number, share: number): number {
  const sorted = Array.from(values.subarray(0, count)).sort((a, b) => a - b)

  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * share))] ?? 0
}

/** Fixed-size window of recent levels; `values()` in no particular order. */
class LevelWindow {
  private readonly data: Float32Array
  private next = 0
  private filled = 0

  constructor(size: number) {
    this.data = new Float32Array(size)
  }

  get size(): number {
    return this.filled
  }

  push(value: number): void {
    this.data[this.next] = value
    this.next = (this.next + 1) % this.data.length
    this.filled = Math.min(this.data.length, this.filled + 1)
  }

  percentile(share: number): number {
    return percentile(this.data, this.filled, share)
  }
}

export class VoiceActivityDetector {
  private readonly options: VoiceActivityOptions
  private readonly levels = new LevelWindow(FLOOR_WINDOW)
  private readonly echo = new LevelWindow(ECHO_WINDOW)
  private phase: Phase = 'quiet'
  private floor = SEED_FLOOR_MAX_DB
  private echoLevel: null | number = null
  /** Voiced flags of the onset's recent frames (the confirmation window). */
  private onsetVoiced: boolean[] = []
  /** Levels heard during an onset over playback — echo, if it fizzles. */
  private onsetLevels: number[] = []
  private framesSinceVoiced = 0
  private utteranceFrames = 0
  private voicedFrames = 0
  private silentFrames = 0
  private loudRun = 0
  private playingFrames = 0
  private notPlayingFrames = Number.POSITIVE_INFINITY
  private onsetDuringPlayback = false

  constructor(options: Partial<VoiceActivityOptions> = {}) {
    this.options = { ...DEFAULT_VOICE_ACTIVITY, ...options }
  }

  /** The learned room noise (dBFS). */
  get floorDb(): number {
    return this.floor
  }

  /** Level that starts a word right now (dBFS). */
  get startDb(): number {
    return this.startThreshold(this.playingFrames > 0)
  }

  /** Level below which the pause after speech counts as silence (dBFS). */
  get releaseDb(): number {
    return Math.min(this.startThreshold(false) - 3, Math.max(RELEASE_MIN_DB, this.floor + RELEASE_MARGIN_DB))
  }

  /** Residual echo of Robo's own voice, when learned (dBFS). */
  get echoDb(): null | number {
    return this.echoLevel
  }

  /** Speech is confirmed and not over yet. */
  get speaking(): boolean {
    return this.phase === 'speech'
  }

  /** A candidate or confirmed utterance is in progress. */
  get active(): boolean {
    return this.phase !== 'quiet'
  }

  /** Voiced time of the current (or just-ended) utterance, ms. */
  get speechMs(): number {
    return this.voicedFrames * VAD_FRAME_MS
  }

  /** Length of the current (or just-ended) utterance, ms. */
  get utteranceMs(): number {
    return this.utteranceFrames * VAD_FRAME_MS
  }

  /** The current utterance began while Robo was audible. */
  get startedDuringPlayback(): boolean {
    return this.onsetDuringPlayback
  }

  /** Abandon the utterance in progress (it was flushed or discarded). */
  reset(): void {
    this.phase = 'quiet'
    this.onsetVoiced = []
    this.onsetLevels = []
    this.silentFrames = 0
    this.loudRun = 0
  }

  /**
   * Feed one frame's level. `playing` is whether Robo's reply is audible
   * during this frame.
   */
  feed(db: number, playing: boolean): VoiceActivityEvent {
    const level = Number.isFinite(db) ? db : -100

    this.trackFloor(level)
    const inGrace = this.trackPlayback(level, playing)
    const voiced = level >= this.startThreshold(playing) && !inGrace

    if (this.phase === 'quiet') {
      if (!voiced) {
        return null
      }

      this.phase = 'onset'
      this.onsetDuringPlayback = playing
      this.onsetVoiced = [true]
      this.onsetLevels = playing ? [level] : []
      this.framesSinceVoiced = 0
      this.utteranceFrames = 1
      this.voicedFrames = 1

      return 'candidate'
    }

    this.utteranceFrames += 1
    this.voicedFrames += voiced ? 1 : 0

    if (this.phase === 'onset') {
      return this.feedOnset(level, voiced, playing)
    }

    if (this.utteranceFrames * VAD_FRAME_MS >= this.options.maxUtteranceMs) {
      this.reset()

      return 'max'
    }

    return this.feedSpeech(level)
  }

  private feedOnset(level: number, voiced: boolean, playing: boolean): VoiceActivityEvent {
    const confirmMs = this.onsetDuringPlayback || playing ? this.options.playbackStartConfirmMs : this.options.startConfirmMs
    const needed = Math.max(1, Math.round(confirmMs / VAD_FRAME_MS))
    const windowFrames = Math.max(needed, Math.round(needed * CONFIRM_WINDOW_FACTOR))

    this.onsetVoiced.push(voiced)

    if (this.onsetVoiced.length > windowFrames) {
      this.onsetVoiced.shift()
    }

    if (playing) {
      this.onsetLevels.push(level)
    }

    this.framesSinceVoiced = voiced ? 0 : this.framesSinceVoiced + 1

    if (this.onsetVoiced.filter(Boolean).length >= needed) {
      this.phase = 'speech'
      this.onsetLevels = []
      this.silentFrames = 0
      this.loudRun = 0

      return 'start'
    }

    if (this.framesSinceVoiced >= windowFrames) {
      // It faded: a click, a cough — or Robo's own echo, which the echo
      // estimate should have covered. Teach it, so the next one does not.
      this.onsetLevels.forEach(value => this.echo.push(value))

      if (this.onsetLevels.length) {
        this.echoLevel = this.echo.percentile(ECHO_PERCENTILE)
      }

      this.reset()

      return 'blip'
    }

    if (this.utteranceFrames * VAD_FRAME_MS >= ONSET_MAX_MS) {
      // Sparse sound that never fills the window (typing, tapping): drop it,
      // so a real word after it starts its own utterance.
      this.reset()

      return 'blip'
    }

    return null
  }

  private feedSpeech(level: number): VoiceActivityEvent {
    if (level >= this.releaseDb) {
      this.loudRun += 1

      if (this.loudRun >= RESUME_FRAMES) {
        this.silentFrames = 0
      } else if (this.silentFrames > 0) {
        this.silentFrames += 1 // one loud frame in a pause is a click, not a word
      }
    } else {
      this.loudRun = 0
      this.silentFrames += 1
    }

    if (this.silentFrames * VAD_FRAME_MS >= this.options.endSilenceMs) {
      this.reset()

      return 'end'
    }

    return null
  }

  private trackFloor(level: number): void {
    if (level <= NO_SIGNAL_DB) {
      return // digital silence: the stream is starting up, not the room
    }

    if (this.levels.size === 0) {
      const seed = Math.min(SEED_FLOOR_MAX_DB, Math.max(SEED_FLOOR_MIN_DB, level))

      for (let index = 0; index < SEED_FRAMES; index += 1) {
        this.levels.push(seed)
      }
    }

    this.levels.push(level)
    this.floor = Math.max(SEED_FLOOR_MIN_DB, this.levels.percentile(FLOOR_PERCENTILE))
  }

  /** Learn Robo's echo while it talks; true during a reply's settling moments. */
  private trackPlayback(level: number, playing: boolean): boolean {
    if (!playing) {
      this.playingFrames = 0
      this.notPlayingFrames += 1

      return false
    }

    if (this.playingFrames === 0 && this.notPlayingFrames * VAD_FRAME_MS < PLAYBACK_GAP_MS) {
      // A short gap between sentences: the same reply carries on.
      this.playingFrames = Math.ceil(PLAYBACK_GRACE_MS / VAD_FRAME_MS)
    }

    this.playingFrames += 1
    this.notPlayingFrames = 0

    const inGrace = this.playingFrames * VAD_FRAME_MS <= PLAYBACK_GRACE_MS

    // Only the room's own sound teaches the echo: never the user's speech.
    if (inGrace || this.phase === 'quiet') {
      this.echo.push(level)
      this.echoLevel = this.echo.percentile(ECHO_PERCENTILE)
    }

    return inGrace
  }

  private startThreshold(playing: boolean): number {
    const base = Math.min(START_MAX_DB, Math.max(START_MIN_DB, this.floor + START_MARGIN_DB))

    if (!playing || this.echoLevel === null) {
      return base
    }

    return Math.min(PLAYBACK_START_MAX_DB, Math.max(base, this.echoLevel + ECHO_MARGIN_DB))
  }
}
