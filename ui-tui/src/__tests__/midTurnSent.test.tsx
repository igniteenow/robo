import { PassThrough } from 'stream'

import { renderSync } from '@robo/ink'
import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createGatewayEventHandler } from '../app/createGatewayEventHandler.js'
import { resetOverlayState } from '../app/overlayStore.js'
import {
  clearMidTurnSends,
  consumeLocalUserEcho,
  MID_TURN_SETTLED_MS,
  midTurnStatusFromGateway,
  rememberLocalUserEcho,
  settleMidTurnSend,
  submitPrompt,
  type SubmitPromptDeps,
  trackMidTurnSend
} from '../app/submissionCore.js'
import { turnController } from '../app/turnController.js'
import { getTurnState, resetTurnState } from '../app/turnStore.js'
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

describe('a settled row is an acknowledgement, not a fixture', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    resetUiState()
    patchUiState({ sid: 'sess-1' })
  })

  afterEach(() => {
    clearMidTurnSends()
    vi.useRealTimers()
  })

  it('dismisses itself a few seconds after the gateway answers', () => {
    const id = trackMidTurnSend('also check the logs')

    settleMidTurnSend(id, 'steered')
    expect(rows()).toEqual([['also check the logs', 'steered']])

    vi.advanceTimersByTime(MID_TURN_SETTLED_MS - 1)
    expect(rows()).toEqual([['also check the logs', 'steered']])

    vi.advanceTimersByTime(1)
    expect(rows()).toEqual([])
  })

  it('stays while the gateway has not answered yet', () => {
    trackMidTurnSend('still on its way')

    vi.advanceTimersByTime(MID_TURN_SETTLED_MS * 10)
    expect(rows()).toEqual([['still on its way', 'sending']])
  })

  it('a row that arrives already settled (another client’s echo) goes the same way', () => {
    trackMidTurnSend('from the desktop', 'redirected')
    expect(rows()).toEqual([['from the desktop', 'redirected']])

    vi.advanceTimersByTime(MID_TURN_SETTLED_MS)
    expect(rows()).toEqual([])
  })

  it('a late settle restarts the clock and a dropped row cancels it', () => {
    const a = trackMidTurnSend('first')
    const b = trackMidTurnSend('second')

    settleMidTurnSend(a, 'sent')
    vi.advanceTimersByTime(MID_TURN_SETTLED_MS / 2)
    settleMidTurnSend(a, 'queued')
    settleMidTurnSend(b, 'dropped')
    vi.advanceTimersByTime(MID_TURN_SETTLED_MS / 2)
    // Re-settled half-way through: the clock restarted, so it is still here.
    expect(rows()).toEqual([['first', 'queued']])

    vi.advanceTimersByTime(MID_TURN_SETTLED_MS / 2)
    expect(rows()).toEqual([])
  })

  it('dismissing after the turn already cleared the strip is a no-op', () => {
    const id = trackMidTurnSend('late')

    settleMidTurnSend(id, 'sent')
    turnController.idle()
    expect(rows()).toEqual([])

    const settled = getUiState()
    vi.advanceTimersByTime(MID_TURN_SETTLED_MS)
    expect(getUiState()).toBe(settled)
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

  it('paints a message another client sent mid-turn in the live block, with no strip row to repeat it', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({
      payload: { mid_turn: true, status: 'redirected', text: 'from the desktop' },
      type: 'message.user'
    } as any)

    // It joins the live turn (shown under the work so far), not settled
    // history above it…
    expect(appended).toEqual([])
    expect(getTurnState().streamSegments).toEqual([{ role: 'user', text: 'from the desktop' }])
    // The bubble under the work is the acknowledgement.
    expect(rows()).toEqual([])

    // …and moves into the transcript with the turn when it ends.
    onEvent({ payload: { text: 'done' }, type: 'message.complete' } as any)
    expect(appended).toEqual([
      { role: 'user', text: 'from the desktop' },
      { receipt: expect.stringMatching(/\d/), role: 'assistant', text: 'done' }
    ])
  })

  it('lists a queued echo as queued (the bubble alone cannot say it was parked)', () => {
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

describe('a message sent mid-turn stays where it was sent', () => {
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
      transcript: { appendMessage: (msg: Msg) => appended.push(msg), panel: vi.fn(), setHistoryItems: vi.fn() },
      voice: { setProcessing: vi.fn(), setRecording: vi.fn(), setVoiceEnabled: vi.fn() }
    }) as any

  const userTexts = (msgs: Msg[]) => msgs.filter(m => m.role === 'user').map(m => m.text)

  beforeEach(() => {
    resetOverlayState()
    resetUiState()
    resetTurnState()
    turnController.fullReset()
    patchUiState({ sid: 'sess-1' })
  })

  it('shows under the work done so far and lands in that order when the turn completes', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: {}, type: 'message.start' } as any)
    onEvent({ payload: { text: 'Checking the config files.' }, type: 'message.interim' } as any)

    expect(turnController.recordMidTurnUserMessage({ role: 'user', text: 'also check the logs' })).toBe(true)

    onEvent({ payload: { text: 'Reading the logs now.' }, type: 'message.interim' } as any)

    // Live: in order, nothing in history yet.
    expect(appended).toEqual([])
    expect(getTurnState().streamSegments.map(m => m.text)).toEqual([
      'Checking the config files.',
      'also check the logs',
      'Reading the logs now.'
    ])

    onEvent({ payload: { text: 'Both look fine.' }, type: 'message.complete' } as any)

    const texts = appended.map(m => m.text).filter(Boolean)

    expect(texts).toEqual([
      'Checking the config files.',
      'also check the logs',
      'Reading the logs now.',
      'Both look fine.'
    ])
    // Exactly once, and the live block is empty again.
    expect(userTexts(appended)).toEqual(['also check the logs'])
    expect(getTurnState().streamSegments).toEqual([])
  })

  it('is kept in the transcript when the turn fails', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: {}, type: 'message.start' } as any)
    turnController.recordMidTurnUserMessage({ role: 'user', text: 'and the docs too' })
    onEvent({ payload: { message: 'provider exploded' }, type: 'error' } as any)

    expect(userTexts(appended)).toEqual(['and the docs too'])
    expect(getTurnState().streamSegments).toEqual([])
  })

  it('is kept, in order, when the person interrupts the turn', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: {}, type: 'message.start' } as any)
    onEvent({ payload: { text: 'Step one.' }, type: 'message.interim' } as any)
    turnController.recordMidTurnUserMessage({ role: 'user', text: 'stop after this' })
    turnController.interruptTurn({
      appendMessage: m => appended.push(m),
      gw: { request: vi.fn(async () => ({})) } as any,
      sid: 'sess-1',
      sys: vi.fn()
    })

    expect(appended.map(m => m.text).slice(0, 2)).toEqual(['Step one.', 'stop after this'])
  })

  it('places a clarify answer, with its question line, where the turn has reached', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: {}, type: 'message.start' } as any)
    onEvent({ payload: { text: 'Two ways to do this.' }, type: 'message.interim' } as any)

    const question: Msg = { kind: 'trail', role: 'system', text: '', tools: ['Clarify("Which one?")'] }
    const answer: Msg = { kind: 'clarify', role: 'user', text: 'the second' }

    expect(turnController.recordMidTurnMessages([question, answer])).toBe(true)
    // Nothing in settled history: the answer sits in the live block, under the work so far.
    expect(appended).toEqual([])
    expect(getTurnState().streamSegments.map(m => m.text)).toEqual(['Two ways to do this.', '', 'the second'])

    onEvent({ payload: { text: 'Going with the second.' }, type: 'message.interim' } as any)
    onEvent({ payload: { text: 'Done.' }, type: 'message.complete' } as any)

    // Lands in the transcript in that order, once, with the question line kept.
    expect(appended.map(m => m.text).filter(Boolean)).toEqual([
      'Two ways to do this.',
      'the second',
      'Going with the second.',
      'Done.'
    ])
    expect(appended.filter(m => m.kind === 'clarify')).toHaveLength(1)
    expect(appended.some(m => m.tools?.some(line => line.includes('Which one?')))).toBe(true)
  })

  it('falls back to the transcript when no turn is live', () => {
    expect(turnController.recordMidTurnMessages([{ kind: 'clarify', role: 'user', text: 'idle answer' }])).toBe(false)
    expect(turnController.recordMidTurnUserMessage({ role: 'user', text: 'idle send' })).toBe(false)
    expect(getTurnState().streamSegments).toEqual([])

    patchUiState({ busy: true })
    expect(turnController.recordMidTurnUserMessage({ role: 'assistant', text: 'not a user message' })).toBe(false)
  })

  it('a send placed live gets no strip row: the bubble under the work is the acknowledgement', async () => {
    const { gw } = makeGateway({ status: 'redirected' })
    const live: Msg[] = []

    submitPrompt(
      'use Postgres',
      makeDeps(gw, { appendLiveUserMessage: msg => (live.push(msg), true) }),
      true,
      undefined,
      true
    )

    expect(live).toEqual([{ role: 'user', text: 'use Postgres' }])
    expect(rows()).toEqual([])

    await flush()

    expect(rows()).toEqual([])
  })

  it('a send placed live still says so when the gateway parked it for later', async () => {
    const { gw } = makeGateway({ status: 'queued' })

    submitPrompt('after this one', makeDeps(gw, { appendLiveUserMessage: () => true }), true, undefined, true)

    expect(rows()).toEqual([])
    await flush()

    expect(rows()).toEqual([['after this one', 'queued']])
  })

  it('a send the live block could not take keeps the strip from the moment of sending', () => {
    const { gw } = makeGateway({ status: 'redirected' })

    submitPrompt('hurry up', makeDeps(gw, { appendLiveUserMessage: () => false }), true, undefined, true)

    expect(rows()).toEqual([['hurry up', 'sending']])
  })

  it('submitPrompt places a mid-turn send live and an ordinary send in history', () => {
    const gw = { request: vi.fn(() => Promise.resolve({ matched: false })) } as unknown as GatewayClient
    const live: Msg[] = []
    const history: Msg[] = []

    const deps: SubmitPromptDeps = {
      appendLiveUserMessage: msg => (live.push(msg), true),
      appendMessage: msg => history.push(msg),
      enqueue: vi.fn(),
      expand: (t: string) => t,
      gw,
      setLastUserMsg: vi.fn(),
      sys: vi.fn()
    }

    submitPrompt('fresh turn', deps)
    submitPrompt('while it works', deps, true, undefined, true)

    expect(history).toEqual([{ role: 'user', text: 'fresh turn' }])
    expect(live).toEqual([{ role: 'user', text: 'while it works' }])

    clearMidTurnSends()
  })
})
