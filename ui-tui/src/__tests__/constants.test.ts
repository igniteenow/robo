import { describe, expect, it } from 'vitest'

import { FACES } from '../content/faces.js'
import { HOTKEYS } from '../content/hotkeys.js'
import { PLACEHOLDERS } from '../content/placeholders.js'
import { TOOL_VERBS, VERBS } from '../content/verbs.js'
import {
  AGENT_LABEL_MAX,
  agentLabel,
  normalizeUserName,
  ROLE,
  shouldShowReplyHeader,
  userLabel
} from '../domain/roles.js'
import { ZERO } from '../domain/usage.js'
import { replyHeaderRuleWidth } from '../lib/inputMetrics.js'
import { INTERPOLATION_RE } from '../protocol/interpolation.js'
import { DEFAULT_THEME } from '../theme.js'

describe('constants', () => {
  it('ZERO', () => expect(ZERO).toEqual({ calls: 0, input: 0, output: 0, total: 0 }))

  it('string arrays are populated', () => {
    for (const arr of [FACES, PLACEHOLDERS, VERBS]) {
      expect(arr.length).toBeGreaterThan(0)
      arr.forEach(s => expect(typeof s).toBe('string'))
    }
  })

  it('HOTKEYS are [key, desc] pairs', () => {
    HOTKEYS.forEach(([k, d]) => {
      expect(typeof k).toBe('string')
      expect(typeof d).toBe('string')
    })
  })

  it('documents Ctrl/Cmd+L as non-destructive redraw', () => {
    const hotkey = HOTKEYS.find(([k]) => k.endsWith('+L'))
    expect(hotkey).toBeDefined()
    expect(hotkey?.[1]).toBe('redraw / repaint')
  })

  it('TOOL_VERBS maps known tools (verb-only, no emoji)', () => {
    expect(TOOL_VERBS.terminal).toBe('terminal')
    expect(TOOL_VERBS.read_file).toBe('reading')
  })

  it('INTERPOLATION_RE matches {!cmd}', () => {
    INTERPOLATION_RE.lastIndex = 0
    expect(INTERPOLATION_RE.test('{!date}')).toBe(true)

    INTERPOLATION_RE.lastIndex = 0
    expect(INTERPOLATION_RE.test('plain')).toBe(false)
  })

  it('ROLE produces glyph/body/prefix per role', () => {
    for (const role of ['assistant', 'system', 'tool', 'user'] as const) {
      expect(ROLE[role](DEFAULT_THEME)).toHaveProperty('glyph')
    }
  })

  it('labels Robo’s lines $Robo, or $<name> when a skin renames the agent', () => {
    expect(ROLE.assistant(DEFAULT_THEME).glyph).toBe('$Robo')
    expect(agentLabel('Cyber Agent')).toBe('$CyberAgent')
    expect(agentLabel('')).toBe('$Robo')
    expect(agentLabel(undefined)).toBe('$Robo')
    // A very long skin name is clamped so it never eats the transcript width.
    expect(agentLabel('x'.repeat(40)).length).toBe(AGENT_LABEL_MAX)
    // Only Robo's lines change: the person's prompt glyph and system dots stay.
    expect(ROLE.user(DEFAULT_THEME).glyph).toBe(DEFAULT_THEME.brand.prompt)
    expect(ROLE.system(DEFAULT_THEME).glyph).toBe('·')
  })

  it('labels the person $<name> from display.user_name, or nothing without one', () => {
    expect(userLabel('Ahmi')).toBe('$Ahmi')
    expect(userLabel('  Ahmi   Khan ')).toBe('$AhmiKhan')
    expect(userLabel('')).toBe('')
    expect(userLabel(undefined)).toBe('')
    expect(userLabel('   ')).toBe('')
    expect(userLabel('x'.repeat(60)).length).toBe(AGENT_LABEL_MAX)
    expect(normalizeUserName(' Ahmi \n Khan ')).toBe('Ahmi Khan')
    expect(normalizeUserName(42)).toBe('42')
    expect(normalizeUserName(null)).toBe('')
  })

  it('heads Robo’s prose with the label and a rule to the transcript edge', () => {
    expect(shouldShowReplyHeader({ role: 'assistant', text: 'Done.' })).toBe(true)
    // no header for an empty streaming placeholder, slash output, diffs, or anyone else
    expect(shouldShowReplyHeader({ role: 'assistant', text: '  ' })).toBe(false)
    expect(shouldShowReplyHeader({ kind: 'slash', role: 'assistant', text: 'x' })).toBe(false)
    expect(shouldShowReplyHeader({ kind: 'diff', role: 'assistant', text: 'x' })).toBe(false)
    expect(shouldShowReplyHeader({ role: 'user', text: 'x' })).toBe(false)
    // 80 cols - 4 reserve - `$Robo` (5) - space = 70; termux reserves 2
    expect(replyHeaderRuleWidth(80, '$Robo')).toBe(70)
    expect(replyHeaderRuleWidth(80, '$Robo', true)).toBe(72)
    expect(replyHeaderRuleWidth(8, '$Robo')).toBe(3)
  })

  it('renders the user’s own messages at full text strength, not the dimmer label tone', () => {
    const user = ROLE.user(DEFAULT_THEME)

    expect(user.body).toBe(DEFAULT_THEME.color.text)
    expect(user.body).toBe(ROLE.assistant(DEFAULT_THEME).body)
    // The prompt glyph keeps its label tint so the gutter still reads as "you".
    expect(user.prefix).toBe(DEFAULT_THEME.color.label)
  })
})
