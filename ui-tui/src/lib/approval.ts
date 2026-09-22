import type { ApprovalReq } from '../types.js'

export const APPROVAL_CHOICES = ['once', 'session', 'deny'] as const

export type ApprovalChoice = (typeof APPROVAL_CHOICES)[number]
export type SpokenApprovalAction = ApprovalChoice | 'show' | 'wait'

export function approvalOptions(req: ApprovalReq): readonly ApprovalChoice[] {
  if (req.choices) {
    return req.choices.filter((choice): choice is ApprovalChoice =>
      APPROVAL_CHOICES.includes(choice as ApprovalChoice)
    )
  }

  return APPROVAL_CHOICES
}

/**
 * Parse only short, deliberate approval utterances. This intentionally does
 * not search inside ordinary sentences: a transcript such as "do not allow
 * this command yet" must never become an approval merely because it contains
 * the word "allow".
 */
export function parseSpokenApproval(raw: string): SpokenApprovalAction | null {
  const phrase = raw
    .trim()
    .toLowerCase()
    .replace(/[.,!?;:]+/g, '')
    .replace(/\s+/g, ' ')

  if (!phrase || phrase.split(' ').length > 6) {
    return null
  }

  if (['yes', 'yes robo', 'allow', 'approve', 'approved', 'go ahead', 'proceed', 'allow once', 'approve once'].includes(phrase)) {
    return 'once'
  }

  if (
    [
      'allow for this session',
      'allow this session',
      'approve for this session',
      'approve this session',
      'for this session',
      'session'
    ].includes(phrase)
  ) {
    return 'session'
  }

  // Older voice instructions used "always". Treat that phrase as the modern
  // session-wide grant instead of exposing a permanent hidden allowlist.
  if (['always allow', 'allow always', 'permanent allow', 'allow permanently', 'always'].includes(phrase)) {
    return 'session'
  }

  if (['no', 'no robo', 'deny', 'denied', 'reject', 'cancel'].includes(phrase)) {
    return 'deny'
  }

  if (['show', 'show command', 'show full command', 'show details', 'details'].includes(phrase)) {
    return 'show'
  }

  if (['wait', 'wait robo', 'hold', 'hold on', 'not yet'].includes(phrase)) {
    return 'wait'
  }

  return null
}
