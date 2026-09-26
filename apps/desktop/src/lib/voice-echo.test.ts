import { describe, expect, it } from 'vitest'

import { isFillerOnly, isLikelyEcho, speechWords } from './voice-echo'

const reply =
  "Sure! The weather in Lahore is sunny and warm today — around 31°C, with a light breeze in the evening. Don't forget water."

describe('speechWords', () => {
  it('lowercases, drops punctuation and keeps apostrophes inside words', () => {
    expect(speechWords("Don’t STOP, it's 3pm!")).toEqual(["don't", 'stop', "it's", '3pm'])
  })

  it('keeps words whole in scripts with combining marks', () => {
    expect(speechWords('نمستے دنیا')).toHaveLength(2)
    expect(speechWords('नमस्ते दुनिया')).toEqual(['नमस्ते', 'दुनिया'])
  })
})

describe('isFillerOnly', () => {
  it('treats silence and hesitation sounds as no request', () => {
    expect(isFillerOnly('')).toBe(true)
    expect(isFillerOnly('Um.')).toBe(true)
    expect(isFillerOnly('Hmm... uh')).toBe(true)
  })

  it('keeps anything with a real word', () => {
    expect(isFillerOnly('um, stop the build')).toBe(false)
    expect(isFillerOnly('wait')).toBe(false)
  })
})

describe('isLikelyEcho', () => {
  it("recognizes Robo's own reply picked up by the microphone", () => {
    expect(isLikelyEcho('sunny and warm today with a light breeze', reply)).toBe(true)
    expect(isLikelyEcho("don't forget water", reply)).toBe(true)
  })

  it('treats a short capture as echo only when the reply says it word for word', () => {
    expect(isLikelyEcho('light breeze', reply)).toBe(true)
    expect(isLikelyEcho('breeze light', reply)).toBe(false)
    expect(isLikelyEcho('wait', reply)).toBe(false)
  })

  it('lets a real interruption through even when it shares a few words with the reply', () => {
    expect(isLikelyEcho('no, what about Karachi instead?', reply)).toBe(false)
    expect(isLikelyEcho('what about the weather tomorrow', reply)).toBe(false)
  })

  it('is never echo without a reply or without words', () => {
    expect(isLikelyEcho('sunny and warm today', '')).toBe(false)
    expect(isLikelyEcho('', reply)).toBe(false)
  })
})
