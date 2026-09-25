import { PassThrough } from 'stream'

import { renderSync } from '@robo/ink'
import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createGatewayEventHandler } from '../app/createGatewayEventHandler.js'
import { resetOverlayState } from '../app/overlayStore.js'
import {
  clearMidTurnSends,
  consumeLocalUserEcho,
  midTurnStatusFromGateway,
  rememberLocalUserEcho,
  settleMidTurnSend,
  submitPrompt,
  type SubmitPromptDeps,
  trackMidTurnSend
} from '../app/submissionCore.js'
import { turnController } from '../app/turnController.js'
import { resetTurnState } from '../app/turnStore.js'
import { getUiState, patchUiState, resetUiState } from '../app/uiStore.js'
import { MID_TURN_STATUS_LABEL, MidTurnSent, midTurnSentHeading } from '../components/midTurnSent.js'
import type { GatewayClient } from '../gatewayClient.js'
import { stripAnsi } from '../lib/text.js'
import { DEFAULT_THEME } from '../theme.js'
import type { Msg } from '../types.js'

// A message sent while a turn is running used to land only in the settled
// transcript — above the live reply block, i.e. off-screen once that block is
// tall — so the user could not tell whether Enter did anything until the model
// reacted. These pin the composer strip that now vouches for every mid-turn
// send: 'sending' the instant Enter is pressed, then what the gateway did.

// Enough microtask turns for detect_drop → prompt.submit → then/catch.
const flush = async () => {
  for (let i = 0; i < 6; i++) {
    await Promise.resolve()
  }
}

function makeGateway(submitResult: unknown = { status: 'redirected' }) {
  const calls: string[] = []

  const gw = {
    request: vi.fn((method: string) => {
      calls.push(method)

      if (method === 'input.detect_drop') {
        return Promise.resolve({ matched: false })
      }

      return submitResult instanceof Error ? Promise.reject(submitResult) : Promise.resolve(submitResult)
    })
  } as unknown as GatewayClient

  return { calls, gw }
}

const makeDeps = (gw: GatewayClient, over: Partial<SubmitPromptDeps> = {}): SubmitPromptDeps => ({
  appendMessage: vi.fn(),
  enqueue: vi.fn(),
  expand: (t: string) => t,
  gw,
  setLastUserMsg: vi.fn(),
  sys: vi.fn(),
  ...over
})

const rows = () => getUiState().midTurnSent.map(item => [item.text, item.status])

describe('submissionCore mid-turn send tracking', () => {
  beforeEach(() => {
    resetUiState()
    patchUiState({ sid: 'sess-1' })
  })

  it('tracks a send as "sending" and settles it in place', () => {
    const id = trackMidTurnSend('  also check the logs  ')

    expect(rows()).toEqual([['also check the logs', 'sending']])

    settleMidTurnSend(id, 'sent')
    expect(rows()).toEqual([['also check the logs', 'sent']])

    settleMidTurnSend(id, 'queued')
    expect(rows()).toEqual([['also check the logs', 'queued']])
  })

  it('drops a send the gateway did not take and ignores unknown ids', () => {
    const id = trackMidTurnSend('never made it')

    settleMidTurnSend(id, 'dropped')
    expect(rows()).toEqual([])

    const settled = getUiState()
    settleMidTurnSend(id + 1000, 'sent')
    // Unknown id: no store write at all (same state object).
    expect(getUiState()).toBe(settled)
  })

  it('keeps only the newest rows and clears on demand', () => {
    for (let i = 0; i < 8; i++) {
      trackMidTurnSend(`message ${i}`)
    }

    expect(rows().map(([text]) => text)).toEqual(['message 3', 'message 4', 'message 5', 'message 6', 'message 7'])

    clearMidTurnSends()
    expect(rows()).toEqual([])
  })

  it('maps the gateway answer: queued / redirected / steered keep their meaning, anything else is delivered', () => {
    expect(midTurnStatusFromGateway('queued')).toBe('queued')
    expect(midTurnStatusFromGateway('redirected')).toBe('redirected')
    expect(midTurnStatusFromGateway('steered')).toBe('steered')
    expect(midTurnStatusFromGateway(undefined)).toBe('sent')
    expect(midTurnStatusFromGateway('accepted')).toBe('sent')
  })

  it('labels a steer so the user sees it will only be read after the current step', () => {
    expect(MID_TURN_STATUS_LABEL.steered).toContain('after this step')
    expect(MID_TURN_STATUS_LABEL.steered).toContain('/busy interrupt')
    expect(MID_TURN_STATUS_LABEL.redirected).toContain('reading it now')
  })
})

