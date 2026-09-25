import { describe, expect, it } from 'vitest'

import {
  applyPrintableInsert,
  shouldRouteMultiCharInputAsPaste,
  shouldSuppressRepeatSubmit,
  SUBMIT_REPEAT_GUARD_MS,
  type SubmitGuardState
} from '../components/textInput.js'

describe('applyPrintableInsert', () => {
  it('applies non-bracketed multi-character bursts immediately', () => {
    const burst = applyPrintableInsert('abc', 3, 'xxxxx')

    const repeated = [...'xxxxx'].reduce((state, ch) => applyPrintableInsert(state.value, state.cursor, ch)!, {
      cursor: 3,
      value: 'abc'
    })

    expect(burst).toEqual({ cursor: 8, value: 'abcxxxxx' })
    expect(burst).toEqual(repeated)
  })

  it('replaces the selected range for burst input', () => {
    expect(applyPrintableInsert('abZZef', 4, 'cd', { end: 4, start: 2 })).toEqual({
      cursor: 4,
      value: 'abcdef'
    })
  })

  it('rejects control or escape-bearing input', () => {
    expect(applyPrintableInsert('abc', 3, '\x1b[200~pasted')).toBeNull()
    expect(applyPrintableInsert('abc', 3, '\t')).toBeNull()
  })
})

describe('shouldSuppressRepeatSubmit', () => {
  const fresh = (): SubmitGuardState => ({ at: 0, value: '' })

  it('lets the first return through and swallows a replayed burst of the same text', () => {
    const state = fresh()

    expect(shouldSuppressRepeatSubmit(state, '/voice off', 1000)).toBe(false)

    // A held key / buffered stdin: forty returns 30 ms apart, the parent has
    // not cleared the value yet. One submit, not forty-one.
    const dropped = Array.from({ length: 40 }, (_, i) => shouldSuppressRepeatSubmit(state, '/voice off', 1030 + i * 30))

    expect(dropped.every(Boolean)).toBe(true)
  })

  it('slides the window with every return so a long burst stays one submit', () => {
    const state = fresh()

    shouldSuppressRepeatSubmit(state, 'stop', 0)

    let t = 0

    for (let i = 0; i < 100; i += 1) {
      t += SUBMIT_REPEAT_GUARD_MS - 50 // each return inside the window of the previous one
      expect(shouldSuppressRepeatSubmit(state, 'stop', t)).toBe(true)
    }

    // The burst ends; a deliberate resubmit later goes through.
    expect(shouldSuppressRepeatSubmit(state, 'stop', t + SUBMIT_REPEAT_GUARD_MS + 1)).toBe(false)
  })

  it('never suppresses a changed value or an empty return', () => {
    const state = fresh()

    expect(shouldSuppressRepeatSubmit(state, 'one', 0)).toBe(false)
    expect(shouldSuppressRepeatSubmit(state, 'two', 10)).toBe(false)
    // Empty returns are the double-Enter interrupt gesture — always delivered.
    expect(shouldSuppressRepeatSubmit(state, '', 20)).toBe(false)
    expect(shouldSuppressRepeatSubmit(state, '', 30)).toBe(false)
    expect(shouldSuppressRepeatSubmit(state, '   ', 40)).toBe(false)
  })
})

describe('shouldRouteMultiCharInputAsPaste', () => {
  it('keeps newline-bearing chunks on the paste path', () => {
    expect(shouldRouteMultiCharInputAsPaste('hello\nworld')).toBe(true)
    expect(shouldRouteMultiCharInputAsPaste('hello\r\nworld'.replace(/\r\n/g, '\n'))).toBe(true)
  })

  it('treats repeated printable key bursts as immediate input', () => {
    expect(shouldRouteMultiCharInputAsPaste('xxxxx')).toBe(false)
  })
})
