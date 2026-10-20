import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { useBusySendChoice } from './use-busy-send-choice'

// The open flag of the Send now / Queue choice: opened by Enter on a text
// draft while busy, closed by a pick, by Esc, by emptying the draft, by the
// turn ending, and by moving to another session. The words themselves are
// never touched here.

interface Props {
  activeQueueSessionKey: string | null
  busy: boolean
  hasText: boolean
}

function renderChoice(initial: Partial<Props> = {}, draft = 'send this') {
  const draftRef = { current: draft }

  const hook = renderHook((props: Props) => useBusySendChoice({ ...props, draftRef }), {
    initialProps: { activeQueueSessionKey: 'session-a', busy: true, hasText: true, ...initial }
  })

  return { draftRef, hook }
}

afterEach(() => {
  cleanup()
})

describe('useBusySendChoice', () => {
  it('starts closed; show opens, hide closes; the ref mirrors the state synchronously', () => {
    const { hook } = renderChoice()

    expect(hook.result.current.open).toBe(false)

    act(() => {
      hook.result.current.show()
    })

    expect(hook.result.current.open).toBe(true)
    expect(hook.result.current.openRef.current).toBe(true)

    act(() => {
      hook.result.current.hide()
    })

    expect(hook.result.current.open).toBe(false)
    expect(hook.result.current.openRef.current).toBe(false)
  })

  it('closes when the turn ends', () => {
    const { hook } = renderChoice()

    act(() => {
      hook.result.current.show()
    })
    hook.rerender({ activeQueueSessionKey: 'session-a', busy: false, hasText: true })

    expect(hook.result.current.open).toBe(false)
  })

  it('closes when the draft is emptied, but not on the composer state lag alone', () => {
    // A fast Enter: the editor holds the words while the composer state still
    // says empty. The choice opens on the live words and must stay open.
    const { draftRef, hook } = renderChoice({ hasText: false })

    act(() => {
      hook.result.current.show()
    })
    expect(hook.result.current.open).toBe(true)

    // State catches up.
    hook.rerender({ activeQueueSessionKey: 'session-a', busy: true, hasText: true })
    expect(hook.result.current.open).toBe(true)

    // The person deletes the words.
    draftRef.current = ''
    hook.rerender({ activeQueueSessionKey: 'session-a', busy: true, hasText: false })
    expect(hook.result.current.open).toBe(false)
  })

  it('closes when the composer moves to another session', () => {
    const { hook } = renderChoice()

    act(() => {
      hook.result.current.show()
    })
    hook.rerender({ activeQueueSessionKey: 'session-b', busy: true, hasText: true })

    expect(hook.result.current.open).toBe(false)
  })
})
