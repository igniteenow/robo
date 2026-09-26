// Timer cadence for the dictation level meter (use-mic-recorder).
//
// It used to run on requestAnimationFrame. rAF only fires when the window
// paints, and a minimized or fully covered window paints nothing, so the
// meter froze whenever the user looked at another app. A plain interval keeps
// sampling whether or not the window is on screen. (The voice chat's capture
// engine, lib/voice-capture, is driven by the audio itself instead.)

export const AUDIO_TICK_MS = 30

/**
 * Run `tick` now and then every `intervalMs` until it returns `false` or the
 * returned stop function is called. Stopping is idempotent.
 */
export function startAudioTicker(tick: () => boolean, intervalMs: number = AUDIO_TICK_MS): () => void {
  let handle: null | ReturnType<typeof setInterval> = null
  let stopped = false

  const stop = () => {
    stopped = true

    if (handle !== null) {
      clearInterval(handle)
      handle = null
    }
  }

  if (tick() === false) {
    stop()

    return stop
  }

  handle = setInterval(() => {
    if (stopped) {
      return
    }

    if (tick() === false) {
      stop()
    }
  }, intervalMs)

  return stop
}
