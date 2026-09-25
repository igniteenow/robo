import { describe, expect, it } from 'vitest'

import { DEFAULT_IDLE_EXIT_MINUTES } from '../app/interfaces.js'
import { normalizeIdleExitMinutes } from '../app/useConfigSync.js'
import {
  IDLE_EXIT_WARN_MS,
  type IdleClock,
  idleExitGoodbye,
  idleExitTick,
  idleExitWarning,
  touchIdleClock
} from '../app/useIdleExit.js'

// A TUI nobody touches for display.tui_idle_exit_minutes quits on its own.
// These pin the clock: what counts as use, when the warning fires, and that
// the countdown restarts from the end of a turn rather than its start.

const MIN = 60_000
const T0 = 1_000_000

const snap = (over: Partial<Parameters<typeof idleExitTick>[1]> = {}) => ({
  busy: false,
  idleExitMinutes: 60,
  listening: false,
  now: T0,
  runningBackgroundTasks: 0,
  ...over
})

const clockAt = (lastActivityAt: number, warned = false): IdleClock => ({ lastActivityAt, warned })

describe('idleExitTick', () => {
  it('does nothing while the deadline is far away', () => {
    expect(idleExitTick(clockAt(T0), snap({ now: T0 + 30 * MIN }))).toBe('none')
  })

  it('warns once, five minutes before the deadline, then exits at the deadline', () => {
    const clock = clockAt(T0)

    expect(idleExitTick(clock, snap({ now: T0 + 55 * MIN }))).toBe('warn')
    expect(clock.warned).toBe(true)
    expect(idleExitTick(clock, snap({ now: T0 + 57 * MIN }))).toBe('none')
    expect(idleExitTick(clock, snap({ now: T0 + 60 * MIN }))).toBe('exit')
  })

  it('a key press after the warning re-arms both the clock and the warning', () => {
    const clock = clockAt(T0)

    idleExitTick(clock, snap({ now: T0 + 56 * MIN }))
    touchIdleClock(clock, T0 + 56 * MIN)

    expect(clock.warned).toBe(false)
    expect(idleExitTick(clock, snap({ now: T0 + 60 * MIN }))).toBe('none')
    expect(idleExitTick(clock, snap({ now: T0 + 56 * MIN + 55 * MIN }))).toBe('warn')
    expect(idleExitTick(clock, snap({ now: T0 + 56 * MIN + 60 * MIN }))).toBe('exit')
  })

  it('a running turn is use: the countdown starts when it ends, not when it began', () => {
    const clock = clockAt(T0)

    // Two hours of agent work with the user watching but not typing.
    expect(idleExitTick(clock, snap({ busy: true, now: T0 + 120 * MIN }))).toBe('none')
    expect(clock.lastActivityAt).toBe(T0 + 120 * MIN)

    expect(idleExitTick(clock, snap({ now: T0 + 174 * MIN }))).toBe('none')
    expect(idleExitTick(clock, snap({ now: T0 + 175 * MIN }))).toBe('warn')
    expect(idleExitTick(clock, snap({ now: T0 + 180 * MIN }))).toBe('exit')
  })

  it('background tasks and an open mic keep the TUI alive', () => {
    const clock = clockAt(T0)

    expect(idleExitTick(clock, snap({ now: T0 + 90 * MIN, runningBackgroundTasks: 1 }))).toBe('none')
    expect(idleExitTick(clock, snap({ listening: true, now: T0 + 200 * MIN }))).toBe('none')
    expect(clock.lastActivityAt).toBe(T0 + 200 * MIN)
  })

  it('a turn ending clears a stale warning', () => {
    const clock = clockAt(T0, true)

    idleExitTick(clock, snap({ busy: true, now: T0 + 56 * MIN }))

    expect(clock.warned).toBe(false)
  })

  it('0 disables the feature entirely', () => {
    const clock = clockAt(T0)

    expect(idleExitTick(clock, snap({ idleExitMinutes: 0, now: T0 + 10_000 * MIN }))).toBe('none')
  })

  it('a short limit skips the five-minute warning and just exits', () => {
    const clock = clockAt(T0)

    expect(idleExitTick(clock, snap({ idleExitMinutes: 3, now: T0 + 2 * MIN }))).toBe('none')
    expect(clock.warned).toBe(false)
    expect(idleExitTick(clock, snap({ idleExitMinutes: 3, now: T0 + 3 * MIN }))).toBe('exit')
  })
})

describe('idle-exit copy', () => {
  it('names the remaining time and the config key', () => {
    expect(idleExitWarning(60)).toBe('no input for 55 min — quitting in 5 min (press any key to stay)')
    expect(IDLE_EXIT_WARN_MS).toBe(5 * MIN)
    expect(idleExitGoodbye('Robo', 60)).toContain('Robo quit after 60 minutes without input')
    expect(idleExitGoodbye('Robo', 60)).toContain('display.tui_idle_exit_minutes')
  })
})

describe('normalizeIdleExitMinutes', () => {
  it('defaults to an hour and accepts numbers or numeric strings', () => {
    expect(DEFAULT_IDLE_EXIT_MINUTES).toBe(60)
    expect(normalizeIdleExitMinutes(undefined)).toBe(60)
    expect(normalizeIdleExitMinutes(90)).toBe(90)
    expect(normalizeIdleExitMinutes('45')).toBe(45)
    expect(normalizeIdleExitMinutes(' 30 ')).toBe(30)
    expect(normalizeIdleExitMinutes(0)).toBe(0)
    expect(normalizeIdleExitMinutes('0')).toBe(0)
    expect(normalizeIdleExitMinutes(2.6)).toBe(3)
  })

  it('falls back to the default on junk rather than silently disabling', () => {
    expect(normalizeIdleExitMinutes('never')).toBe(60)
    expect(normalizeIdleExitMinutes(-5)).toBe(60)
    expect(normalizeIdleExitMinutes(null)).toBe(60)
    expect(normalizeIdleExitMinutes(NaN)).toBe(60)
    expect(normalizeIdleExitMinutes(true)).toBe(60)
  })
})
