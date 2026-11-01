import { PassThrough } from 'stream'

import { renderSync } from '@robo/ink'
import React from 'react'
import { describe, expect, it } from 'vitest'

import { patchUiState, resetUiState } from '../app/uiStore.js'
import { MessageLine } from '../components/messageLine.js'
import { MAX_HISTORY } from '../config/limits.js'
import { toTranscriptMessages } from '../domain/messages.js'
import { capTranscriptHistory, upsert } from '../lib/messages.js'
import { stripAnsi } from '../lib/text.js'
import { DEFAULT_THEME } from '../theme.js'
import type { Msg } from '../types.js'

describe('toTranscriptMessages', () => {
  it('preserves assistant tool-call rows so resume does not drop prior turns', () => {
    const rows = [
      { role: 'user', text: 'first prompt' },
      { role: 'tool', context: 'repo', name: 'search_files', text: 'ignored raw result' },
      { role: 'assistant', text: 'first answer' },
      { role: 'user', text: 'second prompt' }
    ]

    expect(toTranscriptMessages(rows).map(msg => [msg.role, msg.text])).toEqual([
      ['user', 'first prompt'],
      ['assistant', 'first answer'],
      ['user', 'second prompt']
    ])
    expect(toTranscriptMessages(rows)[1]?.tools?.[0]).toContain('Search Files')
  })

  it('skips hidden display_kind rows entirely', () => {
    const rows = [
      { role: 'user', text: 'visible prompt' },
      { role: 'user', text: '[CONTEXT COMPACTION — REFERENCE ONLY]', display_kind: 'hidden' },
      { role: 'assistant', text: 'visible reply' }
    ]

    const result = toTranscriptMessages(rows)
    expect(result.map(msg => msg.text)).toEqual(['visible prompt', 'visible reply'])
    expect(result.every(m => !m.text?.includes('COMPACTION'))).toBe(true)
  })

  it('projects model_switch as an event with replaced text', () => {
    const rows = [
      { role: 'user', text: 'hello' },
      { role: 'user', text: '[System: model changed to gpt-5]', display_kind: 'model_switch' },
      { role: 'assistant', text: 'hi' }
    ]

    const result = toTranscriptMessages(rows)
    expect(result.map(msg => [msg.kind, msg.role, msg.text])).toEqual([
      [undefined, 'user', 'hello'],
      ['event', 'system', 'model changed'],
      [undefined, 'assistant', 'hi']
    ])
  })

  it('projects async_delegation_complete with task_count metadata', () => {
    const rows = [
      { role: 'user', text: 'do work' },
      { role: 'assistant', text: 'done' },
      {
        role: 'user',
        text: '[IMPORTANT: delegation done]',
        display_kind: 'async_delegation_complete',
        display_metadata: { task_count: 3 }
      },
      { role: 'assistant', text: 'merged' }
    ]

    const result = toTranscriptMessages(rows)
    expect(result.map(msg => [msg.kind, msg.text])).toEqual([
      [undefined, 'do work'],
      [undefined, 'done'],
      ['event', '3 background agents finished'],
      [undefined, 'merged']
    ])
  })

  it('projects async_delegation_complete without metadata as generic text', () => {
    const rows = [{ role: 'user', text: 'event', display_kind: 'async_delegation_complete' }]

    const result = toTranscriptMessages(rows)
    expect(result[0]?.kind).toBe('event')
    expect(result[0]?.text).toBe('background agent work finished')
  })
})

