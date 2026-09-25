import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { useEffect, useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ClientSessionState } from '@/app/types'
import { chatMessageText, textPart } from '@/lib/chat-messages'
import { createClientSessionState } from '@/lib/chat-runtime'
import type { RpcEvent } from '@/types/robo'

import { useMessageStream } from './index'

// `message.user` is the gateway's authoritative echo of a message it accepted
// while a turn was running — busy-input policy, session.steer,
// session.redirect — fired for EVERY attached client. The desktop paints its
// own sends optimistically, so the echo only has to cover the other cases: a
// steer typed in the TUI or the web dashboard on the same session, or a local
// echo that never happened. It must never double up our own bubble.

const SID = 'session-1'

let handleEvent: ((event: RpcEvent) => void) | null = null
let updateState: ((updater: (state: ClientSessionState) => ClientSessionState) => void) | null = null
let sessionStates: Map<string, ClientSessionState>

function Harness() {
  const activeSessionIdRef = useRef<string | null>(SID)
  const sessionStateByRuntimeIdRef = useRef(new Map<string, ClientSessionState>())
  const queryClientRef = useRef(new QueryClient())

  const updateSessionState = (sessionId: string, updater: (state: ClientSessionState) => ClientSessionState) => {
    const current = sessionStateByRuntimeIdRef.current.get(sessionId) ?? createClientSessionState()
    const next = updater(current)
    sessionStateByRuntimeIdRef.current.set(sessionId, next)
    sessionStates.set(sessionId, next)

    return next
  }

  const stream = useMessageStream({
    activeSessionIdRef,
    hydrateFromStoredSession: vi.fn(async () => undefined),
    queryClient: queryClientRef.current,
    refreshRoboConfig: vi.fn(async () => undefined),
    refreshSessions: vi.fn(async () => undefined),
    sessionStateByRuntimeIdRef,
    updateSessionState
  })

  useEffect(() => {
    handleEvent = stream.handleGatewayEvent
    updateState = updater => updateSessionState(SID, updater)
  }, [stream.handleGatewayEvent])

  return null
}

async function mountStream() {
  sessionStates = new Map()
  render(<Harness />)
  await waitFor(() => expect(handleEvent).not.toBeNull())
}

const start = () => act(() => handleEvent!({ payload: {}, session_id: SID, type: 'message.start' }))
const delta = (text: string) => act(() => handleEvent!({ payload: { text }, session_id: SID, type: 'message.delta' }))

const complete = (text: string) =>
  act(() => handleEvent!({ payload: { text }, session_id: SID, type: 'message.complete' }))

const userEcho = (text: string, status = 'steered') =>
  act(() => handleEvent!({ payload: { mid_turn: true, status, text }, session_id: SID, type: 'message.user' }))

function getState(): ClientSessionState {
  return sessionStates.get(SID) ?? createClientSessionState()
}

function transcript(): string[] {
  return getState()
    .messages.filter(m => !m.hidden && chatMessageText(m))
    .map(m => `${m.role}:${chatMessageText(m)}`)
}

describe('useMessageStream message.user (mid-turn echo)', () => {
  beforeEach(() => {
    handleEvent = null
    updateState = null
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('paints a steer sent from another client above the live reply', async () => {
    await mountStream()
    await start()
    // Still sitting in the delta batch (33 ms flush timer) when the echo
    // arrives: the handler flushes it first, so the live bubble exists and
    // the steer lands above it — where the redirect path puts its own bubble.
    await delta('Looking at the logs')

    await userEcho('also check auth.log')

    expect(transcript()).toEqual(['user:also check auth.log', 'assistant:Looking at the logs'])
  })

  it('lands at the tail when the reply bubble has not started streaming yet', async () => {
    await mountStream()
    await start()

    await userEcho('also check auth.log', 'queued')
    await delta('On it')
    await complete('On it')

    expect(transcript()).toEqual(['user:also check auth.log', 'assistant:On it'])
  })

  it('does not double up a bubble this client already painted', async () => {
    await mountStream()
    await start()

    // The optimistic bubble the submit / redirect paths paint at send time.
    act(() =>
      updateState!(state => ({
        ...state,
        messages: [...state.messages, { id: 'user-optimistic', parts: [textPart('also check auth.log')], role: 'user' }]
      }))
    )
    await delta('Looking')
    await userEcho('  also check auth.log  ')

    expect(transcript().filter(line => line === 'user:also check auth.log')).toHaveLength(1)
  })

  it('ignores frames that are not mid-turn or carry no text', async () => {
    await mountStream()
    await start()

    await act(() => handleEvent!({ payload: { text: 'hello' }, session_id: SID, type: 'message.user' }))
    await userEcho('   ')

    expect(transcript()).toEqual([])
  })
})
