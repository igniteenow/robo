import { describe, expect, it } from 'vitest'

import { expressionForStatus } from '../components/roboCommandDeck.js'

describe('Robo command-deck expressions', () => {
  it('maps operator-facing states to stable expressions', () => {
    expect(expressionForStatus('ready', false)).toBe('happy')
    expect(expressionForStatus('thinking', true)).toBe('working')
    expect(expressionForStatus('approval required', false)).toBe('approval')
    expect(expressionForStatus('tool failed', false)).toBe('error')
    expect(expressionForStatus('idle', false)).toBe('idle')
  })
})
