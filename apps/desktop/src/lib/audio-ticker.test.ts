import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { startAudioTicker } from './audio-ticker'

describe('startAudioTicker', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('ticks at once, then on every interval until the tick says stop', () => {
    let ticks = 0

    startAudioTicker(() => {
      ticks += 1

      return ticks < 4
    }, 30)

    expect(ticks).toBe(1)
    vi.advanceTimersByTime(300)
    expect(ticks).toBe(4)
  })

  it('stops for good when stopped from outside, however often', () => {
    const tick = vi.fn(() => true)
    const stop = startAudioTicker(tick, 30)

    vi.advanceTimersByTime(90)
    stop()
    stop()

    const count = tick.mock.calls.length

    vi.advanceTimersByTime(300)
    expect(tick).toHaveBeenCalledTimes(count)
  })

  it('keeps ticking while animation frames never come (a minimized window)', () => {
    vi.stubGlobal('requestAnimationFrame', () => 0)

    const tick = vi.fn(() => true)
    const stop = startAudioTicker(tick, 30)

    vi.advanceTimersByTime(3_000)
    expect(tick.mock.calls.length).toBeGreaterThanOrEqual(100)
    stop()
    vi.unstubAllGlobals()
  })
})
