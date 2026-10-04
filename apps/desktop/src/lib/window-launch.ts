/**
 * Is this page load a fresh LAUNCH of the window (the app just started, or a
 * new window opened), or a RELOAD of the same window (⌘R, renderer crash
 * recovery, a runtime-profile switch)?
 *
 * A launch opens on a clean new chat; a reload lands back where it was.
 * sessionStorage lives exactly as long as the window: Electron starts every
 * new window with it empty and keeps it across reloads and same-window
 * navigations. The answer is latched on the first call of the page load, so
 * every caller (the route restore, the composer's draft store) sees the same
 * decision.
 *
 * Dependency-free on purpose: both stores import it, so it must not import
 * either of them.
 */
const WINDOW_BOOTED_KEY = 'robo.desktop.window-booted'

let freshWindowLaunch: boolean | null = null

/**
 * Read-and-mark against a window-scoped storage: true when this window had not
 * booted before. No usable storage (restricted context) answers false — keep
 * the remembered-state behaviour rather than guess.
 */
export function markWindowBooted(storage: null | Pick<Storage, 'getItem' | 'setItem'> | undefined): boolean {
  try {
    if (!storage) {
      return false
    }

    const fresh = storage.getItem(WINDOW_BOOTED_KEY) === null
    storage.setItem(WINDOW_BOOTED_KEY, '1')

    return fresh
  } catch {
    return false
  }
}

function windowStorage(): null | Storage {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

/**
 * Decide and MARK: the window counts as booted from here on, so its next
 * reload restores. Called by the route restore once it has acted on the
 * answer; a reload before that (a boot-failure "Reload", say) is still a
 * launch.
 */
export function isFreshWindowLaunch(): boolean {
  if (freshWindowLaunch === null) {
    freshWindowLaunch = markWindowBooted(windowStorage())
  }

  return freshWindowLaunch
}

/**
 * The same answer without marking the window — for module-init readers (the
 * composer's draft store) that run long before the route restore.
 */
export function peekFreshWindowLaunch(): boolean {
  if (freshWindowLaunch !== null) {
    return freshWindowLaunch
  }

  try {
    const storage = windowStorage()

    return storage ? storage.getItem(WINDOW_BOOTED_KEY) === null : false
  } catch {
    return false
  }
}

/** @internal Forget the latched launch decision (tests only). */
export function _resetFreshWindowLaunchForTests(): void {
  freshWindowLaunch = null
}
