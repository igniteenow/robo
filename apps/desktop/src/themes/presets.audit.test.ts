/**
 * Built-in theme audit. Copyright (c) 2026 Ignitee Now.
 *
 * Every built-in theme, in both modes, must be complete, readable and
 * self-contained. Floors follow WCAG 2.2: 4.5:1 for text (7:1 for primary
 * reading text, and for everything in the Contrast theme), 3:1 for focus
 * indicators and other essential non-text marks.
 */
import { describe, expect, it } from 'vitest'

import { BUILTIN_THEME_LIST, BUILTIN_THEMES, canonicalSkinName, DEFAULT_SKIN_NAME, RENAMED_SKINS } from './presets'
import type { DesktopTerminalPalette, DesktopThemeColors } from './types'

const HEX = /^#[0-9A-F]{6}$/i

const REQUIRED: (keyof DesktopThemeColors)[] = [
  'background',
  'foreground',
  'card',
  'cardForeground',
  'muted',
  'mutedForeground',
  'popover',
  'popoverForeground',
  'primary',
  'primaryForeground',
  'secondary',
  'secondaryForeground',
  'accent',
  'accentForeground',
  'border',
  'input',
  'ring',
  'midground',
  'composerRing',
  'destructive',
  'destructiveForeground',
  'sidebarBackground',
  'sidebarBorder',
  'userBubble',
  'userBubbleBorder'
]

const channel = (v: number) => {
  const c = v / 255

  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

const luminance = (hex: string) => {
  const n = parseInt(hex.slice(1), 16)

  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255)
}

const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)

  return (hi + 0.05) / (lo + 0.05)
}

interface Case {
  id: string
  theme: string
  mode: 'dark' | 'light'
  colors: DesktopThemeColors
  terminal?: DesktopTerminalPalette
}

const CASES: Case[] = BUILTIN_THEME_LIST.flatMap(t => [
  { id: `${t.name}:light`, theme: t.name, mode: 'light' as const, colors: t.colors, terminal: t.terminal },
  {
    id: `${t.name}:dark`,
    theme: t.name,
    mode: 'dark' as const,
    colors: t.darkColors ?? t.colors,
    terminal: t.darkTerminal ?? t.terminal
  }
])

