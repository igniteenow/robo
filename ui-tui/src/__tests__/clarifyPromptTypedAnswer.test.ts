import { describe, expect, it } from 'vitest'

import { isTypedAnswerStart } from '../components/prompts.js'

const plain = { ctrl: false, meta: false }

describe('clarify picker: typing starts the free-text answer', () => {
  it('opens the answer field on a printable, unmodified, non-digit key', () => {
    expect(isTypedAnswerStart('s', plain)).toBe(true)
    expect(isTypedAnswerStart(' ', plain)).toBe(true)
    expect(isTypedAnswerStart('é', plain)).toBe(true)
    expect(isTypedAnswerStart('/', plain)).toBe(true)
  })

  it('leaves digits to the quick picks and chords to their own handlers', () => {
    expect(isTypedAnswerStart('1', plain)).toBe(false)
    expect(isTypedAnswerStart('7', plain)).toBe(false)
    expect(isTypedAnswerStart('c', { ctrl: true, meta: false })).toBe(false) // Ctrl+C cancel
    expect(isTypedAnswerStart('v', { ctrl: false, meta: true })).toBe(false) // Cmd+V paste
    expect(isTypedAnswerStart('v', { ctrl: false, meta: false, super: true })).toBe(false) // Super+V (kitty/CSI-u)
  })

  it('ignores escapes, control bytes and multi-character sequences', () => {
    expect(isTypedAnswerStart('', plain)).toBe(false)
    expect(isTypedAnswerStart('\x1b', plain)).toBe(false)
    expect(isTypedAnswerStart('\x7f', plain)).toBe(false)
    expect(isTypedAnswerStart('\x1b[A', plain)).toBe(false)
    expect(isTypedAnswerStart('ab', plain)).toBe(false)
  })
})
