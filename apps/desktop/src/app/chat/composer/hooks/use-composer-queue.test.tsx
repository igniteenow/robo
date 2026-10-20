import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  $parkedQueueSessions,
  $queuedPromptsBySession,
  enqueueQueuedPrompt,
  getQueuedPrompts,
  isQueueParked,
  parkQueuedPrompts
} from '@/store/composer-queue'

import type { QueueEditState } from '../composer-utils'
import type { ChatBarProps } from '../types'

import { useComposerQueue } from './use-composer-queue'

// The park ↔ drain contract at the hook level. The store tests pin the pure
// pieces (shouldAutoDrain, park bookkeeping); these pin the wiring — the
// auto-drain effect honoring the park, and send-now-while-busy lifting it so
// the settle drain still flows (the regression that sank the old blanket
// interrupt latch).

const SESSION_KEY = 'stored-session-queue-hook'

function renderQueueHook(overrides: { busy?: boolean; draft?: string; onCancel?: () => void } = {}) {
  const onSubmit = vi.fn<ChatBarProps['onSubmit']>(async () => true)
  const onCancel = overrides.onCancel ?? vi.fn()
  const queueEditRef: { current: QueueEditState | null } = { current: null }
  const draftRef = { current: overrides.draft ?? '' }

  const clearDraft = vi.fn(() => {
    draftRef.current = ''
  })

  const hook = renderHook(
    ({ busy }: { busy: boolean }) =>
      useComposerQueue({
        activeQueueSessionKey: SESSION_KEY,
        attachments: [],
        busy,
        clearDraft,
        draftRef,
        focusInput: () => undefined,
        loadIntoComposer: () => undefined,
        onCancel,
        onSubmit,
        queueEditRef,
        queueSessionKey: SESSION_KEY,
        sessionId: 'rt-session-queue-hook'
      }),
    { initialProps: { busy: overrides.busy ?? false } }
  )

  return { clearDraft, draftRef, hook, onCancel, onSubmit }
}

describe('useComposerQueue park integration', () => {
  beforeEach(() => {
    window.localStorage.clear()
    $queuedPromptsBySession.set({})
    $parkedQueueSessions.set({})
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    $queuedPromptsBySession.set({})
    $parkedQueueSessions.set({})
  })

  it('auto-drains an unparked queue once idle', async () => {
    enqueueQueuedPrompt(SESSION_KEY, { attachments: [], text: 'flows' })

    const { onSubmit } = renderQueueHook()

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(getQueuedPrompts(SESSION_KEY)).toHaveLength(0)
  })

  it('holds a parked queue at the idle settle (the Stop edge)', async () => {
    enqueueQueuedPrompt(SESSION_KEY, { attachments: [], text: 'halted' })
    parkQueuedPrompts(SESSION_KEY)

    const { hook, onSubmit } = renderQueueHook({ busy: true })

    // The Stop settle: busy flips false with the park in place.
    hook.rerender({ busy: false })

    await act(async () => {
      await Promise.resolve()
    })

    expect(onSubmit).not.toHaveBeenCalled()
    expect(getQueuedPrompts(SESSION_KEY)).toHaveLength(1)
  })

  it('drainNextQueued sends a parked entry and lifts the park (manual resume)', async () => {
    enqueueQueuedPrompt(SESSION_KEY, { attachments: [], text: 'resumed' })
    parkQueuedPrompts(SESSION_KEY)

    const { hook, onSubmit } = renderQueueHook()

    await act(async () => {
      await hook.result.current.drainNextQueued()
    })

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(isQueueParked(SESSION_KEY)).toBe(false)
  })

  it('sendQueuedNow while busy unparks so the settle drain flows (no stale latch)', async () => {
    const first = enqueueQueuedPrompt(SESSION_KEY, { attachments: [], text: 'first' })
    enqueueQueuedPrompt(SESSION_KEY, { attachments: [], text: 'send me now' })
    parkQueuedPrompts(SESSION_KEY)

    const { hook, onCancel, onSubmit } = renderQueueHook({ busy: true })
    const target = getQueuedPrompts(SESSION_KEY).find(e => e.id !== first!.id)!

    act(() => {
      hook.result.current.sendQueuedNow(target.id)
    })

    // The interrupt fired and the park lifted — this interrupt exists to reach
    // the queue, not to halt it.
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(isQueueParked(SESSION_KEY)).toBe(false)

    // Turn settles → the promoted entry drains.
    hook.rerender({ busy: false })

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0]?.[0]).toBe('send me now')
  })

  it('sendDraftNow while busy: draft to the head of the queue, park lifted, interrupt fired, drained on settle', async () => {
    enqueueQueuedPrompt(SESSION_KEY, { attachments: [], text: 'already waiting' })
    parkQueuedPrompts(SESSION_KEY)

    const { clearDraft, hook, onCancel, onSubmit } = renderQueueHook({ busy: true, draft: 'stop, do this instead' })

    let accepted = false

    act(() => {
      accepted = hook.result.current.sendDraftNow()
    })

    expect(accepted).toBe(true)
    expect(clearDraft).toHaveBeenCalledTimes(1)
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(isQueueParked(SESSION_KEY)).toBe(false)
    expect(getQueuedPrompts(SESSION_KEY).map(e => e.text)).toEqual(['stop, do this instead', 'already waiting'])

    hook.rerender({ busy: false })

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0]?.[0]).toBe('stop, do this instead')
  })

  it('sendDraftNow while idle sends the draft straight away', async () => {
    const { hook, onCancel, onSubmit } = renderQueueHook({ draft: 'right now' })

    act(() => {
      hook.result.current.sendDraftNow()
    })

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0]?.[0]).toBe('right now')
    expect(onCancel).not.toHaveBeenCalled()
    expect(getQueuedPrompts(SESSION_KEY)).toHaveLength(0)
  })

  it('sendDraftNow does nothing for an empty draft', () => {
    const { hook, onCancel } = renderQueueHook({ busy: true, draft: '   ' })

    let accepted = true

    act(() => {
      accepted = hook.result.current.sendDraftNow()
    })

    expect(accepted).toBe(false)
    expect(onCancel).not.toHaveBeenCalled()
    expect(getQueuedPrompts(SESSION_KEY)).toHaveLength(0)
  })
})
