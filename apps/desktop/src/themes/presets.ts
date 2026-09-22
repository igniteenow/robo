/**
 * Built-in desktop themes. Copyright (c) 2026 Ignitee Now.
 *
 * Four themes, each with a hand-tuned light and dark palette, all built from
 * the brand tokens in `assets/brand/BRAND.md`. Names line up with the terminal
 * skins in `robo_cli/skin_engine.py`, so `/skin ember` means the same thing in
 * the CLI and on the desktop.
 *
 * Every palette is expanded from a handful of seed colours by `palette()`, so a
 * theme cannot ship with a missing token, and every value is a plain 6-digit
 * hex, so `presets.audit.test.ts` can measure contrast for every pair that
 * carries text or a focus indicator. Add a theme by adding seeds; nothing else
 * needs to change.
 */
import type { DesktopTerminalPalette, DesktopTheme, DesktopThemeColors, DesktopThemeTypography } from './types'

// Colour-emoji fonts, appended to every stack. None of the UI faces carry emoji
// glyphs, and on platforms whose default font lacks them too (Linux) they would
// otherwise render as empty boxes.
export const EMOJI_FALLBACK = '"Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji", emoji'

const SYSTEM_SANS =
  '"Segoe WPC", "Segoe UI", -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", system-ui, sans-serif, ' +
  EMOJI_FALLBACK

const SYSTEM_MONO = '"JetBrains Mono", Menlo, Monaco, "SF Mono", Consolas, monospace, ' + EMOJI_FALLBACK

// Poppins (SIL OFL 1.1) is bundled in src/fonts and declared in styles.css, so
// the app never fetches a font at runtime.
export const BRAND_SANS = '"Poppins", ' + SYSTEM_SANS

export const DEFAULT_TYPOGRAPHY: DesktopThemeTypography = { fontSans: BRAND_SANS, fontMono: SYSTEM_MONO }

// Brand tokens, sampled from the Ignitee Now logo.
export const IGNITEENOW_INDIGO = '#3F3E98'
export const IGNITEENOW_INDIGO_LIGHT = '#8E8CE0'
export const IGNITEENOW_EMBER = '#EF8A22'
export const IGNITEENOW_FLAME = '#DF5A30'

interface Seeds {
  /** Window background and the text drawn on it. */
  bg: string
  fg: string
  /** Cards and inputs; popovers default to the same surface. */
  surface: string
  popover?: string
  /** Hover / selected fills, secondary buttons, the user's chat bubble. */
  raised: string
  /** Secondary text. Must stay readable on `bg`, `surface` and `raised`. */
  dim: string
  /** Hairlines. */
  line: string
  /** Primary buttons and the text on them. */
  primary: string
  onPrimary: string
  /** Accent text and the composer's focus outline. */
  accent: string
  /** Structural brand stroke: focus rings, streaming cursor, selection. */
  stroke: string
  danger: string
  onDanger: string
  sidebar: string
  bubbleLine: string
}

const palette = (s: Seeds): DesktopThemeColors => ({
  background: s.bg,
  foreground: s.fg,
  card: s.surface,
  cardForeground: s.fg,
  muted: s.raised,
  mutedForeground: s.dim,
  popover: s.popover ?? s.surface,
  popoverForeground: s.fg,
  primary: s.primary,
  primaryForeground: s.onPrimary,
  secondary: s.raised,
  secondaryForeground: s.fg,
  accent: s.raised,
  accentForeground: s.accent,
  border: s.line,
  input: s.surface,
  ring: s.stroke,
  midground: s.stroke,
  composerRing: s.accent,
  destructive: s.danger,
  destructiveForeground: s.onDanger,
  sidebarBackground: s.sidebar,
  sidebarBorder: s.line,
  userBubble: s.raised,
  userBubbleBorder: s.bubbleLine
})

/** ANSI colours for the integrated terminal, in the order xterm names them. */
const terminal = (
  fg: string,
  cursor: string,
  selection: string,
  normal: [string, string, string, string, string, string, string, string],
  bright: [string, string, string, string, string, string, string, string]
): DesktopTerminalPalette => ({
  foreground: fg,
  cursor,
  selectionBackground: selection,
  black: normal[0],
  red: normal[1],
  green: normal[2],
  yellow: normal[3],
  blue: normal[4],
  magenta: normal[5],
  cyan: normal[6],
  white: normal[7],
  brightBlack: bright[0],
  brightRed: bright[1],
  brightGreen: bright[2],
  brightYellow: bright[3],
  brightBlue: bright[4],
  brightMagenta: bright[5],
  brightCyan: bright[6],
  brightWhite: bright[7]
})

const typography = { fontSans: BRAND_SANS, fontMono: SYSTEM_MONO }