describe('submissionCore.submitPrompt — mid-turn sends', () => {
  beforeEach(() => {
    resetUiState()
    patchUiState({ sid: 'sess-1' })
  })

  it('lists a mid-turn send synchronously, before any RPC resolves', () => {
    const { gw } = makeGateway()

    submitPrompt('hurry up', makeDeps(gw), true, undefined, true)

    expect(rows()).toEqual([['hurry up', 'sending']])
    expect(getUiState().busy).toBe(true)
  })

  it('settles to "redirected" when the gateway redirected the live turn', async () => {
    const { calls, gw } = makeGateway({ status: 'redirected' })

    submitPrompt('use Postgres', makeDeps(gw), true, undefined, true)
    await flush()

    expect(calls).toEqual(['input.detect_drop', 'prompt.submit'])
    expect(rows()).toEqual([['use Postgres', 'redirected']])
  })

  it('settles to "queued" when the gateway parked the text for the next turn', async () => {
    const { gw } = makeGateway({ status: 'queued' })

    submitPrompt('after this one', makeDeps(gw), true, undefined, true)
    await flush()

    expect(rows()).toEqual([['after this one', 'queued']])
  })

  it('shows the transcript label, not the model payload, for a /skill send', () => {
    const { gw } = makeGateway()

    submitPrompt('/skill full-expansion-body', makeDeps(gw), true, '/skill', true)

    expect(rows()).toEqual([['/skill', 'sending']])
  })

  it('drops the row when prompt.submit fails (the sys note owns the failure)', async () => {
    const { gw } = makeGateway(new Error('gateway exploded'))
    const sys = vi.fn()

    submitPrompt('lost one', makeDeps(gw, { sys }), true, undefined, true)
    expect(rows()).toEqual([['lost one', 'sending']])

    await flush()

    expect(rows()).toEqual([])
    expect(sys).toHaveBeenCalledWith('error: gateway exploded')
  })

  it('drops the row when a legacy gateway answers "session busy" and re-queues locally', async () => {
    const { gw } = makeGateway(new Error('session busy'))
    const enqueue = vi.fn()

    submitPrompt('legacy path', makeDeps(gw, { enqueue }), true, undefined, true)
    await flush()

    expect(rows()).toEqual([])
    expect(enqueue).toHaveBeenCalledWith('legacy path')
  })

  it('a fresh (idle) turn clears rows left over from the previous one', () => {
    const { gw } = makeGateway()
    trackMidTurnSend('stale')

    submitPrompt('new turn', makeDeps(gw))

    expect(rows()).toEqual([])
  })

  it('remembers the expanded payload so the gateway echo of a paste send is not painted twice', async () => {
    const { gw } = makeGateway()
    const expand = (t: string) => t.replace('[[ paste ]]', 'line one\nline two')

    submitPrompt('review [[ paste ]]', makeDeps(gw, { expand }), true, undefined, true)
    await flush()

    expect(consumeLocalUserEcho('review line one\nline two')).toBe(true)
    // The composer form is remembered as before; nothing else leaks in.
    expect(consumeLocalUserEcho('review [[ paste ]]')).toBe(true)
    expect(consumeLocalUserEcho('review line one\nline two')).toBe(false)
  })
})

describe('turnController.idle clears the strip', () => {
  beforeEach(() => {
    resetUiState()
    resetTurnState()
    turnController.fullReset()
  })

  it('drops every row when the turn ends', () => {
    trackMidTurnSend('one')
    trackMidTurnSend('two')
    patchUiState({ busy: true })

    turnController.idle()

    expect(getUiState().busy).toBe(false)
    expect(rows()).toEqual([])
  })
})