describe('MessageLine', () => {
  it('preserves a separator after compound user prompt glyphs in transcript rows', () => {
    const stdout = new PassThrough()
    const stdin = new PassThrough()
    const stderr = new PassThrough()
    let output = ''

    Object.assign(stdout, { columns: 80, isTTY: false, rows: 24 })
    Object.assign(stdin, { isTTY: false })
    Object.assign(stderr, { isTTY: false })
    stdout.on('data', chunk => {
      output += chunk.toString()
    })

    const t = {
      ...DEFAULT_THEME,
      brand: { ...DEFAULT_THEME.brand, prompt: 'Ψ >' }
    }

    const instance = renderSync(
      React.createElement(MessageLine, {
        cols: 80,
        msg: { role: 'user', text: 'Okay' },
        t
      }),
      {
        patchConsole: false,
        stderr: stderr as NodeJS.WriteStream,
        stdin: stdin as NodeJS.ReadStream,
        stdout: stdout as NodeJS.WriteStream
      }
    )

    instance.unmount()
    instance.cleanup()

    const renderedLine = stripAnsi(output)
      .split('\n')
      .find(line => line.includes('Okay'))

    expect(renderedLine).toContain('Ψ > Okay')
  })

  const renderLines = (msg: Msg, cols = 40) => {
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

    const instance = renderSync(React.createElement(MessageLine, { cols, msg, t: DEFAULT_THEME }), {
      patchConsole: false,
      stderr: stderr as NodeJS.WriteStream,
      stdin: stdin as NodeJS.ReadStream,
      stdout: stdout as NodeJS.WriteStream
    })

    instance.unmount()
    instance.cleanup()

    return stripAnsi(output)
      .split('\n')
      .map(line => line.trimEnd())
      .filter(Boolean)
  }

  it('opens a reply with a `$Robo` header row and indents the text under it', () => {
    const lines = renderLines({ role: 'assistant', text: 'Hey there' })
    const header = lines.findIndex(line => line.startsWith('$Robo '))

    expect(header).toBeGreaterThanOrEqual(0)
    expect(lines[header]).toMatch(/^\$Robo ─{3,}$/)
    // the rule stops at the transcript's right edge: 40 cols - 4 reserve
    expect(lines[header]!.length).toBe(36)
    // (a non-TTY stream repeats the frame on unmount, so match the start)
    expect(lines[header + 1]).toMatch(/^ {3}Hey there/)
  })

  it('closes a reply with its receipt row under the body', () => {
    const lines = renderLines({ receipt: '7.6s · 1 search · 10:39 PM', role: 'assistant', text: 'Here you go.' })
    const body = lines.findIndex(line => line.startsWith('   Here you go.'))

    expect(body).toBeGreaterThanOrEqual(0)
    expect(lines[body + 1]).toMatch(/^ {3}✓ 7\.6s · 1 search · 10:39 PM/)
  })

  it('keeps the person’s prompt glyph and draws no header for their messages', () => {
    const lines = renderLines({ role: 'user', text: 'hi' })

    expect(lines.some(line => line.includes('$Robo'))).toBe(false)
    expect(lines.some(line => /^\$/.test(line))).toBe(false)
  })

  it('heads the person’s messages $<name> once display.user_name is set', () => {
    patchUiState({ userName: 'Ahmi' })

    try {
      const lines = renderLines({ role: 'user', text: 'hi' })
      const header = lines.findIndex(line => line.startsWith('$Ahmi '))

      expect(header).toBeGreaterThanOrEqual(0)
      expect(lines[header]).toMatch(/^\$Ahmi ─{3,}$/)
      expect(lines[header + 1]).toMatch(/^› hi/)
    } finally {
      resetUiState()
    }
  })
})

describe('upsert', () => {
  it('appends when last role differs', () => {
    expect(upsert([{ role: 'user', text: 'hi' }], 'assistant', 'hello')).toHaveLength(2)
  })

  it('replaces when last role matches', () => {
    expect(upsert([{ role: 'assistant', text: 'partial' }], 'assistant', 'full')[0]!.text).toBe('full')
  })

  it('appends to empty', () => {
    expect(upsert([], 'user', 'first')).toEqual([{ role: 'user', text: 'first' }])
  })

  it('does not mutate', () => {
    const prev = [{ role: 'user' as const, text: 'hi' }]
    upsert(prev, 'assistant', 'yo')
    expect(prev).toHaveLength(1)
  })
})

describe('capTranscriptHistory', () => {
  it('keeps the intro and the newest bounded display rows', () => {
    const intro = { kind: 'intro' as const, role: 'system' as const, text: '' }
    const rows = Array.from({ length: 1_005 }, (_, index) => ({ role: 'user' as const, text: `m${index}` }))
    const capped = capTranscriptHistory([intro, ...rows])

    expect(capped).toHaveLength(MAX_HISTORY)
    expect(capped[0]).toBe(intro)
    expect(capped[1]?.text).toBe(`m${rows.length - (MAX_HISTORY - 1)}`)
    expect(capped.at(-1)?.text).toBe('m1004')
  })
})
