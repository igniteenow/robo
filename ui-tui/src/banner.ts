import type { ThemeColors } from './theme.js'

const RICH_RE = /\[(?:bold\s+)?(?:dim\s+)?(#(?:[0-9a-fA-F]{3,8}))\]([\s\S]*?)(\[\/\])/g

export function parseRichMarkup(markup: string): Line[] {
  const lines: Line[] = []

  for (const raw of markup.split('\n')) {
    const trimmed = raw.trimEnd()

    if (!trimmed) {
      lines.push(['', ' '])

      continue
    }

    const matches = [...trimmed.matchAll(RICH_RE)]

    if (!matches.length) {
      lines.push(['', trimmed])

      continue
    }

    let cursor = 0

    for (const match of matches) {
      const before = trimmed.slice(cursor, match.index)

      if (before) {
        lines.push(['', before])
      }

      lines.push([match[1]!, match[2]!])
      cursor = match.index! + match[0].length
    }

    if (cursor < trimmed.length) {
      lines.push(['', trimmed.slice(cursor)])
    }
  }

  return lines
}

// Robo's wordmark is intentionally compact enough for an ordinary terminal.
// It is not derived from the upstream banner and remains legible without a
// patched font or true-colour support.
const LOGO_ART = [
  '██████╗  ██████╗ ██████╗  ██████╗ ',
  '██╔══██╗██╔═══██╗██╔══██╗██╔═══██╗',
  '██████╔╝██║   ██║██████╔╝██║   ██║',
  '██╔══██╗██║   ██║██╔══██╗██║   ██║',
  '██║  ██║╚██████╔╝██████╔╝╚██████╔╝',
  '╚═╝  ╚═╝ ╚═════╝ ╚═════╝  ╚═════╝ '
]

// Robo mark: a compact, single-width box-drawing robot that stays aligned in
// any monospace terminal (no ambiguous-width glyphs). Antenna and neck share
// one spine column; ear and shoulder joints sit on the head/plate edges.
const ROBOT_FACE_ART = [
  '             ╭─╮             ',
  '             ╰┬╯             ',
  '       ╭──────┴──────╮       ',
  '       │  ╭──╮ ╭──╮  │       ',
  '  ╭────┤  │o │ │o │  ├────╮  ',
  '  │    │  ╰──╯ ╰──╯  │    │  ',
  '  ╰────┤   ╰─────╯   ├────╯  ',
  '       ╰──────┬──────╯       ',
  '          ╭───┴───╮          ',
  '     ╭────┴───────┴────╮     ',
  '     ╰─────────────────╯     ',
]

const LOGO_GRADIENT = [0, 0, 1, 1, 2, 2] as const
const ROBOT_FACE_GRADIENT = ['accent', 'accent', 'primary', 'primary', 'primary', 'primary', 'primary', 'primary', 'border', 'muted', 'muted'] as const

const colorizeLogo = (art: string[], gradient: readonly number[], colors: ThemeColors): Line[] => {
  const palette = [colors.primary, colors.accent, colors.border, colors.muted]

  return art.map((text, index) => [palette[gradient[index]!] ?? colors.muted, text])
}

const colorizeRobotFace = (colors: ThemeColors): Line[] =>
  ROBOT_FACE_ART.map((text, index) => [colors[ROBOT_FACE_GRADIENT[index]!] ?? colors.muted, text])

export const LOGO_WIDTH = Math.max(...LOGO_ART.map(line => line.length))
export const ROBOT_FACE_WIDTH = Math.max(...ROBOT_FACE_ART.map(line => line.length))

export const logo = (colors: ThemeColors, customLogo?: string): Line[] =>
  customLogo ? parseRichMarkup(customLogo) : colorizeLogo(LOGO_ART, LOGO_GRADIENT, colors)

export const robotFace = (colors: ThemeColors, customHero?: string): Line[] =>
  customHero ? parseRichMarkup(customHero) : colorizeRobotFace(colors)

export const artWidth = (lines: Line[]) => lines.reduce((max, [, text]) => Math.max(max, text.length), 0)

type Line = [string, string]
