import { PassThrough } from 'stream'

import { renderSync } from '@robo/ink'
import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { checkSummaryNote, createGatewayEventHandler } from '../app/createGatewayEventHandler.js'
import { resetOverlayState } from '../app/overlayStore.js'
import { turnController } from '../app/turnController.js'
import { getTurnState, resetTurnState } from '../app/turnStore.js'
import { getUiState, patchUiState, resetUiState } from '../app/uiStore.js'
import { livePhase, StreamingAssistant } from '../components/streamingAssistant.js'
import { STREAM_IDLE_BATCH_MS } from '../config/timing.js'
import { ANALYZING_TRAIL_LINE, stripAnsi } from '../lib/text.js'
import type { Msg } from '../types.js'

// A long task used to show as "▸ Thinking" and "▸ Tool calls (N)" for its
// whole run — the only movement a growing number and, while a command ran,
// one line on the folded row. These drive the real event stream through the
// real live area and pin what a person following along now sees: each step
// as it happens, what Robo is doing between steps, and the same folded
// transcript as before once the turn is over.

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
      colsRef: ref(100),
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

const settle = async () => {
  for (let i = 0; i < 4; i++) {
    await new Promise(resolve => setImmediate(resolve))
  }
}

async function liveArea(cols = 100): Promise<string[]> {
  const stdout = new PassThrough()
  const stdin = new PassThrough()
  const stderr = new PassThrough()
  let output = ''

  Object.assign(stdout, { columns: cols, isTTY: false, rows: 40 })
  Object.assign(stdin, { isTTY: false })
  Object.assign(stderr, { isTTY: false })
  stdout.on('data', chunk => {
    const frame = stripAnsi(chunk.toString())

    if (frame.trim()) {
      output = frame
    }
  })

  const ui = getUiState()

  const instance = renderSync(
    <StreamingAssistant
      cols={cols}
      detailsMode={ui.detailsMode}
      detailsModeCommandOverride={ui.detailsModeCommandOverride}
      progress={{ showProgressArea: true }}
      sections={ui.sections}
    />,
    { patchConsole: false, stderr: stderr as any, stdin: stdin as any, stdout: stdout as any }
  )

  await settle()
  instance.unmount()
  instance.cleanup()

  return output
    .split('\n')
    .map(row => row.trim())
    .filter(Boolean)
}

const rowMatching = (rows: string[], text: string) => rows.find(row => row.includes(text)) ?? ''

