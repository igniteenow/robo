import { useEffect } from 'react'

import { idleScheduler, prewarm, type PrewarmLoader, type PrewarmScheduler } from '@/lib/prewarm'
import { $desktopBoot, type DesktopBootState } from '@/store/boot'
import { isSecondaryWindow } from '@/store/windows'

/**
 * The overlay and page views are lazy chunks, so the first visit to Settings,
 * the Command Center or Capabilities after launch paid a chunk load — fetch,
 * parse, evaluate — before anything appeared, and on a slow machine that is
 * the "takes a while to get there" between features. Once the cold boot has
 * settled, this fetches those chunks one at a time in idle slots so the first
 * click finds them already evaluated. Each loader is the same `import()` the
 * lazy views use, so the bundler shares one chunk between the two.
 *
 * Primary and peer app windows only; a session window has no sidebar to reach
 * these from and stays lean.
 */

// Most-reached first.
const VIEW_LOADERS: readonly PrewarmLoader[] = [
  () => import('../../settings'),
  () => import('../../command-center'),
  () => import('../../skills'),
  () => import('../../messaging'),
  () => import('../../artifacts'),
  () => import('../../agents'),
  () => import('../../cron'),
  () => import('../../profiles'),
  () => import('../../webhooks'),
  () => import('../../starmap')
]

// Leave the freshly booted app alone for a moment (sidebar fill, first
// keystrokes), then take idle slots; the timeout keeps a never-idle machine
// from waiting forever.
export const PREWARM_AFTER_BOOT_MS = 2500
const IDLE_TIMEOUT_MS = 8000

/** The cold boot is over and the shell is interactive. */
export function bootSettled(boot: Pick<DesktopBootState, 'error' | 'progress' | 'running'>): boolean {
  return !boot.running && boot.progress >= 100 && !boot.error
}

export interface PrewarmViewsOptions {
  loaders?: readonly PrewarmLoader[]
  schedule?: PrewarmScheduler
}

export function usePrewarmViews({ loaders = VIEW_LOADERS, schedule }: PrewarmViewsOptions = {}): void {
  useEffect(() => {
    if (isSecondaryWindow()) {
      return
    }

    let started = false
    let timer: number | null = null
    let cancelPrewarm: (() => void) | null = null
    let unsubscribe: (() => void) | null = null

    // Runs once, on the first settled boot; later boot-state churn (a reconnect
    // re-completing the boot) must not queue a second pass.
    const onBoot = (boot: DesktopBootState) => {
      if (started || !bootSettled(boot)) {
        return
      }

      started = true
      timer = window.setTimeout(() => {
        timer = null
        unsubscribe?.()
        unsubscribe = null
        cancelPrewarm = prewarm(loaders, schedule ?? idleScheduler(IDLE_TIMEOUT_MS))
      }, PREWARM_AFTER_BOOT_MS)
    }

    unsubscribe = $desktopBoot.subscribe(onBoot)

    return () => {
      unsubscribe?.()

      if (timer !== null) {
        window.clearTimeout(timer)
      }

      cancelPrewarm?.()
    }
  }, [loaders, schedule])
}
