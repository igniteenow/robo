/**
 * speech-endpointer.ts — when does a spoken turn start, and when is it over?
 *
 * The mic level meter used to compare against ONE fixed threshold: speech
 * while the level was above it, silence below. That is right in a quiet room
 * and wrong everywhere else. A fan, a laptop's own noise, a Windows mic with
 * its boost turned up all sit ABOVE the fixed threshold, so after the first
 * word the "silence" that ends the turn never comes: Listening… for the whole
 * 60 s cap, then a minute of noise sent to the transcriber, which finds no
 * words in it. That was the "it keeps listening while I talk and never
 * catches what I said" voice chat.
 *
 * This endpointer learns the room instead:
 *
 * - The noise FLOOR is a low percentile of recent quiet levels — the room
 *   between words. The first CALIBRATION_MS of a turn feed it unconditionally
 *   (there is no floor to compare with yet); after that, every sub-trigger
 *   sample keeps it tracking until speech begins, and then it holds — speech
 *   must never raise it.
 * - Speech TRIGGERS at max(minLevel, floor × 3), capped so speech always
 *   stays reachable over a loud room, and only after a short sustained run —
 *   a click or one loud frame is not a word. While calibrating, only a
 *   clearly loud level counts, so a word spoken in the first instant is still
 *   caught and a noisy room is not mistaken for one.
 * - The turn RELEASES (silence starts counting) below max(minLevel,
 *   floor × 1.8): in a noisy room that is above the noise, so the pause after
 *   the last word is heard as a pause. `silenceMs` of it ends the turn.
 * - A turn ends anyway after `maxSpeechMs` of speech (or noise that passed
 *   for it), and gives up after `idleSilenceMs` with no speech at all.
 *
 * Pure and clock-free (the caller passes `now`), so it is unit-tested with
 * synthetic level traces rather than a microphone.
 */

export interface SpeechEndpointerOptions {
  /** Absolute floor for the speech trigger and the release level (0..1). */
  minLevel: number
  /** Quiet after speech that ends the turn (ms). */
  silenceMs: number
  /** No speech at all for this long → give up (ms; 0 = never). */
  idleSilenceMs: number
  /** A turn ends this long after speech began, whatever the level (ms; 0 = never). */
  maxSpeechMs: number
}

/** 'end': the turn is over (speech was heard). 'idle': nothing was said. */
export type SpeechEndpointEvent = 'end' | 'idle' | null

/** Every sample feeds the floor for this long after the turn starts. */
export const CALIBRATION_MS = 300
/** Quiet samples that make up the floor (~2 s at display cadence). */
const FLOOR_WINDOW = 120
/** The floor is this percentile of the window: the room between words. */
const FLOOR_PERCENTILE = 0.25
/** Floor cap → trigger cap: speech must stay reachable over loud rooms. */
const FLOOR_CAP = 0.08
const TRIGGER_MULTIPLIER = 3
const RELEASE_MULTIPLIER = 1.8
/** The highest the trigger can go; also what counts as speech while calibrating. */
export const TRIGGER_CEILING = FLOOR_CAP * TRIGGER_MULTIPLIER
/** Above-trigger run that counts as a word starting. */
const ONSET_MS = 60

export class SpeechEndpointer {
  heardSpeech = false

  private readonly options: SpeechEndpointerOptions
  private readonly startedAt: number
  private readonly floorSamples: number[] = []
  private floor = 0
  private onsetSince: null | number = null
  private speechStartedAt = 0
  private silenceSince: null | number = null

  constructor(options: SpeechEndpointerOptions, startedAt: number) {
    this.options = options
    this.startedAt = startedAt
  }

  /** Level that starts a word. */
  get trigger(): number {
    return Math.min(TRIGGER_CEILING, Math.max(this.options.minLevel, this.floor * TRIGGER_MULTIPLIER))
  }

  /** Level below which the pause after speech counts as silence. */
  get release(): number {
    return Math.min(this.trigger, Math.max(this.options.minLevel, this.floor * RELEASE_MULTIPLIER))
  }

  /** The learned room noise level. */
  get noiseFloor(): number {
    return this.floor
  }

  /** Feed one level sample (0..1) at time `now`. */
  feed(level: number, now: number): SpeechEndpointEvent {
    if (!this.heardSpeech) {
      const calibrating = now - this.startedAt < CALIBRATION_MS

      // While calibrating, anything short of clearly-loud is the room (a
      // word spoken in the first instant must not become the floor).
      if (calibrating ? level < TRIGGER_CEILING : level < this.trigger) {
        this.pushFloorSample(level)
      }

      const onsetLevel = calibrating ? TRIGGER_CEILING : this.trigger

      if (level >= onsetLevel) {
        this.onsetSince ??= now

        if (now - this.onsetSince >= ONSET_MS) {
          this.heardSpeech = true
          this.speechStartedAt = this.onsetSince
          this.silenceSince = null
        }
      } else {
        this.onsetSince = null
      }

      if (!this.heardSpeech) {
        return this.options.idleSilenceMs > 0 && now - this.startedAt >= this.options.idleSilenceMs ? 'idle' : null
      }
    }

    if (level >= this.release) {
      this.silenceSince = null
    } else {
      this.silenceSince ??= now

      if (this.options.silenceMs > 0 && now - this.silenceSince >= this.options.silenceMs) {
        return 'end'
      }
    }

    if (this.options.maxSpeechMs > 0 && now - this.speechStartedAt >= this.options.maxSpeechMs) {
      return 'end'
    }

    return null
  }

  private pushFloorSample(level: number): void {
    this.floorSamples.push(level)

    if (this.floorSamples.length > FLOOR_WINDOW) {
      this.floorSamples.shift()
    }

    const sorted = [...this.floorSamples].sort((a, b) => a - b)
    const index = Math.min(sorted.length - 1, Math.floor(sorted.length * FLOOR_PERCENTILE))

    this.floor = Math.min(FLOOR_CAP, sorted[index] ?? 0)
  }
}
