import { describe, expect, it } from 'vitest'

import {
  busyComposerHint,
  composerFrameStyle,
  composerMode,
  frameBottomLayout,
  frameBottomText,
  frameTopLayout,
  frameTopText
} from '../components/composerFrame.js'
import { DEFAULT_THEME } from '../theme.js'

const cells = (s: string) => [...s].length

describe('chat box top edge', () => {
  it('is exactly the requested width with tag and hint', () => {
    const line = frameTopText(80, '◆ ROBO', '↑ history · Ctrl+B voice · /help')

    expect(cells(line)).toBe(80)
    expect(line.startsWith('╭─ ◆ ROBO ─')).toBe(true)
    expect(line.endsWith(' ↑ history · Ctrl+B voice · /help ─╮')).toBe(true)
  })

  it('drops the hint first when the line is tight, then the tag, never the corners', () => {
    const tight = frameTopLayout(30, '◆ ROBO', '↑ history · Ctrl+B voice · /help')

    expect(tight.hint).toBe('')
    expect(tight.tag).toBe('◆ ROBO')
    expect(cells(frameTopText(30, '◆ ROBO', '↑ history · Ctrl+B voice · /help'))).toBe(30)

    const tiny = frameTopLayout(8, '◆ ROBO', '')

    expect(tiny.tag).toBe('')
    expect(frameTopText(8, '◆ ROBO', '')).toBe('╭──────╮')
  })

  it('keeps at least two rule cells between tag and hint', () => {
    // '╭─ ' + tag(6) + ' ' + fill + ' hint ' + '─╮'  → hint needs fill >= 2
    const w = 3 + 6 + 1 + 2 + 6 + 2 // hint 'help' = 4 + 2 spaces
    const lay = frameTopLayout(w, '◆ ROBO', 'help')

    expect(lay).toEqual({ fill: 2, hint: 'help', tag: '◆ ROBO' })
    expect(frameTopLayout(w - 1, '◆ ROBO', 'help').hint).toBe('')
  })

  it('renders the frameless variant without corners at the same width', () => {
    const line = frameTopText(60, '◆ ROBO', '/help', true)

    expect(cells(line)).toBe(60)
    expect(line.startsWith('── ◆ ROBO ─')).toBe(true)
    expect(line.endsWith(' /help ──')).toBe(true)
    expect(frameTopText(6, '◆ ROBO', '', true)).toBe('──────')
  })
})

describe('chat box bottom edge', () => {
  it('carries the label on the right at exactly the requested width', () => {
    const line = frameBottomText(60, 'voice off')

    expect(cells(line)).toBe(60)
    expect(line.startsWith('╰───')).toBe(true)
    expect(line.endsWith('─ voice off ─╯')).toBe(true)
  })

  it('drops the label before the rule shrinks below two cells', () => {
    expect(frameBottomLayout(16, 'voice off')).toEqual({ fill: 2, label: 'voice off' })
    expect(frameBottomLayout(15, 'voice off')).toEqual({ fill: 13, label: '' })
    expect(frameBottomText(4, 'voice off')).toBe('╰──╯')
  })
})

describe('busy hint', () => {
  it('promises an immediate read only for the modes that deliver it', () => {
    expect(busyComposerHint('interrupt')).toContain('type to redirect Robo')
    expect(busyComposerHint('redirect')).toContain('type to redirect Robo')
    expect(busyComposerHint('steer')).toContain('read after this step')
    expect(busyComposerHint('steer')).toContain('/busy interrupt')
    expect(busyComposerHint('queue')).toContain('queue for the next turn')
  })
})

describe('chat box mode', () => {
  it('follows the shell prefix and the voice capture state', () => {
    expect(composerMode(false, 'voice off')).toBe('chat')
    expect(composerMode(false, 'voice on [tts]')).toBe('chat')
    expect(composerMode(true, 'voice on')).toBe('shell')
    expect(composerMode(false, '● REC')).toBe('rec')
    expect(composerMode(true, '● REC')).toBe('rec') // capture outranks the shell prefix
    expect(composerMode(false, '◉ STT')).toBe('stt')
    // /edit: the recalled text is being edited, not executed — it outranks
    // the shell prefix; voice capture still outranks it.
    expect(composerMode(false, 'voice off', true)).toBe('edit')
    expect(composerMode(true, 'voice off', true)).toBe('edit')
    expect(composerMode(false, '● REC', true)).toBe('rec')
  })

  it('maps each mode to a tag and a frame colour from the theme', () => {
    const t = DEFAULT_THEME

    expect(composerFrameStyle('chat', t)).toEqual({ color: t.color.accent, tag: `${t.brand.icon} ${t.brand.tool}` })
    expect(composerFrameStyle('shell', t)).toEqual({ color: t.color.shellDollar, tag: '$ SHELL' })
    expect(composerFrameStyle('rec', t)).toEqual({ color: t.color.error, tag: '● REC' })
    expect(composerFrameStyle('stt', t)).toEqual({ color: t.color.warn, tag: '◉ STT' })
    expect(composerFrameStyle('edit', t)).toEqual({ color: t.color.primary, tag: '✎ EDIT' })
  })
})
