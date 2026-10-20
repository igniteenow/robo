/**
 * Run a list of loaders one at a time, each in its own scheduled slot, so a
 * batch of chunk loads (parse + evaluate, each a long task) never lands in one
 * go and never races the user. The returned function cancels whatever has not
 * started yet; a loader that is already running finishes on its own.
 */

export type PrewarmLoader = () => Promise<unknown> | unknown

/** Schedule `run` for later; returns a function that un-schedules it. */
export type PrewarmScheduler = (run: () => void) => () => void

export function prewarm(loaders: readonly PrewarmLoader[], schedule: PrewarmScheduler): () => void {
  let cancelled = false
  let unschedule: (() => void) | null = null

  const step = (index: number) => {
    if (cancelled || index >= loaders.length) {
      return
    }

    unschedule = schedule(() => {
      unschedule = null

      if (cancelled) {
        return
      }

      let loading: Promise<unknown>

      try {
        loading = Promise.resolve(loaders[index]())
      } catch {
        loading = Promise.resolve()
      }

      // A chunk that fails to load is the lazy view's problem at open time
      // (its own Suspense/error path); prewarming just moves on.
      void loading.catch(() => undefined).then(() => step(index + 1))
    })
  }

  step(0)

  return () => {
    cancelled = true
    unschedule?.()
    unschedule = null
  }
}

/**
 * Idle-time scheduler: `requestIdleCallback` where the window has it, with a
 * timeout so a busy machine still gets there, and a plain timer elsewhere
 * (jsdom, older runtimes).
 */
export function idleScheduler(timeoutMs: number): PrewarmScheduler {
  return run => {
    const w = window as Window & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number
      cancelIdleCallback?: (handle: number) => void
    }

    if (typeof w.requestIdleCallback === 'function') {
      const handle = w.requestIdleCallback(run, { timeout: timeoutMs })

      return () => w.cancelIdleCallback?.(handle)
    }

    const handle = window.setTimeout(run, 250)

    return () => window.clearTimeout(handle)
  }
}