/** Ignitee — the brand. Navy, the logo's indigo for structure, ember to act. */
export const igniteenowTheme: DesktopTheme = {
  name: 'igniteenow',
  label: 'Ignitee',
  description: 'Navy and indigo with an ember accent',
  colors: palette({
    bg: '#FFF8F1',
    fg: '#0A1030',
    surface: '#FFFFFF',
    raised: '#F6EADD',
    dim: '#5C6088',
    line: '#E3D5C5',
    primary: '#B5470F',
    onPrimary: '#FFFFFF',
    accent: '#B5470F',
    stroke: '#3F3E98',
    danger: '#B42332',
    onDanger: '#FFFFFF',
    sidebar: '#FBF0E4',
    bubbleLine: '#E2CDB5'
  }),
  darkColors: palette({
    bg: '#0A1030',
    fg: '#FFEFE0',
    surface: '#0E1437',
    popover: '#121945',
    raised: '#1E255C',
    dim: '#A9AECF',
    line: '#2A2F73',
    primary: '#EF8A22',
    onPrimary: '#0A1030',
    accent: '#EF8A22',
    stroke: '#8E8CE0',
    danger: '#D52734',
    onDanger: '#FFFFFF',
    sidebar: '#070B24',
    bubbleLine: '#3F3E98'
  }),
  typography,
  terminal: terminal(
    '#0A1030',
    '#B5470F',
    '#F6D9BC',
    ['#0A1030', '#B42332', '#1E7A46', '#8F5400', '#3F3E98', '#8A2F8F', '#0F6F80', '#5C6088'],
    ['#4B4F7A', '#D52734', '#2E8F58', '#B5470F', '#5856B8', '#A445A9', '#1B8A9E', '#23264A']
  ),
  darkTerminal: terminal(
    '#FFEFE0',
    '#EF8A22',
    '#2A2C73',
    ['#1E255C', '#F0626E', '#3FBF7F', '#F2B441', '#8E8CE0', '#D58CE0', '#5CC8D6', '#E6E3F5'],
    ['#7C82AD', '#FF8A93', '#6FD9A0', '#F5A13A', '#A3A1EC', '#E6A8EE', '#86DDE8', '#FFEFE0']
  )
}

/** Ember — warm charcoal with the full flame. */
export const emberTheme: DesktopTheme = {
  name: 'ember',
  label: 'Ember',
  description: 'Warm charcoal with the full flame',
  colors: palette({
    bg: '#FFF6EC',
    fg: '#2A1A10',
    surface: '#FFFFFF',
    raised: '#F8E7D6',
    dim: '#75604F',
    line: '#EBD3BC',
    primary: '#B93F0B',
    onPrimary: '#FFFFFF',
    accent: '#B93F0B',
    stroke: '#C2410C',
    danger: '#B42332',
    onDanger: '#FFFFFF',
    sidebar: '#FBEBDA',
    bubbleLine: '#E8C9A8'
  }),
  darkColors: palette({
    bg: '#1A120C',
    fg: '#F3E6DA',
    surface: '#24180F',
    popover: '#2B1B12',
    raised: '#38241A',
    dim: '#BBA99C',
    line: '#4A2C17',
    primary: '#F5A13A',
    onPrimary: '#1A120C',
    accent: '#F5A13A',
    stroke: '#E8742A',
    danger: '#C9342B',
    onDanger: '#FFFFFF',
    sidebar: '#140D08',
    bubbleLine: '#6B3D1D'
  }),
  typography,
  terminal: terminal(
    '#2A1A10',
    '#B93F0B',
    '#F6D9BC',
    ['#2A1A10', '#B42332', '#2F7A3A', '#8F5400', '#2F5FA8', '#8A2F6F', '#1F7373', '#75604F'],
    ['#5A4637', '#D52734', '#3F8F4A', '#B93F0B', '#3F73C2', '#A4458A', '#2B8A8A', '#3A271B']
  ),
  darkTerminal: terminal(
    '#F3E6DA',
    '#F5A13A',
    '#5A3318',
    ['#38241A', '#FF7A70', '#8CCB7A', '#F2C14E', '#7FB0E8', '#E09AC4', '#6FCFC4', '#F3E6DA'],
    ['#9A8677', '#FF9C94', '#A8DD98', '#F5A13A', '#9CC4F0', '#ECB4D6', '#90DED5', '#FFF3E8']
  )
}

