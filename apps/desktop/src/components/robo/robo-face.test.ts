import { describe, expect, it } from 'vitest'

import { emotionForPetState } from './robo-face'

describe('emotionForPetState', () => {
  it.each([
    ['idle', 'neutral'],
    ['review', 'confused'],
    ['waiting', 'confused'],
    ['run', 'surprised'],
    ['failed', 'sad'],
    ['jump', 'happy'],
    ['wave', 'happy']
  ] as const)('maps %s to %s', (state, emotion) => {
    expect(emotionForPetState(state)).toBe(emotion)
  })
})
