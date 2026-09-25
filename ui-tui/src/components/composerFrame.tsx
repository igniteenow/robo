// The chat box frame: a rounded box on all four sides around the composer.
//
//   ╭─ ◆ ROBO ────────────────────── ↑ history · Ctrl+B voice · /help ─╮
//   │ ▍ready  ·  model  ·  39.2k/1m  ·  [███░░░░░░░] 4%  ·  idle 1s     │
//   │ › type here…                                                     ♥ │
//   ╰──────────────────────────────────────────────────────── voice off ─╯
//
// The top and bottom edges are drawn as text so they can carry a tag, a hint
// and a label at exact columns; the sides come from an Ink Box with only its
// left/right borders on, so multi-line input grows the box without any row
// bookkeeping here. The tag and the frame colour follow the composer's mode:
// chat (brand ember), shell (`!` prefix), REC / STT (voice capture), EDIT
// (/edit: the last message is back in the composer, waiting to be resent).
import { stringWidth, Text } from '@robo/ink'

import type { Theme } from '../theme.js'

/** Columns the frame takes on EACH side of the input: border + inner padding. */
export const COMPOSER_FRAME_INSET = 2

/** Below this many columns the frame's chrome costs more than it gives. */
export const COMPOSER_FRAME_MIN_COLS = 40

const TOP_LEFT = '╭─ '
const TOP_RIGHT = '─╮'
// Frameless (narrow / Termux) variant: the same line without corners, so the
// tag still heads the composer while the sides and bottom edge stay off.
const OPEN_LEFT = '── '
const OPEN_RIGHT = '──'
const BOTTOM_LEFT = '╰'
const BOTTOM_RIGHT = '╯'
const RULE = '─'

export type ComposerMode = 'chat' | 'edit' | 'rec' | 'shell' | 'stt'

/** Which mode the composer is in, from the shell prefix, the voice label the
 * status bar already derives (`● REC` / `◉ STT` / `voice on|off`) and the
 * /edit state. Voice capture outranks everything; an edit outranks the
 * shell prefix (the recalled text is being edited, not executed). */
export function composerMode(shellMode: boolean, voiceLabel: string, editing = false): ComposerMode {
  if (voiceLabel.startsWith('●')) {
    return 'rec'
  }

  if (voiceLabel.startsWith('◉')) {
    return 'stt'
  }

  if (editing) {
    return 'edit'
  }

  return shellMode ? 'shell' : 'chat'
}

export function composerFrameStyle(mode: ComposerMode, t: Theme): { color: string; tag: string } {
  switch (mode) {
    case 'rec':
      return { color: t.color.error, tag: '● REC' }

    case 'stt':
      return { color: t.color.warn, tag: '◉ STT' }

    case 'shell':
      return { color: t.color.shellDollar, tag: '$ SHELL' }

    case 'edit':
      return { color: t.color.primary, tag: '✎ EDIT' }

    default:
      return { color: t.color.accent, tag: `${t.brand.icon} ${t.brand.tool}` }
  }
}

/** What typing does while Robo works, by `display.busy_input_mode`. Only
 * interrupt/redirect read the message now; the others say so honestly. */
export function busyComposerHint(mode: string): string {
  switch (mode) {
    case 'queue':
      return 'type to queue for the next turn · Ctrl+C stop · /edit last message'

    case 'steer':
      return 'type to steer (read after this step; /busy interrupt for now) · Ctrl+C stop'

    default:
      return 'type to redirect Robo · Ctrl+C stop · /edit last message'
  }
}

export interface FrameTopLayout {
  /** `─` cells between the tag and the hint (or the right corner). */
  fill: number
  /** The hint as rendered, '' when it did not fit. */
  hint: string
  /** The tag as rendered, '' when even the tag did not fit. */
  tag: string
}

/** Lay out `╭─ TAG ───…─── HINT ─╮` in exactly `width` cells. The hint goes
 * first when the line is tight, then the tag; the corners always survive. */