/** Midnight — calm, indigo-forward, lower saturation. For long sessions. */
export const midnightTheme: DesktopTheme = {
  name: 'midnight',
  label: 'Midnight',
  description: 'Calm indigo for long sessions',
  colors: palette({
    bg: '#F6F6FE',
    fg: '#14183A',
    surface: '#FFFFFF',
    raised: '#ECECFA',
    dim: '#5A5F8A',
    line: '#D9D9F0',
    primary: '#3F3E98',
    onPrimary: '#FFFFFF',
    accent: '#3F3E98',
    stroke: '#5856B8',
    danger: '#B42332',
    onDanger: '#FFFFFF',
    sidebar: '#EFEFFB',
    bubbleLine: '#C9C8EC'
  }),
  darkColors: palette({
    bg: '#0B0E24',
    fg: '#E4E6FA',
    surface: '#14183A',
    popover: '#181C44',
    raised: '#1F2452',
    dim: '#9CA1CC',
    line: '#2C3170',
    primary: '#8E8CE0',
    onPrimary: '#0B0E24',
    accent: '#A5A3F5',
    stroke: '#8E8CE0',
    danger: '#C93A50',
    onDanger: '#FFFFFF',
    sidebar: '#080A1C',
    bubbleLine: '#3F3E98'
  }),
  typography,
  terminal: terminal(
    '#14183A',
    '#3F3E98',
    '#DADAF5',
    ['#14183A', '#B42332', '#1E7A46', '#8F5400', '#3F3E98', '#7A3FA0', '#0F6F80', '#5A5F8A'],
    ['#474C78', '#D52734', '#2E8F58', '#A86500', '#5856B8', '#9455BA', '#1B8A9E', '#23264A']
  ),
  darkTerminal: terminal(
    '#E4E6FA',
    '#A5A3F5',
    '#2F3478',
    ['#1F2452', '#FF7A8A', '#5FD0A0', '#F2C14E', '#8E8CE0', '#C99CF0', '#6FCFE0', '#DEE1F7'],
    ['#7A80B0', '#FF9CA8', '#86E0B8', '#F6D27A', '#A5A3F5', '#DCB8F6', '#94DDEA', '#F2F3FF']
  )
}

/** Contrast — accessibility first. Maximum legibility in both modes. */
export const contrastTheme: DesktopTheme = {
  name: 'contrast',
  label: 'Contrast',
  description: 'Maximum legibility, light or dark',
  colors: palette({
    bg: '#FFFFFF',
    fg: '#000000',
    surface: '#FFFFFF',
    raised: '#EDEDED',
    dim: '#2B2B2B',
    line: '#4A4A4A',
    primary: '#0B3D91',
    onPrimary: '#FFFFFF',
    accent: '#0B3D91',
    stroke: '#0B3D91',
    danger: '#9B1C1C',
    onDanger: '#FFFFFF',
    sidebar: '#F5F5F5',
    bubbleLine: '#000000'
  }),
  darkColors: palette({
    bg: '#000000',
    fg: '#FFFFFF',
    surface: '#0F0F0F',
    popover: '#141414',
    raised: '#1C1C1C',
    dim: '#D0D0D0',
    line: '#8A8A8A',
    primary: '#FFD23F',
    onPrimary: '#000000',
    accent: '#FFD23F',
    stroke: '#7FDBFF',
    danger: '#FF8A8A',
    onDanger: '#000000',
    sidebar: '#000000',
    bubbleLine: '#FFFFFF'
  }),
  typography,
  terminal: terminal(
    '#000000',
    '#0B3D91',
    '#C9DAF8',
    ['#000000', '#9B1C1C', '#0F5E2C', '#6B4A00', '#0B3D91', '#6A1B7A', '#005F6B', '#2B2B2B'],
    ['#3A3A3A', '#B42332', '#1E7A46', '#8F5400', '#1F56B8', '#8A2F9C', '#0F7A88', '#000000']
  ),
  darkTerminal: terminal(
    '#FFFFFF',
    '#FFD23F',
    '#404040',
    ['#1C1C1C', '#FF8A8A', '#5CFF8F', '#FFD23F', '#7FDBFF', '#F0A8FF', '#7FF0E8', '#FFFFFF'],
    ['#B0B0B0', '#FFB0B0', '#90FFB4', '#FFE27A', '#A8E8FF', '#F6C8FF', '#A8F6F0', '#FFFFFF']
  )
}

export const BUILTIN_THEMES: Record<string, DesktopTheme> = {
  igniteenow: igniteenowTheme,
  ember: emberTheme,
  midnight: midnightTheme,
  contrast: contrastTheme
}

export const BUILTIN_THEME_LIST = Object.values(BUILTIN_THEMES)

export const DEFAULT_SKIN_NAME = 'igniteenow'

/**
 * Names that no longer exist, and the theme each one should become. Covers the
 * terminal skin names (so `/skin robo` works on the desktop) and themes removed
 * in 3.0. A saved preference for one of these migrates instead of silently
 * resetting to the default.
 */
export const RENAMED_SKINS: Record<string, string> = {
  robo: 'igniteenow',
  default: 'igniteenow',
  gold: 'igniteenow',
  paper: 'igniteenow',
  'igniteenow-light': 'igniteenow',
  ares: 'ember',
  slate: 'midnight',
  mono: 'contrast',
  cyberpunk: 'contrast'
}

/** Resolve a possibly-retired name to a current built-in theme name. */
export const canonicalSkinName = (name: string | null | undefined): string | null => {
  const key = (name ?? '').trim()

  if (!key) {
    return null
  }

  return RENAMED_SKINS[key.toLowerCase()] ?? key
}
