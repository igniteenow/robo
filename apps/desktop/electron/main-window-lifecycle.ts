type MainWindowLike = {
  isDestroyed: () => boolean
}

type EnsureMainWindowOptions<T extends MainWindowLike> = {
  isReady: boolean
  createWindow: () => unknown
  focusWindow: (window: T) => unknown
  focusExisting?: boolean
}

export function ensureMainWindow<T extends MainWindowLike>(
  window: T | null | undefined,
  { isReady, createWindow, focusWindow, focusExisting = true }: EnsureMainWindowOptions<T>
) {
  if (!window || window.isDestroyed()) {
    // a closed electron window stays truthy, so replace it before invoking native methods.
    if (isReady) {
      createWindow()
    }

    return
  }

  if (focusExisting) {
    focusWindow(window)
  }
}

export type WindowShowFallbackReason = 'loaded' | 'timeout'

type WindowShowFallbackOptions = {
  isDestroyed: () => boolean
  isVisible: () => boolean
  show: () => unknown
  delayMs: number
  onFallback?: (reason: WindowShowFallbackReason) => unknown
  setTimer?: (callback: () => void, delayMs: number) => unknown
  clearTimer?: (handle: unknown) => unknown
}

type WindowShowFallback = {
  /** The window was shown or closed: stand down for good. */
  cancel: () => void
  /** Show the window now if nothing has shown it yet (at most once). */
  showNow: (reason: WindowShowFallbackReason) => void
}

/**
 * Safety net for windows created with `show: false` that wait for
 * `ready-to-show` (the first painted frame). On some Linux sessions that event
 * never arrives, which leaves a running app with no window until a second
 * launch pokes it. The window is shown anyway after `delayMs`, or earlier when
 * the caller reports another sign of life through `showNow` (the page finished
 * loading).
 *
 * Call `cancel` once the window has been shown (or closed), so a window the
 * user hid on purpose is never brought back.
 */
export function armWindowShowFallback({
  isDestroyed,
  isVisible,
  show,
  delayMs,
  onFallback,
  setTimer = setTimeout,
  clearTimer = handle => clearTimeout(handle as ReturnType<typeof setTimeout>)
}: WindowShowFallbackOptions): WindowShowFallback {
  let settled = false
  let handle: unknown = null

  const settle = () => {
    if (settled) {
      return false
    }

    settled = true
    clearTimer(handle)

    return true
  }

  const showNow = (reason: WindowShowFallbackReason) => {
    if (!settle() || isDestroyed() || isVisible()) {
      return
    }

    show()
    onFallback?.(reason)
  }

  handle = setTimer(() => showNow('timeout'), delayMs)

  return { cancel: () => void settle(), showNow }
}
