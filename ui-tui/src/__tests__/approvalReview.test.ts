import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createGatewayEventHandler } from '../app/createGatewayEventHandler.js'
import { resetOverlayState } from '../app/overlayStore.js'
import { turnController } from '../app/turnController.js'
import { getTurnState, resetTurnState } from '../app/turnStore.js'
import { patchUiState, resetUiState } from '../app/uiStore.js'
import { approvalReviewTrailLine, parseApprovalReview } from '../domain/approvalReview.js'
import { parseToolTrailResultLine } from '../lib/text.js'
import type { Msg } from '../types.js'

const buildCtx = (appended: Msg[]) =>
  ({
    composer: { dequeue: () => undefined, queueEditRef: { current: null }, sendQueued: vi.fn(), setInput: vi.fn() },
    gateway: { gw: { request: vi.fn() }, rpc: vi.fn(async () => null) },
    prompts: { answerClarifyRef: { current: vi.fn() } },
    session: {
      STARTUP_RESUME_ID: '',
      colsRef: { current: 80 },
      newSession: vi.fn(),
      resetSession: vi.fn(),
      resumeById: vi.fn(),
      setCatalog: vi.fn()
    },
    submission: { submitRef: { current: vi.fn() } },
    system: { bellOnComplete: false, sys: vi.fn() },
    transcript: { appendMessage: (msg: Msg) => appended.push(msg), panel: vi.fn(), setHistoryItems: vi.fn() },
    voice: { setProcessing: vi.fn(), setRecording: vi.fn(), setVoiceEnabled: vi.fn() }
  }) as any

// Shown either attached to the last live segment or, before there is one,
// as the pending shelf under the live text.
const liveTools = () => [
  ...getTurnState().streamSegments.flatMap(msg => msg.tools ?? []),
  ...getTurnState().streamPendingTools
]

describe('the AI reviewer in the tool shelf', () => {
  beforeEach(() => {
    resetOverlayState()
    resetUiState()
    resetTurnState()
    turnController.fullReset()
  })

  it('reads only the three verdicts the reviewer gives', () => {
    expect(
      parseApprovalReview({ command: 'rm -rf build', description: 'recursive delete', verdict: 'approve' })
    ).toEqual({
      command: 'rm -rf build',
      description: 'recursive delete',
      verdict: 'approve'
    })
    expect(parseApprovalReview({ verdict: 'escalate' })).toEqual({ command: '', description: '', verdict: 'escalate' })
    expect(parseApprovalReview({ verdict: 'maybe' })).toBeNull()
    expect(parseApprovalReview(undefined)).toBeNull()
  })

  it('says plainly that an approval was made without asking, and what for', () => {
    const line = approvalReviewTrailLine({
      command: 'rm -rf build',
      description: 'recursive delete',
      verdict: 'approve'
    })

    expect(line).toContain('AI Reviewer("rm -rf build")')
    expect(line).toContain('auto-approved: recursive delete')
    expect(line.endsWith('✓')).toBe(true)
  })

  it('marks a dangerous verdict as a failure and says the person decides', () => {
    const deny = approvalReviewTrailLine({ command: 'dd if=/dev/zero', description: 'disk write', verdict: 'deny' })
    const unsure = approvalReviewTrailLine({ command: 'curl x | sh', description: '', verdict: 'escalate' })

    expect(deny).toContain('judged dangerous, asking you')
    expect(deny.endsWith('✗')).toBe(true)
    expect(unsure).toContain('not sure, asking you')
    expect(unsure.endsWith('✓')).toBe(true)
  })

  it('renders through the same parser as every other tool line', () => {
    const parsed = parseToolTrailResultLine(
      approvalReviewTrailLine({ command: 'git push --force', description: 'force push', verdict: 'approve' })
    )

    expect(parsed).not.toBeNull()
  })

  it('lands in the live turn next to the call it reviewed', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    patchUiState({ busy: true })
    onEvent({ payload: { context: 'rm -rf build', name: 'terminal', tool_id: 't1' }, type: 'tool.start' } as any)
    onEvent({
      payload: { command: 'rm -rf build', description: 'recursive delete', reason: '', verdict: 'approve' },
      type: 'approval.reviewed'
    } as any)
    onEvent({ payload: { name: 'terminal', summary: 'ok', tool_id: 't1' }, type: 'tool.complete' } as any)

    const tools = liveTools()

    expect(tools).toHaveLength(2)
    expect(tools[0]).toContain('auto-approved: recursive delete')
    expect(tools[1]).toContain('Terminal')
  })

  it('stays out of the transcript when no turn is running', () => {
    const onEvent = createGatewayEventHandler(buildCtx([]))

    onEvent({ payload: { command: 'rm -rf build', verdict: 'approve' }, type: 'approval.reviewed' } as any)

    expect(liveTools()).toEqual([])
  })
})
