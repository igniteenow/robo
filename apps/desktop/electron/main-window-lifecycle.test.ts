import assert from 'node:assert/strict'

import { test } from 'vitest'

import { armWindowShowFallback, ensureMainWindow } from './main-window-lifecycle'

test('recreates a destroyed primary window without focusing it', () => {
  const destroyedWindow = {
    isDestroyed: () => true
  }

  let createCalls = 0
  let focusCalls = 0

  ensureMainWindow(destroyedWindow, {
    isReady: true,
    createWindow: () => {
      createCalls += 1
    },
    focusWindow: () => {
      focusCalls += 1
    }
  })

  assert.equal(createCalls, 1)
  assert.equal(focusCalls, 0)
})

test('waits for app readiness before recreating a primary window', () => {
  let createCalls = 0

  ensureMainWindow(null, {
    isReady: false,
    createWindow: () => {
      createCalls += 1
    },
    focusWindow: () => assert.fail('missing window must not be focused')
  })

  assert.equal(createCalls, 0)
})

test('focuses a live primary window for a normal second launch', () => {
  const liveWindow = {
    isDestroyed: () => false
  }

  let focusedWindow = null

  ensureMainWindow(liveWindow, {
    isReady: true,
    createWindow: () => assert.fail('live window must not be replaced'),
    focusWindow: window => {
      focusedWindow = window
    }
  })

  assert.equal(focusedWindow, liveWindow)
})

test('leaves live-window focus to deep-link delivery', () => {
  const liveWindow = {
    isDestroyed: () => false
  }

  ensureMainWindow(liveWindow, {
    isReady: true,
    createWindow: () => assert.fail('live window must not be replaced'),
    focusWindow: () => assert.fail('deep-link delivery owns focus'),
    focusExisting: false
  })
})

function fakeWindow({ destroyed = false, visible = false } = {}) {
  const state = { destroyed, fallbacks: [] as string[], shows: 0, visible }
  let pending: (() => void) | null = null
  let cleared = 0

  const fallback = armWindowShowFallback({
    clearTimer: () => {
      cleared += 1
      pending = null
    },
    delayMs: 3000,
    isDestroyed: () => state.destroyed,
    isVisible: () => state.visible,
    onFallback: reason => {
      state.fallbacks.push(reason)
    },
    setTimer: (callback, delayMs) => {
      assert.equal(delayMs, 3000)
      pending = callback

      return 1
    },
    show: () => {
      state.shows += 1
      state.visible = true
    }
  })

  return {
    ...fallback,
    cleared: () => cleared,
    // The grace period runs out (a no-op once the timer was cleared).
    elapse: () => pending?.(),
    state
  }
}

test('shows a window that never got its first frame once the grace period runs out', () => {
  const win = fakeWindow()

  assert.equal(win.state.shows, 0)

  win.elapse()

  assert.equal(win.state.shows, 1)
  assert.deepEqual(win.state.fallbacks, ['timeout'])
})

test('shows it earlier when the page has loaded, and only once', () => {
  const win = fakeWindow()

  win.showNow('loaded')

  assert.equal(win.state.shows, 1)
  assert.deepEqual(win.state.fallbacks, ['loaded'])
  assert.equal(win.cleared(), 1)

  win.state.visible = false
  win.showNow('loaded')
  win.elapse()

  assert.equal(win.state.shows, 1)
})

test('leaves a window alone once ready-to-show has shown it', () => {
  const win = fakeWindow()

  // ready-to-show → win.show() → the 'show' event disarms the fallback.
  win.state.visible = true
  win.cancel()
  win.showNow('loaded')
  win.elapse()

  assert.equal(win.cleared(), 1)
  assert.equal(win.state.shows, 0)
  assert.deepEqual(win.state.fallbacks, [])
})

test('never brings back a window that was shown and then hidden on purpose', () => {
  const win = fakeWindow()

  win.cancel()
  win.state.visible = false
  win.showNow('loaded')
  win.elapse()

  assert.equal(win.state.shows, 0)
})

test('does not show a window that is already visible or already gone', () => {
  const visible = fakeWindow({ visible: true })

  visible.elapse()

  assert.equal(visible.state.shows, 0)
  assert.deepEqual(visible.state.fallbacks, [])

  const gone = fakeWindow({ destroyed: true })

  gone.showNow('loaded')

  assert.equal(gone.state.shows, 0)
  assert.deepEqual(gone.state.fallbacks, [])
})

test('cancelling after the fallback fired is harmless', () => {
  const win = fakeWindow()

  win.elapse()
  win.cancel()
  win.cancel()

  assert.equal(win.state.shows, 1)
  assert.equal(win.cleared(), 1)
})
