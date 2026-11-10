import { describe, expect, it } from 'vitest'

import type { Msg } from '../types.js'

import {
  appendToolShelfMessage,
  canHoldToolShelf,
  isTodoDone,
  mergeToolShelfInto,
  takeLiveToolShelf
} from './liveProgress.js'

describe('isTodoDone', () => {
  it('only treats non-empty all-completed/cancelled lists as done', () => {
    expect(isTodoDone([])).toBe(false)
    expect(isTodoDone([{ content: 'x', id: 'x', status: 'completed' }])).toBe(true)
    expect(isTodoDone([{ content: 'x', id: 'x', status: 'in_progress' }])).toBe(false)
    expect(
      isTodoDone([
        { content: 'x', id: 'x', status: 'completed' },
        { content: 'y', id: 'y', status: 'cancelled' }
      ])
    ).toBe(true)
  })
})

describe('tool shelf helpers', () => {
  it('recognizes contextual thinking shelves as holders', () => {
    expect(canHoldToolShelf({ kind: 'trail', role: 'system', text: '', thinking: 'plan' })).toBe(true)
    expect(canHoldToolShelf({ kind: 'trail', role: 'system', text: '', tools: ['one ✓'] })).toBe(true)
    expect(canHoldToolShelf({ role: 'assistant', text: 'done' })).toBe(false)
  })

  it('merges source rows into an existing shelf', () => {
    expect(
      mergeToolShelfInto(
        { kind: 'trail', role: 'system', text: '', thinking: 'plan', tools: ['one ✓'] },
        { kind: 'trail', role: 'system', text: '', tools: ['two ✓'] }
      )
    ).toEqual({ kind: 'trail', role: 'system', text: '', thinking: 'plan', tools: ['one ✓', 'two ✓'] })
  })
})

describe('appendToolShelfMessage', () => {
  it('merges adjacent tool shelves into one contextual shelf', () => {
    const merged = appendToolShelfMessage([{ kind: 'trail', role: 'system', text: '', tools: ['one ✓'] }], {
      kind: 'trail',
      role: 'system',
      text: '',
      tools: ['two ✓']
    })

    expect(merged).toEqual([{ kind: 'trail', role: 'system', text: '', tools: ['one ✓', 'two ✓'] }])
  })

  it('adds tools to the nearest contextual thinking shelf', () => {
    const merged = appendToolShelfMessage(
      [{ kind: 'trail', role: 'system', text: '', thinking: 'plan', tools: ['one ✓'] }],
      { kind: 'trail', role: 'system', text: '', tools: ['two ✓'] }
    )

    expect(merged).toEqual([{ kind: 'trail', role: 'system', text: '', thinking: 'plan', tools: ['one ✓', 'two ✓'] }])
  })

  it('merges through intervening thinking-only rows back into the nearest holder', () => {
    const prev: Msg[] = [
      { kind: 'trail', role: 'system', text: '', thinking: 'plan', tools: ['one ✓'] },
      { kind: 'trail', role: 'system', text: '', thinking: 'more plan' }
    ]

    const merged = appendToolShelfMessage(prev, {
      kind: 'trail',
      role: 'system',
      text: '',
      tools: ['two ✓']
    })

    expect(merged).toHaveLength(2)
    expect(merged[0]).toEqual({
      kind: 'trail',
      role: 'system',
      text: '',
      thinking: 'plan',
      tools: ['one ✓', 'two ✓']
    })
    expect(merged[1]).toEqual({ kind: 'trail', role: 'system', text: '', thinking: 'more plan' })
  })

  it('collapses a chronological thinking/tool/thinking/tool stream into one shelf', () => {
    const events: Msg[] = [
      { kind: 'trail', role: 'system', text: '', thinking: 'plan' },
      { kind: 'trail', role: 'system', text: '', tools: ['one ✓'] },
      { kind: 'trail', role: 'system', text: '', thinking: 'more plan' },
      { kind: 'trail', role: 'system', text: '', tools: ['two ✓'] },
      { kind: 'trail', role: 'system', text: '', tools: ['three ✓'] }
    ]

    const reduced = events.reduce<Msg[]>((acc, msg) => appendToolShelfMessage(acc, msg), [])

    expect(reduced).toHaveLength(2)
    expect(reduced[0]).toEqual({
      kind: 'trail',
      role: 'system',
      text: '',
      thinking: 'plan',
      tools: ['one ✓', 'two ✓', 'three ✓']
    })
    expect(reduced[1]).toEqual({ kind: 'trail', role: 'system', text: '', thinking: 'more plan' })
  })

  it('starts a new shelf across assistant text boundaries', () => {
    const merged = appendToolShelfMessage(
      [
        { kind: 'trail', role: 'system', text: '', tools: ['one ✓'] },
        { role: 'assistant', text: 'done' }
      ],
      { kind: 'trail', role: 'system', text: '', tools: ['two ✓'] }
    )

    expect(merged).toHaveLength(3)
  })
})

// The live list of steps lifts the rows of the working phase in progress out
// of the segment that holds them — the same segment appendToolShelfMessage
// would merge the next row into — and leaves everything else as it was.
describe('takeLiveToolShelf', () => {
  it('lifts the tool rows of the current phase and keeps the reasoning they sat with', () => {
    const segments: Msg[] = [
      { role: 'assistant', text: 'Checking the config.' },
      { kind: 'trail', role: 'system', text: '', thinking: 'plan', toolTokens: 12, tools: ['one ✓', 'two ✗'] },
      { kind: 'trail', role: 'system', text: '', thinking: 'more plan' }
    ]

    const { lines, segments: rest } = takeLiveToolShelf(segments)

    expect(lines).toEqual(['one ✓', 'two ✗'])
    expect(rest).toEqual([
      { role: 'assistant', text: 'Checking the config.' },
      { kind: 'trail', role: 'system', text: '', thinking: 'plan', toolTokens: 12 },
      { kind: 'trail', role: 'system', text: '', thinking: 'more plan' }
    ])
    // Pure: the caller's segments are left alone.
    expect(segments[1]?.tools).toEqual(['one ✓', 'two ✗'])
  })

  it('agrees with appendToolShelfMessage on which segment holds the phase', () => {
    const settled: Msg[] = [
      { kind: 'trail', role: 'system', text: '', tools: ['one ✓'] },
      { role: 'assistant', text: 'Now the tests.' },
      { kind: 'trail', role: 'system', text: '', thinking: 'plan' }
    ]

    const merged = appendToolShelfMessage(settled, { kind: 'trail', role: 'system', text: '', tools: ['two ✓'] })
    const { lines, segments } = takeLiveToolShelf(merged)

    expect(lines).toEqual(['two ✓'])
    expect(segments.map(msg => msg.tools)).toEqual([['one ✓'], undefined, undefined])
  })

  it('lifts nothing across something the person sees as a step of the conversation', () => {
    const segments: Msg[] = [
      { kind: 'trail', role: 'system', text: '', tools: ['one ✓'] },
      { role: 'assistant', text: 'Here is what I found.' }
    ]

    expect(takeLiveToolShelf(segments)).toEqual({ lines: [], segments })
    expect(takeLiveToolShelf([])).toEqual({ lines: [], segments: [] })
  })
})