describe('message.user echo → strip', () => {
  const ref = <T,>(current: T) => ({ current })

  const buildCtx = (appended: Msg[]) =>
    ({
      composer: {
        dequeue: () => undefined,
        queueEditRef: ref<null | number>(null),
        sendQueued: vi.fn(),
        setInput: vi.fn()
      },
      gateway: { gw: { request: vi.fn() }, rpc: vi.fn(async () => null) },
      prompts: { answerClarifyRef: { current: vi.fn() } },
      session: {
        STARTUP_RESUME_ID: '',
        colsRef: ref(80),
        newSession: vi.fn(),
        resetSession: vi.fn(),
        resumeById: vi.fn(),
        setCatalog: vi.fn()
      },
      submission: { submitRef: { current: vi.fn() } },
      system: { bellOnComplete: false, sys: vi.fn() },
      transcript: {
        appendMessage: (msg: Msg) => appended.push(msg),
        panel: vi.fn(),
        setHistoryItems: vi.fn()
      },
      voice: { setProcessing: vi.fn(), setRecording: vi.fn(), setVoiceEnabled: vi.fn() }
    }) as any

  beforeEach(() => {
    resetOverlayState()
    resetUiState()
    resetTurnState()
    turnController.fullReset()
    patchUiState({ busy: true, sid: 'sess-1' })
  })

  it('paints a message another client sent mid-turn and lists it with its disposition', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({
      payload: { mid_turn: true, status: 'redirected', text: 'from the desktop' },
      type: 'message.user'
    } as any)

    expect(appended).toEqual([{ role: 'user', text: 'from the desktop' }])
    expect(rows()).toEqual([['from the desktop', 'redirected']])
  })

  it('lists a queued echo as queued', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: { mid_turn: true, status: 'queued', text: 'later' }, type: 'message.user' } as any)

    expect(rows()).toEqual([['later', 'queued']])
  })

  it('skips the echo of a send this client already painted and tracked', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    rememberLocalUserEcho('mine')
    trackMidTurnSend('mine')

    onEvent({ payload: { mid_turn: true, status: 'steered', text: 'mine' }, type: 'message.user' } as any)

    expect(appended).toEqual([])
    expect(rows()).toEqual([['mine', 'sending']])
  })

  it('does not open a strip row once the turn is over or for a blank echo', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    patchUiState({ busy: false })
    onEvent({ payload: { mid_turn: true, status: 'redirected', text: 'late echo' }, type: 'message.user' } as any)
    onEvent({ payload: { mid_turn: true, text: '   ' }, type: 'message.user' } as any)

    expect(appended).toEqual([{ role: 'user', text: 'late echo' }])
    expect(rows()).toEqual([])
  })
})

describe('<MidTurnSent />', () => {
  const t = DEFAULT_THEME

  function render(items: Parameters<typeof MidTurnSent>[0]['items'], cols = 80): string {
    const stdout = new PassThrough()
    const stdin = new PassThrough()
    const stderr = new PassThrough()
    let output = ''

    Object.assign(stdout, { columns: cols, isTTY: false, rows: 24 })
    Object.assign(stdin, { isTTY: false })
    Object.assign(stderr, { isTTY: false })
    stdout.on('data', chunk => {
      output += chunk.toString()
    })

    const instance = renderSync(React.createElement(MidTurnSent, { cols, items, t }), {
      patchConsole: false,
      stderr: stderr as NodeJS.WriteStream,
      stdin: stdin as NodeJS.ReadStream,
      stdout: stdout as NodeJS.WriteStream
    })

    instance.unmount()
    instance.cleanup()

    return stripAnsi(output)
  }

  it('lists each send with its status', () => {
    const out = render([
      { id: 1, status: 'sending', text: 'also check auth.log' },
      { id: 2, status: 'sent', text: 'and the worktree ones' },
      { id: 3, status: 'queued', text: 'then summarize' }
    ])

    expect(out).toContain(midTurnSentHeading(3))

    // Off a real terminal Ink repaints the frame on unmount, so the capture
    // holds every line more than once: assert per row, never by counting
    // across the whole output.
    const row = (text: string) => out.split('\n').find(line => line.includes(text)) ?? ''

    expect(row('also check auth.log')).toContain(MID_TURN_STATUS_LABEL.sending)
    expect(row('also check auth.log')).not.toContain('✓')
    expect(row('and the worktree ones')).toContain('✓')
    expect(row('and the worktree ones')).toContain(MID_TURN_STATUS_LABEL.sent)
    expect(row('then summarize')).toContain('✓')
    expect(row('then summarize')).toContain(MID_TURN_STATUS_LABEL.queued)
  })

  it('collapses a long message to one line', () => {
    const out = render([{ id: 1, status: 'sent', text: `${'x'.repeat(200)}\n\nsecond paragraph` }], 60)

    expect(out).toContain('…')
    expect(out).not.toContain('second paragraph')
  })
})
