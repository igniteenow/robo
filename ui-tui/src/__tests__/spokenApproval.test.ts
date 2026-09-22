import { describe, expect, it } from 'vitest'

import { approvalOptions, parseSpokenApproval } from '../lib/approval.js'

describe('spoken approval', () => {
  it.each([
    ['yes', 'once'],
    ['go ahead', 'once'],
    ['Allow once.', 'once'],
    ['allow for this session', 'session'],
    ['always allow', 'session'],
    ['no robo', 'deny'],
    ['show full command', 'show'],
    ['hold on', 'wait']
  ])('maps %s to %s', (phrase, expected) => {
    expect(parseSpokenApproval(phrase)).toBe(expected)
  })

  it.each([
    'do not allow this command yet',
    'I said yes yesterday but not today',
    'can you show me why this is needed',
    'allow this command after you explain every part of it please'
  ])('does not approve conversational text: %s', phrase => {
    expect(parseSpokenApproval(phrase)).toBeNull()
  })

  it('honors backend choice restrictions', () => {
    expect(approvalOptions({ choices: ['once', 'deny'], command: 'x', description: 'x' })).toEqual(['once', 'deny'])
    expect(approvalOptions({ allowPermanent: false, command: 'x', description: 'x' })).toEqual([
      'once',
      'session',
      'deny'
    ])
  })
})
