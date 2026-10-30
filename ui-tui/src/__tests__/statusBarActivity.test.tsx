import { PassThrough } from 'stream'

import { renderSync } from '@robo/ink'
import React from 'react'
import { beforeEach, describe, expect, it } from 'vitest'

import { patchTurnState, resetTurnState } from '../app/turnStore.js'
import { patchUiState, resetUiState } from '../app/uiStore.js'
import { StatusRule } from '../components/appChrome.js'
import { VERBS } from '../content/verbs.js'
import { stripAnsi } from '../lib/text.js'
import { DEFAULT_THEME } from '../theme.js'

// While Robo works, the status bar names the real step — "running…",
// "reading…", "writing…", "thinking…" — not a decorative verb picked at
// random. The decorative rotation is still there for
// display.friendly_tool_labels: false.

const settle = async () => {
  await new Promise(resolve => setImmediate(resolve))
  await new Promise(resolve => setImmediate(resolve))
}

async function renderBusy(): Promise<string> {
  const stdout = new PassThrough()
  const stdin = new PassThrough()
  const stderr = new PassThrough()
  let output = ''

  Object.assign(stdout, { columns: 120, isTTY: false, rows: 10 })
  Object.assign(stdin, { isTTY: false })
  Object.assign(stderr, { isTTY: false })
  stdout.on('data', chunk => {
    output += chunk.toString()
  })

  const instance = renderSync(
    <StatusRule
      bgCount={0}
      busy
      cols={120}
      cwdLabel="~/repo"
      liveSessionCount={0}
      model="opus-4.8"
      sessionStartedAt={null}
      status="running…"
      statusColor={DEFAULT_THEME.color.ok}
      t={DEFAULT_THEME}
      turnStartedAt={Date.now() - 5_000}
      usage={{ context_max: 200_000, context_percent: 25, context_used: 50_000, total: 50_000 }}
      voiceLabel=""
    />,
    {
      patchConsole: false,
      stderr: stderr as NodeJS.WriteStream,
      stdin: stdin as NodeJS.ReadStream,
      stdout: stdout as NodeJS.WriteStream
    }
  )

  await settle()
  instance.unmount()
  instance.cleanup()

  return stripAnsi(output)
}

describe('status bar — the verb is what Robo is doing', () => {
  beforeEach(() => {
    resetUiState()
    resetTurnState()
  })

  it('names the running tool', async () => {
    patchTurnState({ tools: [{ context: 'npm test', id: 't1', name: 'terminal', startedAt: Date.now() }] })

    expect(await renderBusy()).toContain('running…')

    patchTurnState({ tools: [{ context: 'src/app.ts', id: 't2', name: 'read_file', startedAt: Date.now() }] })

    expect(await renderBusy()).toContain('reading…')
  })

  it('says "writing…" while the answer streams and "thinking…" while waiting on the model', async () => {
    patchTurnState({ streaming: 'The fix is' })

    expect(await renderBusy()).toContain('writing…')

    patchTurnState({ streaming: '' })

    const frame = await renderBusy()

    expect(frame).toContain('thinking…')

    for (const verb of VERBS) {
      expect(frame).not.toContain(`${verb}…`)
    }
  })

  it('keeps the decorative rotation when friendly labels are switched off', async () => {
    patchUiState({ friendlyToolLabels: false })
    patchTurnState({ tools: [{ context: 'npm test', id: 't1', name: 'terminal', startedAt: Date.now() }] })

    const frame = await renderBusy()

    expect(frame).not.toContain('running…')
    expect(VERBS.some(verb => frame.includes(`${verb}…`))).toBe(true)
  })
})
