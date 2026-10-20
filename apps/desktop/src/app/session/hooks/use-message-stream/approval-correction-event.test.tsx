import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { type MutableRefObject, useEffect, useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ClientSessionState } from '@/app/types'
import { createClientSessionState } from '@/lib/chat-runtime'
import { clearAllPrompts, sessionApprovalRequest } from '@/store/prompts'
import type { RpcEvent } from '@/types/robo'

import { useMessageStream } from './index'

// An `approval.request` carries `kind: "correction"` when the fact checker
// proposes a correction to the answer (agent/fact_check.py). The store must
// keep the kind so the approval bar can say Apply / Keep answer instead of
// Run / Reject; a command approval (no kind) stays a command.

const SID = 'session-1'

let handleEvent: ((event: RpcEvent) => void) | null = null
let stateRef: MutableRefObject<Map<string, ClientSessionState>> | null = null

function Harness() {
  const activeSessionIdRef = useRef<string | null>(SID)
  const sessionStateByRuntimeIdRef = useRef(new Map<string, ClientSessionState>())
  const queryClientRef = useRef(new QueryClient())

  const stream = useMessageStream({
    activeSessionIdRef,
    hydrateFromStoredSession: vi.fn(async () => undefined),
    queryClient: queryClientRef.current,
    refreshRoboConfig: vi.fn(async () => undefined),
    refreshSessions: vi.fn(async () => undefined),
    sessionStateByRuntimeIdRef,
    updateSessionState: (sessionId, updater) => {
      const current = sessionStateByRuntimeIdRef.current.get(sessionId) ?? createClientSessionState()
      const next = updater(current)
      sessionStateByRuntimeIdRef.current.set(sessionId, next)

      return next
    }
  })

  useEffect(() => {
    handleEvent = stream.handleGatewayEvent
    stateRef = sessionStateByRuntimeIdRef
  }, [stream.handleGatewayEvent])

  return null
}

async function mountStream() {
  render(<Harness />)
  await waitFor(() => expect(handleEvent).not.toBeNull())
}

const approvalRequest = (payload: Record<string, unknown>) =>
  act(() => handleEvent!({ payload, session_id: SID, type: 'approval.request' }))

describe('approval.request kind', () => {
  beforeEach(() => {
    handleEvent = null
    stateRef = null
    clearAllPrompts()
  })

  afterEach(() => {
    cleanup()
    clearAllPrompts()
    vi.restoreAllMocks()
  })

  it('keeps a fact-check correction as kind "correction"', async () => {
    await mountStream()

    approvalRequest({
      allow_permanent: false,
      choices: ['once', 'session', 'deny'],
      command: 'Answer says: X\nSource says: Y',
      description: 'Correction proposed: Robo\'s research disagrees with 1 statement in the answer. Apply the correction?',
      kind: 'correction'
    })

    const request = sessionApprovalRequest(SID).get()
    expect(request?.kind).toBe('correction')
    expect(request?.allowPermanent).toBe(false)
    expect(request?.choices).toEqual(['once', 'session', 'deny'])
    expect(request?.command).toBe('Answer says: X\nSource says: Y')
    expect(stateRef?.current.get(SID)?.needsInput).toBe(true)
  })

  it('treats a request without a kind as a command', async () => {
    await mountStream()

    approvalRequest({ command: 'rm -rf build', description: 'dangerous command' })

    expect(sessionApprovalRequest(SID).get()?.kind).toBe('command')
  })
})
