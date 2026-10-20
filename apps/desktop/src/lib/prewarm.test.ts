import { describe, expect, it } from 'vitest'

import { idleScheduler, prewarm, type PrewarmScheduler } from './prewarm'

/** A scheduler the test drives by hand: nothing runs until `tick()`. */
function manualScheduler() {
  const queue: Array<() => void> = []

  const schedule: PrewarmScheduler = run => {
    queue.push(run)

    return () => {
      const at = queue.indexOf(run)

      if (at >= 0) {
        queue.splice(at, 1)
      }
    }
  }

  return {
    schedule,
    pending: () => queue.length,
    tick: () => {
      const run = queue.shift()
      run?.()
    }
  }
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0))

describe('prewarm', () => {
  it('loads one at a time, each in its own slot, in order', async () => {
    const calls: string[] = []
    const sched = manualScheduler()

    prewarm(
      [
        () => {
          calls.push('a')
        },
        async () => {
          calls.push('b')
        },
        () => {
          calls.push('c')
        }
      ],
      sched.schedule
    )

    // Nothing has loaded yet; exactly one slot is booked.
    expect(calls).toEqual([])
    expect(sched.pending()).toBe(1)

    sched.tick()
    await flush()
    expect(calls).toEqual(['a'])
    expect(sched.pending()).toBe(1)

    sched.tick()
    await flush()
    sched.tick()
    await flush()
    expect(calls).toEqual(['a', 'b', 'c'])
    expect(sched.pending()).toBe(0)
  })

  it('keeps going past a loader that rejects or throws', async () => {
    const calls: string[] = []
    const sched = manualScheduler()

    prewarm(
      [
        () => Promise.reject(new Error('chunk missing')),
        () => {
          throw new Error('sync')
        },
        () => {
          calls.push('after')
        }
      ],
      sched.schedule
    )

    sched.tick()
    await flush()
    sched.tick()
    await flush()
    sched.tick()
    await flush()
    expect(calls).toEqual(['after'])
  })

  it('cancel stops everything that has not started', async () => {
    const calls: string[] = []
    const sched = manualScheduler()

    const cancel = prewarm(
      [
        () => {
          calls.push('a')
        },
        () => {
          calls.push('b')
        }
      ],
      sched.schedule
    )

    sched.tick()
    await flush()
    expect(calls).toEqual(['a'])

    cancel()
    expect(sched.pending()).toBe(0)
    sched.tick()
    await flush()
    expect(calls).toEqual(['a'])
  })

  it('handles an empty list', () => {
    const sched = manualScheduler()

    expect(() => prewarm([], sched.schedule)()).not.toThrow()
    expect(sched.pending()).toBe(0)
  })
})

describe('idleScheduler', () => {
  it('runs the callback later and can be cancelled', async () => {
    let ran = 0
    const schedule = idleScheduler(100)

    const cancel = schedule(() => {
      ran += 1
    })

    cancel()

    schedule(() => {
      ran += 10
    })

    await new Promise(resolve => setTimeout(resolve, 400))
    expect(ran).toBe(10)
  })
})