describe('built-in theme set', () => {
  it('is exactly the four Ignitee Now themes', () => {
    expect(Object.keys(BUILTIN_THEMES)).toEqual(['igniteenow', 'ember', 'midnight', 'contrast'])
    expect(BUILTIN_THEMES[DEFAULT_SKIN_NAME]).toBeDefined()
  })

  it('keys each theme by its own name, with unique labels', () => {
    for (const [key, theme] of Object.entries(BUILTIN_THEMES)) {
      expect(theme.name).toBe(key)
      expect(theme.description.length).toBeGreaterThan(0)
    }

    expect(new Set(BUILTIN_THEME_LIST.map(t => t.label)).size).toBe(BUILTIN_THEME_LIST.length)
  })

  it('ships a hand-tuned palette for both modes', () => {
    for (const theme of BUILTIN_THEME_LIST) {
      expect(theme.darkColors, theme.name).toBeDefined()
      expect(theme.darkTerminal, theme.name).toBeDefined()
      expect(theme.terminal, theme.name).toBeDefined()
    }
  })

  it('never fetches anything at runtime', () => {
    for (const theme of BUILTIN_THEME_LIST) {
      expect(theme.typography?.fontUrl, theme.name).toBeUndefined()
      expect(JSON.stringify(theme)).not.toMatch(/https?:\/\//)
    }
  })
})

describe.each(CASES)('$id', ({ colors, mode, terminal, theme }) => {
  const strict = theme === 'contrast' ? 7 : 4.5
  const c = colors as Required<DesktopThemeColors>

  it('defines every token as a 6-digit hex', () => {
    for (const key of REQUIRED) {
      expect(c[key], key).toMatch(HEX)
    }
  })

  it('has the right polarity', () => {
    const lum = luminance(c.background)

    if (mode === 'light') {
      expect(lum).toBeGreaterThan(0.6)
    } else {
      expect(lum).toBeLessThan(0.1)
    }
  })

  it('keeps reading text at 7:1 on every surface', () => {
    for (const surface of [c.background, c.card, c.popover, c.sidebarBackground]) {
      expect(contrast(c.foreground, surface), surface).toBeGreaterThanOrEqual(7)
    }

    expect(contrast(c.foreground, c.muted)).toBeGreaterThanOrEqual(strict)
    expect(contrast(c.cardForeground, c.card)).toBeGreaterThanOrEqual(7)
    expect(contrast(c.popoverForeground, c.popover)).toBeGreaterThanOrEqual(7)
    expect(contrast(c.secondaryForeground, c.secondary)).toBeGreaterThanOrEqual(strict)
  })

  it('keeps secondary text readable on every surface', () => {
    for (const surface of [c.background, c.card, c.muted, c.sidebarBackground]) {
      expect(contrast(c.mutedForeground, surface), surface).toBeGreaterThanOrEqual(strict)
    }
  })

  it('keeps button and accent text readable', () => {
    expect(contrast(c.primaryForeground, c.primary)).toBeGreaterThanOrEqual(strict)
    expect(contrast(c.destructiveForeground, c.destructive)).toBeGreaterThanOrEqual(strict)
    expect(contrast(c.accentForeground, c.accent)).toBeGreaterThanOrEqual(strict)
    expect(contrast(c.accentForeground, c.background)).toBeGreaterThanOrEqual(strict)
  })

  it('keeps focus indicators and controls visible (3:1)', () => {
    for (const mark of [c.ring, c.midground, c.composerRing, c.primary, c.destructive]) {
      expect(contrast(mark, c.background), mark).toBeGreaterThanOrEqual(3)
    }

    expect(contrast(c.ring, c.card)).toBeGreaterThanOrEqual(3)
    expect(contrast(c.composerRing, c.input)).toBeGreaterThanOrEqual(3)
  })

  it('keeps hairlines and the chat bubble distinguishable', () => {
    expect(contrast(c.border, c.background)).toBeGreaterThanOrEqual(1.2)
    expect(contrast(c.userBubbleBorder, c.userBubble)).toBeGreaterThanOrEqual(1.2)
  })

  it('has a readable terminal palette', () => {
    expect(terminal).toBeDefined()
    const t = terminal as Required<DesktopTerminalPalette>

    expect(contrast(t.foreground, c.background)).toBeGreaterThanOrEqual(7)
    expect(contrast(t.cursor, c.background)).toBeGreaterThanOrEqual(3)

    // `black` is conventionally the background-adjacent slot; everything else must show.
    const visible = [
      t.red,
      t.green,
      t.yellow,
      t.blue,
      t.magenta,
      t.cyan,
      t.white,
      t.brightBlack,
      t.brightRed,
      t.brightGreen,
      t.brightYellow,
      t.brightBlue,
      t.brightMagenta,
      t.brightCyan,
      t.brightWhite
    ]

    for (const ansi of visible) {
      expect(ansi).toMatch(HEX)
      expect(contrast(ansi, c.background), ansi).toBeGreaterThanOrEqual(3)
    }
  })
})

describe('retired and terminal skin names', () => {
  it('always migrate to a theme that exists', () => {
    for (const [from, to] of Object.entries(RENAMED_SKINS)) {
      expect(BUILTIN_THEMES[to], `${from} -> ${to}`).toBeDefined()
      expect(BUILTIN_THEMES[from], `${from} must not also be a live theme`).toBeUndefined()
    }
  })

  it('cover every terminal skin, so /skin means the same thing everywhere', () => {
    // robo_cli/skin_engine.py built-ins
    for (const cliSkin of ['robo', 'ember', 'midnight', 'paper', 'contrast']) {
      expect(BUILTIN_THEMES[canonicalSkinName(cliSkin) as string], cliSkin).toBeDefined()
    }
  })

  it('cover every theme removed in 3.0', () => {
    expect(canonicalSkinName('mono')).toBe('contrast')
    expect(canonicalSkinName('cyberpunk')).toBe('contrast')
    expect(canonicalSkinName('slate')).toBe('midnight')
    expect(canonicalSkinName('ares')).toBe('ember')
  })

  it('normalise case and whitespace, and pass unknown names through', () => {
    expect(canonicalSkinName('  MONO ')).toBe('contrast')
    expect(canonicalSkinName('my-own-theme')).toBe('my-own-theme')
    expect(canonicalSkinName('')).toBeNull()
    expect(canonicalSkinName(null)).toBeNull()
    expect(canonicalSkinName(undefined)).toBeNull()
  })
})
