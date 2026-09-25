import { useInput } from '@robo/ink'
import { useEffect, useRef } from 'react'

import { getUiState } from './uiStore.js'
import { isWakeUserDisabled } from './wakeState.js'

// A TUI nobody has touched for `display.tui_idle_exit_minutes` quits on its
// own instead of holding the gateway (and its model/tool processes) forever.
//
// "Touched" is a key, a paste, a wheel tick, or a change to the text in the
// composer (a right-click paste, an editor round trip). Time spent with a turn
// running, a background task alive, or an open mic (voice mode / an armed
// "Hey Robo" wake word) does not count as idle — those are ways of using the
// TUI without pressing a key, and killing them would lose work. Five minutes
// before the deadline a system line says so; any key cancels. Disabled (never
// quits) in the dashboard chat, where the PTY child has no restart path (see
// /quit).

export const IDLE_EXIT_POLL_MS = 30_000
export const IDLE_EXIT_WARN_MS = 5 * 60_000

export interface IdleClock {
  lastActivityAt: number
  warned: boolean
}

export interface IdleExitSnapshot {
  /** Turn, shell escape or interpolation in flight. */
  busy: boolean
  /** `display.tui_idle_exit_minutes`; 0 (or less) disables. */
  idleExitMinutes: number
  /** Hands-free voice or an armed wake word: the mic is the input device. */
  listening: boolean
  now: number
  /** Background tasks the session is still watching. */
  runningBackgroundTasks: number
}

export type IdleTick = 'exit' | 'none' | 'warn'

export const idleExitWarning = (minutes: number) =>
  `no input for ${Math.max(0, minutes - IDLE_EXIT_WARN_MS / 60_000)} min — quitting in 5 min (press any key to stay)`

export const idleExitGoodbye = (product: string, minutes: number) =>
  `${product} quit after ${minutes} minutes without input (display.tui_idle_exit_minutes; 0 disables).`

// One poll of the idle clock. Anything that counts as use pushes the clock
// forward (so the countdown starts when the turn ends, not when it began);
// otherwise the clock runs and the tick says whether to warn or to exit.
export function idleExitTick(clock: IdleClock, s: IdleExitSnapshot): IdleTick {
  if (s.idleExitMinutes <= 0) {
    return 'none'
  }

  if (s.busy || s.runningBackgroundTasks > 0 || s.listening) {
    clock.lastActivityAt = s.now
    clock.warned = false

    return 'none'
  }

  const remaining = s.idleExitMinutes * 60_000 - (s.now - clock.lastActivityAt)

  if (remaining <= 0) {
    return 'exit'
  }

  if (remaining <= IDLE_EXIT_WARN_MS && !clock.warned && s.idleExitMinutes * 60_000 > IDLE_EXIT_WARN_MS) {
    clock.warned = true

    return 'warn'
  }

  return 'none'
}

export const touchIdleClock = (clock: IdleClock, now: number) => {
  clock.lastActivityAt = now
  clock.warned = false
}

export interface UseIdleExitOptions {
  /** The composer's text: any change to it is use (mouse-driven edits — a
   * right-click paste, a drag that moves text — never reach useInput). */
  composerText?: string
  enabled: boolean
  onExit: (minutes: number) => void
  sys: (text: string) => void
  voiceEnabled: boolean
}

export function useIdleExit({ composerText = '', enabled, onExit, sys, voiceEnabled }: UseIdleExitOptions) {
  const clockRef = useRef<IdleClock>({ lastActivityAt: Date.now(), warned: false })
  const voiceRef = useRef(voiceEnabled)
  const onExitRef = useRef(onExit)
  const sysRef = useRef(sys)
  const composerTextRef = useRef(composerText)

  voiceRef.current = voiceEnabled
  onExitRef.current = onExit
  sysRef.current = sys

  // Every keystroke, paste and wheel tick lands here as well as in the real
  // input handlers; this one only resets the clock. (Mouse clicks and drags
  // are dispatched through the component tree instead and never arrive.)
  useInput(() => touchIdleClock(clockRef.current, Date.now()), { isActive: enabled })

  useEffect(() => {
    if (composerTextRef.current === composerText) {
      return
    }

    composerTextRef.current = composerText

    if (enabled) {
      touchIdleClock(clockRef.current, Date.now())
    }
  }, [composerText, enabled])

  useEffect(() => {
    if (!enabled) {
      return
    }

    // The clock starts when the feature (re)arms, not from some earlier idle.
    touchIdleClock(clockRef.current, Date.now())

    const timer = setInterval(() => {
      const ui = getUiState()
      const minutes = ui.idleExitMinutes

      const tick = idleExitTick(clockRef.current, {
        busy: ui.busy,
        idleExitMinutes: minutes,
        listening: voiceRef.current || (ui.wakeWordEnabled && !isWakeUserDisabled()),
        now: Date.now(),
        runningBackgroundTasks: ui.bgTasks.size
      })

      if (tick === 'warn') {
        sysRef.current(idleExitWarning(minutes))
      } else if (tick === 'exit') {
        clearInterval(timer)
        onExitRef.current(minutes)
      }
    }, IDLE_EXIT_POLL_MS)

    return () => clearInterval(timer)
  }, [enabled])
}
