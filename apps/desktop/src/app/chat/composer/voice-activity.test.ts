import { describe, expect, it } from 'vitest'

import { liveTranscriptTail } from './voice-activity'

describe('liveTranscriptTail', () => {
  it('keeps short text as it is, whitespace tidied', () => {
    expect(liveTranscriptTail('  hello   there \n friend ')).toBe('hello there friend')
  })

  it('keeps the newest words of long text, cut at a word', () => {
    const words = Array.from({ length: 60 }, (_, i) => `word${i}`).join(' ')
    const tail = liveTranscriptTail(words, 40)

    expect(tail.startsWith('…')).toBe(true)
    expect(tail.endsWith('word59')).toBe(true)
    expect(tail.length).toBeLessThanOrEqual(41)
    expect(
      tail
        .slice(1)
        .split(' ')
        .every(w => /^word\d+$/.test(w))
    ).toBe(true)
  })
})