describe('the live area while Robo works', () => {
  beforeEach(() => {
    resetOverlayState()
    resetUiState()
    resetTurnState()
    turnController.fullReset()
    patchUiState({ busy: true, showReasoning: true, sid: 'sess-1' })
  })

  it('shows each step as it happens, then the same folded transcript once the turn is over', async () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))
    const ev = (type: string, payload: Record<string, unknown> = {}) => onEvent({ payload, type } as any)

    ev('message.start')
    ev('reasoning.delta', { text: 'The user wants the port. Let me look at the config files first.' })
    ev('message.interim', { text: 'Checking the config files to find the current port.' })
    ev('tool.start', { context: 'PORT', name: 'search_files', tool_id: 't1' })
    ev('tool.complete', { duration_s: 0.4, name: 'search_files', tool_id: 't1' })
    ev('tool.start', { context: 'npm test', name: 'terminal', tool_id: 't2' })
    ev('tool.complete', { duration_s: 14.2, error: 'exit 1', name: 'terminal', tool_id: 't2' })
    ev('reasoning.delta', { text: 'One test failed. Let me fix it.' })
    ev('tool.start', { context: 'src/app.ts', name: 'patch', tool_id: 't3' })
    ev('tool.complete', { duration_s: 0.3, name: 'patch', tool_id: 't3' })
    ev('tool.start', { context: 'npm test', name: 'terminal', tool_id: 't4' })

    // A command is running: every step so far, the running one with its clock.
    let rows = await liveArea()

    expect(rows).toContain('Checking the config files to find the current port.')
    expect(rowMatching(rows, 'Working')).toContain('▾ Working  4 steps')
    expect(rowMatching(rows, 'Searched files')).toMatch(/✓ Searched files for PORT \(0\.4s\)$/)
    expect(rowMatching(rows, 'Ran npm test')).toMatch(/✗ Ran npm test \(14s\) — exit 1$/)
    expect(rowMatching(rows, 'Edited')).toMatch(/✓ Edited src\/app\.ts \(0\.3s\)$/)
    expect(rowMatching(rows, 'Running npm test')).toMatch(/Running npm test \(\d+\.\ds\)$/)
    expect(rows.join('\n')).not.toContain('Tool calls')

    // Between steps: the list stays, and its last row says what Robo is doing.
    ev('tool.complete', { duration_s: 9.9, name: 'terminal', tool_id: 't4' })
    rows = await liveArea()

    expect(rowMatching(rows, 'Working')).toContain('4 steps')
    expect(rows.at(-1)).toMatch(/analyzing tool output…$/)

    ev('reasoning.delta', { text: ' All green now; writing the answer.' })
    rows = await liveArea()

    expect(rows.at(-1)).toMatch(/thinking…$/)
    // The collapsed Thinking row carries the tail of what the model is thinking.
    expect(rowMatching(rows, '▸ Thinking  ')).toMatch(/writing the answer\.$/)

    ev('tool.generating', { name: 'read_file' })
    rows = await liveArea()

    expect(rows.at(-1)).toMatch(/Reading…$/)
    expect(rows.join('\n')).not.toContain('thinking…')

    // The answer streams in under the list; no phase row competes with it.
    ev('tool.start', { context: 'README.md', name: 'read_file', tool_id: 't5' })
    ev('tool.complete', { duration_s: 0.1, name: 'read_file', tool_id: 't5' })
    ev('message.delta', { text: 'The port is 8080.' })
    // Deltas paint on the stream batch timer.
    await new Promise(resolve => setTimeout(resolve, STREAM_IDLE_BATCH_MS * 3))
    rows = await liveArea()

    expect(rowMatching(rows, 'Working')).toContain('5 steps')
    expect(rows.join('\n')).not.toMatch(/thinking…|analyzing tool output…/)
    expect(rows).toContain('The port is 8080.')

    // Over: the transcript gets exactly the folded trail it always did.
    ev('message.complete', { text: 'The port is 8080.' })

    const trail = appended.find(msg => msg.kind === 'trail' && msg.tools?.length)

    expect(trail?.tools).toEqual([
      'Search Files("PORT") (0.4s) ✓',
      'Terminal("npm test") (14.2s) :: exit 1 ✗',
      'Patch("src/app.ts") (0.3s) ✓',
      'Terminal("npm test") (9.9s) ✓',
      'Read File("README.md") (0.1s) ✓'
    ])
    expect(appended.at(-1)).toMatchObject({ role: 'assistant', text: 'The port is 8080.' })
    expect(getUiState().busy).toBe(false)
  })

  it('leaves the expanded and hidden layouts as they were', async () => {
    const onEvent = createGatewayEventHandler(buildCtx([]))
    const ev = (type: string, payload: Record<string, unknown> = {}) => onEvent({ payload, type } as any)

    ev('message.start')
    ev('tool.start', { context: 'PORT', name: 'search_files', tool_id: 't1' })
    ev('tool.complete', { duration_s: 0.4, name: 'search_files', tool_id: 't1' })
    ev('tool.start', { context: 'npm test', name: 'terminal', tool_id: 't2' })

    patchUiState({ sections: { tools: 'expanded' } })
    let rows = await liveArea()

    expect(rowMatching(rows, 'Tool calls')).toContain('▾ Tool calls')
    expect(rows.join('\n')).not.toContain('Working')
    expect(rowMatching(rows, 'Searched')).toContain('Searched files for PORT')
    expect(rowMatching(rows, 'Running')).toContain('Running npm test')

    patchUiState({ sections: { activity: 'hidden', thinking: 'hidden', tools: 'hidden' } })
    rows = await liveArea()

    expect(rows).toEqual([])
  })

  it('shows what the turn is doing after the answer, where the eye is', async () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))
    const ev = (type: string, payload: Record<string, unknown> = {}) => onEvent({ payload, type } as any)

    ev('message.start')
    ev('tool.start', { context: 'PORT', name: 'search_files', tool_id: 't1' })
    ev('tool.complete', { duration_s: 0.4, name: 'search_files', tool_id: 't1' })
    ev('message.delta', { text: 'The port is 8080.' })
    await new Promise(resolve => setTimeout(resolve, STREAM_IDLE_BATCH_MS * 3))

    // The answer has streamed; the end-of-turn fact check starts. Its report
    // gets its own row under the answer, not a "thinking…" in the list above.
    ev('status.update', { kind: 'fact_check', text: '🔎 Checking the answer for statements to verify…' })
    let rows = await liveArea()

    expect(rows.indexOf('The port is 8080.')).toBeLessThan(rows.indexOf(rowMatching(rows, 'Checking the answer')))
    expect(rows.at(-1)).toMatch(/🔎 Checking the answer for statements to verify…$/)
    expect(rows.join('\n')).not.toMatch(/thinking…/)
    expect(getTurnState().phase).toMatchObject({ kind: 'fact_check', tone: 'info', verb: 'checking' })

    // Each research step replaces the last; the verdict is kept for the receipt.
    ev('status.update', { kind: 'fact_check', text: '🔎 Checking the answer (1/8): searching the web for "port"' })
    ev('status.update', { kind: 'lifecycle', text: '🔎 Checked 1 statement against 2 sources: confirmed' })
    ev('status.update', { kind: 'fact_check_result', text: '🔎 Checked 1 statement against 2 sources: confirmed' })
    rows = await liveArea()

    expect(rows.at(-1)).toMatch(/Checked 1 statement against 2 sources: confirmed$/)
    expect(rows.join('\n')).not.toContain('(1/8)')

    ev('message.complete', { text: 'The port is 8080.' })

    const reply = appended.find(msg => msg.role === 'assistant' && msg.text === 'The port is 8080.')

    expect(reply?.receipt).toMatch(/1 search · checked 1 statement against 2 sources: confirmed · /)
    expect(getTurnState().phase).toBeNull()
  })

  it('a phase between steps rides as the last row of the live list, until the model moves on', async () => {
    const onEvent = createGatewayEventHandler(buildCtx([]))
    const ev = (type: string, payload: Record<string, unknown> = {}) => onEvent({ payload, type } as any)

    ev('message.start')
    ev('tool.start', { context: 'src/app.ts', name: 'patch', tool_id: 't1' })
    ev('tool.complete', { duration_s: 0.3, name: 'patch', tool_id: 't1' })
    ev('message.interim', { text: 'Fixed the parser.' })
    ev('status.update', { kind: 'verify', text: '🔍 Checking the work before finishing…' })
    let rows = await liveArea()

    expect(rows.at(-1)).toMatch(/Checking the work before finishing…$/)
    expect(getTurnState().phase?.verb).toBe('verifying')

    // The model starts its verification step: the list speaks again.
    ev('tool.start', { context: 'npm test', name: 'terminal', tool_id: 't2' })
    rows = await liveArea()

    expect(getTurnState().phase).toBeNull()
    expect(rows.at(-1)).toMatch(/Running npm test/)
    expect(rows.join('\n')).not.toContain('Checking the work')

    // Reasoning after a report clears it too; a report outside a turn is ignored.
    ev('tool.complete', { duration_s: 2, name: 'terminal', tool_id: 't2' })
    ev('status.update', { kind: 'lifecycle', text: '🗜️ Compacting context — summarizing earlier conversation…' })
    expect(getTurnState().phase?.text).toContain('Compacting context')
    ev('reasoning.delta', { text: 'All green.' })
    expect(getTurnState().phase).toBeNull()
    ev('message.complete', { text: 'Done.' })
    ev('status.update', { kind: 'lifecycle', text: 'late report' })
    expect(getTurnState().phase).toBeNull()
  })

  it('turns the verdict line into a receipt fragment', () => {
    expect(checkSummaryNote('🔎 Checked 3 statements against 2 sources: confirmed')).toBe(
      'checked 3 statements against 2 sources: confirmed'
    )
    expect(checkSummaryNote('  Checked 1 statement: could not be settled')).toBe(
      'checked 1 statement: could not be settled'
    )
    expect(checkSummaryNote('🔎')).toBe('')
  })

  it('names the phase between steps', () => {
    const base = { drafting: false, reasoning: false, running: false, streaming: false, trail: [] as string[] }

    expect(livePhase(base)).toBe('thinking…')
    expect(livePhase({ ...base, trail: [ANALYZING_TRAIL_LINE] })).toBe(ANALYZING_TRAIL_LINE)
    expect(livePhase({ ...base, reasoning: true, trail: [ANALYZING_TRAIL_LINE] })).toBe('thinking…')
    expect(livePhase({ ...base, running: true })).toBe('')
    expect(livePhase({ ...base, drafting: true })).toBe('')
    expect(livePhase({ ...base, streaming: true })).toBe('')
    // A reported phase wins over the inferred ones, but never over a row
    // that already says what runs.
    expect(livePhase({ ...base, reported: '🔎 Checking the answer…', trail: [ANALYZING_TRAIL_LINE] })).toBe(
      '🔎 Checking the answer…'
    )
    expect(livePhase({ ...base, reported: '🔎 Checking the answer…', running: true })).toBe('')
  })
})
