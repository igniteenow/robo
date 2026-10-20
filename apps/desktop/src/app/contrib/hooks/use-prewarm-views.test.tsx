// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PrewarmScheduler } from '@/lib/prewarm'
import { $desktopBoot, completeDesktopBoot, failDesktopBoot, setDesktopBootStep } from '@/store/boot'

import { bootSettled, PREWARM_AFTER_BOOT_MS, usePrewarmViews } from './use-prewarm-views'

// Runs each slot synchronously so the test only has to drive the boot store
// and the post-boot timer.
const immediate: PrewarmScheduler = run => {
  run()

  return () => undefined
}

// Each prewarm step hands over through a couple of microtasks.
const flush = () =>
  act(async () => {
    for (let i = 0; i < 6; i += 1) {
      await Promise.resolve()
    }
  })

function booting() {
  setDesktopBootStep({ message: 'starting', phase: 'renderer.boot', progress: 6, running: true })
}

describe('bootSettled', () => {
  it('is the cold boot being over, with no error', () => {
    expect(bootSettled({ error: null, progress: 100, running: false })).toBe(true)
    expect(bootSettled({ error: null, progress: 97, running: true })).toBe(false)
    expect(bootSettled({ error: null, progress: 100, running: true })).toBe(false)
    expect(bootSettled({ error: 'nope', progress: 100, running: false })).toBe(false)
  })
})

describe('usePrewarmViews', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    booting()
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('warms the views once, a moment after the boot settles, one by one', async () => {
    const calls: string[] = []

    const loaders = [
      () => {
        calls.push('settings')
      },
      () => {
        calls.push('command-center')
      }
    ]

    renderHook(() => usePrewarmViews({ loaders, schedule: immediate }))

    // Still booting: nothing is scheduled, let alone loaded.
    act(() => vi.advanceTimersByTime(PREWARM_AFTER_BOOT_MS * 2))
    expect(calls).toEqual([])

    act(() => completeDesktopBoot())
    expect(calls).toEqual([])

    act(() => vi.advanceTimersByTime(PREWARM_AFTER_BOOT_MS - 1))
    expect(calls).toEqual([])

    act(() => vi.advanceTimersByTime(1))
    await flush()
    await flush()
    expect(calls).toEqual(['settings', 'command-center'])

    // A later re-completion (reconnect) does not warm again.
    act(() => completeDesktopBoot())
    act(() => vi.advanceTimersByTime(PREWARM_AFTER_BOOT_MS * 2))
    await flush()
    expect(calls).toEqual(['settings', 'command-center'])
  })

  it('never starts on a failed boot, and stops when the shell unmounts', () => {
    const calls: string[] = []

    const loaders = [
      () => {
        calls.push('settings')
      }
    ]

    const { unmount } = renderHook(() => usePrewarmViews({ loaders, schedule: immediate }))

    act(() => failDesktopBoot('backend died'))
    act(() => vi.advanceTimersByTime(PREWARM_AFTER_BOOT_MS * 2))
    expect(calls).toEqual([])

    act(() => completeDesktopBoot())
    unmount()
    act(() => vi.advanceTimersByTime(PREWARM_AFTER_BOOT_MS * 2))
    expect(calls).toEqual([])
    expect($desktopBoot.get().running).toBe(false)
  })
})