export function frameTopLayout(width: number, tag: string, hint: string): FrameTopLayout {
  const w = Math.max(2, Math.floor(width))
  const fixed = stringWidth(TOP_LEFT) + 1 + stringWidth(TOP_RIGHT) // '╭─ ' + ' ' after the tag + '─╮'
  const tagW = stringWidth(tag)
  const hintW = hint ? stringWidth(hint) + 2 : 0 // ' hint ' — a space either side

  if (tag && w - fixed - tagW - hintW >= 2 && hint) {
    return { fill: w - fixed - tagW - hintW, hint, tag }
  }

  if (tag && w - fixed - tagW >= 1) {
    return { fill: w - fixed - tagW, hint: '', tag }
  }

  return { fill: w - 2, hint: '', tag: '' }
}

export interface FrameBottomLayout {
  fill: number
  label: string
}

/** Lay out `╰───…─── LABEL ─╯` in exactly `width` cells; the label is dropped
 * before the line ever shrinks below two rule cells. */
export function frameBottomLayout(width: number, label: string): FrameBottomLayout {
  const w = Math.max(2, Math.floor(width))
  const labelW = label ? stringWidth(label) + 3 : 0 // ' label ─'

  if (label && w - 2 - labelW >= 2) {
    return { fill: w - 2 - labelW, label }
  }

  return { fill: w - 2, label: '' }
}

/** The plain-text rendering of the top edge (tests, and the fallback when
 * colour is unavailable) — exactly `width` cells. */
export function frameTopText(width: number, tag: string, hint: string, open = false): string {
  const lay = frameTopLayout(width, tag, hint)
  const [left, right] = open ? [OPEN_LEFT, OPEN_RIGHT] : [TOP_LEFT, TOP_RIGHT]

  if (!lay.tag) {
    return open ? RULE.repeat(lay.fill + 2) : `╭${RULE.repeat(lay.fill)}╮`
  }

  return `${left}${lay.tag} ${RULE.repeat(lay.fill)}${lay.hint ? ` ${lay.hint} ` : ''}${right}`
}

export function frameBottomText(width: number, label: string): string {
  const lay = frameBottomLayout(width, label)

  return `${BOTTOM_LEFT}${RULE.repeat(lay.fill)}${lay.label ? ` ${lay.label} ${RULE}` : ''}${BOTTOM_RIGHT}`
}

export function ComposerFrameTop({
  color,
  hint,
  hintColor,
  open = false,
  tag,
  width
}: {
  color: string
  hint: string
  hintColor: string
  /** No corners: the frameless composer (narrow panes / Termux). */
  open?: boolean
  tag: string
  width: number
}) {
  const lay = frameTopLayout(width, tag, hint)
  const [left, right] = open ? [OPEN_LEFT, OPEN_RIGHT] : [TOP_LEFT, TOP_RIGHT]

  if (!lay.tag) {
    return (
      <Text color={color} wrap="truncate-end">
        {open ? RULE.repeat(lay.fill + 2) : `╭${RULE.repeat(lay.fill)}╮`}
      </Text>
    )
  }

  return (
    <Text color={color} wrap="truncate-end">
      {left}
      <Text bold>{lay.tag}</Text>
      {` ${RULE.repeat(lay.fill)}`}
      {lay.hint ? <Text color={hintColor}>{` ${lay.hint} `}</Text> : null}
      {right}
    </Text>
  )
}

export function ComposerFrameBottom({
  color,
  label,
  labelColor,
  width
}: {
  color: string
  label: string
  labelColor: string
  width: number
}) {
  const lay = frameBottomLayout(width, label)

  return (
    <Text color={color} wrap="truncate-end">
      {BOTTOM_LEFT}
      {RULE.repeat(lay.fill)}
      {lay.label ? (
        <>
          <Text color={labelColor}>{` ${lay.label} `}</Text>
          {RULE}
        </>
      ) : null}
      {BOTTOM_RIGHT}
    </Text>
  )
}
