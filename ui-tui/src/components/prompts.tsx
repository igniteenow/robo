import { Box, Text, useInput, wrapAnsi } from '@robo/ink'
import { useState } from 'react'

import { type ApprovalChoice, approvalOptions } from '../lib/approval.js'
import { isMac } from '../lib/platform.js'
import type { Theme } from '../theme.js'
import type { ApprovalReq, ClarifyReq, ConfirmReq } from '../types.js'

import { chipRowProps } from './overlayPrimitives.js'
import { TextInput } from './textInput.js'

export { approvalOptions } from '../lib/approval.js'

const LABELS = { deny: 'Deny', once: 'Allow once', session: 'Allow for this session' } as const

// A fact-check correction rides the same prompt with its own words (desktop
// parity: "Apply correction" / "Keep answer").
const CORRECTION_LABELS = {
  deny: 'Keep answer',
  once: 'Apply correction',
  session: 'Apply corrections this session'
} as const

const CMD_PREVIEW_LINES = 10
const PLUGIN_RULE_RE = /^<([\w.-]+)>\s*\(plugin approval rule\)$/

type ApprovalKey = {
  downArrow?: boolean
  escape?: boolean
  return?: boolean
  upArrow?: boolean
}

type ApprovalAction = { kind: 'choose'; choice: ApprovalChoice } | { kind: 'move'; delta: -1 | 1 } | { kind: 'noop' }

/**
 * Pure key-dispatch for the approval prompt — exported so the regression
 * matrix (Esc, Ctrl+C-equivalent, number keys, Enter, ↑↓) is testable
 * without mounting React + Ink + a fake stdin.  The component just maps the
 * action onto its own state setters.
 *
 * Esc and number keys both terminate the prompt; Esc maps to deny (parity
 * with the global Ctrl+C handler that already calls cancelOverlayFromCtrlC
 * for approvals).  Numbers 1..opts.length pick the labelled choice.  Enter
 * confirms the current selection.  ↑/↓ moves the selection within bounds.
 * Letters are deliberately NOT shortcuts: the prompt can appear while the
 * person is mid-sentence in the composer, and a stray "a" or "d" must not
 * decide anything.
 */
export function approvalAction(
  ch: string,
  key: ApprovalKey,
  sel: number,
  opts: readonly ApprovalChoice[] = ['once', 'session', 'deny']
): ApprovalAction {
  if (key.escape) {
    return { kind: 'choose', choice: 'deny' }
  }

  const n = parseInt(ch, 10)

  if (n >= 1 && n <= opts.length) {
    return { kind: 'choose', choice: opts[n - 1]! }
  }

  if (key.return) {
    return { kind: 'choose', choice: opts[sel]! }
  }

  if (key.upArrow && sel > 0) {
    return { kind: 'move', delta: -1 }
  }

  if (key.downArrow && sel < opts.length - 1) {
    return { kind: 'move', delta: 1 }
  }

  return { kind: 'noop' }
}

/**
 * The question the card asks, from the shape of the request. Pure and
 * exported for tests: a shell command, an execute_code script, a plugin rule
 * on a tool, or a fact-check correction each get their own words, and the
 * matching option labels.
 */
export function approvalHeading(req: ApprovalReq): { labels: typeof LABELS | typeof CORRECTION_LABELS; title: string } {
  if (req.kind === 'correction') {
    return { labels: CORRECTION_LABELS, title: "Apply Robo's correction to the answer?" }
  }

  const command = req.command.trim()

  if (command.startsWith('execute_code')) {
    return { labels: LABELS, title: 'Allow Robo to run this script?' }
  }

  const plugin = PLUGIN_RULE_RE.exec(command)

  if (plugin) {
    return { labels: LABELS, title: `Allow Robo to use ${plugin[1]}?` }
  }

  return { labels: LABELS, title: 'Allow Robo to run this command?' }
}

/**
 * The approval card. One question, the plain reason it was raised, the exact
 * command, then — when the gateway sends them — what Robo said it was doing
 * (`intent`), what to look at first (`check`) and what its reviewer concluded
 * (`review`). Options are numbered; the cursor row carries the shared
 * selection chip. Nothing here changes which choices exist or what they do.
 */
export function ApprovalPrompt({ cols = 80, onChoice, req, t }: ApprovalPromptProps) {
  const [sel, setSel] = useState(0)
  const opts = approvalOptions(req)
  const { labels, title } = approvalHeading(req)
  const correction = req.kind === 'correction'

  useInput((ch, key) => {
    const action = approvalAction(ch, key, sel, opts)

    if (action.kind === 'choose') {
      onChoice(action.choice)
    } else if (action.kind === 'move') {
      setSel(s => s + action.delta)
    }
  })

  // Wrap long single-line commands to the panel width instead of clipping the
  // tail (mirrors the CLI approval panel fix — the full command must be
  // reviewable before approving). Border + paddingX + inner indent ≈ 8 cols.
  const innerWidth = Math.max(20, cols - 8)

  const rawLines = req.command
    .split('\n')
    .flatMap(line => wrapAnsi(line, innerWidth, { hard: true, trim: false }).split('\n'))

  const shown = rawLines.slice(0, CMD_PREVIEW_LINES)
  const overflow = rawLines.length - shown.length

  // Context rows: a short label column, then the sentence wrapped to the rest.
  const facts: { label: string; text: string; tone: string }[] = []

  if (req.intent) {
    facts.push({ label: 'Robo', text: req.intent, tone: t.color.text })
  }

  if (req.review) {
    facts.push({ label: 'Review', text: req.review, tone: t.color.warn })
  }

  if (req.check && !correction) {
    facts.push({ label: 'Check', text: req.check, tone: t.color.muted })
  }

  const factLabelWidth = facts.reduce((w, f) => Math.max(w, f.label.length), 0) + 2
  const factTextWidth = Math.max(16, innerWidth - factLabelWidth)

  return (
    <Box borderColor={t.color.warn} borderStyle="round" flexDirection="column" paddingX={1}>
      <Text>
        <Text bold color={t.color.warn}>
          {'? '}
        </Text>
        <Text bold color={t.color.text}>
          {title}
        </Text>
      </Text>

      <Box flexDirection="column" paddingLeft={2}>
        {wrapAnsi(req.description, innerWidth, { hard: true, trim: true })
          .split('\n')
          .map((line, i) => (
            <Text color={t.color.muted} key={i} wrap="truncate-end">
              {line.trim() || ' '}
            </Text>
          ))}
      </Box>

      <Box flexDirection="column" marginTop={1} paddingLeft={2}>
        {shown.map((line, i) => (
          <Text color={t.color.text} key={i} wrap="truncate-end">
            {line || ' '}
          </Text>
        ))}

        {overflow > 0 ? (
          <Text color={t.color.muted}>
            … +{overflow} more line{overflow === 1 ? '' : 's'} (full text above)
          </Text>
        ) : null}
      </Box>

      {facts.length > 0 ? (
        <Box flexDirection="column" marginTop={1} paddingLeft={2}>
          {facts.map(fact => (
            <Box key={fact.label}>
              <Box flexShrink={0} width={factLabelWidth}>
                <Text color={t.color.label}>{fact.label}</Text>
              </Box>
              <Box flexDirection="column" width={factTextWidth}>
                {wrapAnsi(fact.text, factTextWidth, { hard: true, trim: true })
                  .split('\n')
                  .map((line, i) => (
                    <Text color={fact.tone} key={i} wrap="truncate-end">
                      {line.trim() || ' '}
                    </Text>
                  ))}
              </Box>
            </Box>
          ))}
        </Box>
      ) : null}

      <Box flexDirection="column" marginTop={1}>
        {opts.map((o, i) => (
          <Text key={o}>
            <Text color={t.color.muted} {...chipRowProps(t, sel === i)}>
              {sel === i ? '❯ ' : '  '}
              <Text color={sel === i ? undefined : t.color.muted}>{i + 1} </Text> {labels[o]}
            </Text>
          </Text>
        ))}
      </Box>

      <Box flexDirection="column" marginTop={1}>
        <Text color={t.color.muted}>
          ↑/↓ move · Enter choose · 1-{opts.length} pick · Esc {correction ? 'keep' : 'deny'}
        </Text>
        <Text color={t.color.muted}>
          Voice: {correction ? '"yes" to apply · "no" to keep' : '"allow once" · "allow for this session" · "deny"'} ·
          "wait"
        </Text>
      </Box>
    </Box>
  )
}

/** A printable, unmodified, non-digit key: the start of a typed answer.
 * Digits are the quick picks (or, out of range, nothing); modifier chords
 * (Ctrl+C cancel, Cmd+V paste) and key escapes never count. */
export function isTypedAnswerStart(ch: string, key: { ctrl: boolean; meta: boolean; super?: boolean }): boolean {
  if (key.ctrl || key.meta || key.super || ch.length !== 1) {
    return false
  }

  const code = ch.charCodeAt(0)

  return code >= 0x20 && code !== 0x7f && !(ch >= '0' && ch <= '9')
}

export function ClarifyPrompt({ cols = 80, onAnswer, onCancel, req, t }: ClarifyPromptProps) {
  const [sel, setSel] = useState(0)
  const [custom, setCustom] = useState('')
  const [typing, setTyping] = useState(false)
  const choices = req.choices ?? []

  const heading = (
    <Text bold>
      <Text color={t.color.accent}>ask</Text>
      <Text color={t.color.text}> {req.question}</Text>
    </Text>
  )

  useInput((ch, key) => {
    if (key.escape) {
      typing && choices.length ? setTyping(false) : onCancel()

      return
    }

    if (typing || !choices.length) {
      return
    }

    if (key.upArrow && sel > 0) {
      setSel(s => s - 1)
    }

    if (key.downArrow && sel < choices.length) {
      setSel(s => s + 1)
    }

    if (key.return) {
      sel === choices.length ? setTyping(true) : choices[sel] && onAnswer(choices[sel]!)
    }

    const n = parseInt(ch)

    if (n >= 1 && n <= choices.length) {
      onAnswer(choices[n - 1]!)

      return
    }

    // The composer is hidden while this prompt owns the keyboard, so a user
    // who just starts typing ("stop", "the first one but in Rust") means the
    // free-text answer: open it with the character they typed instead of
    // dropping their keystrokes and then letting Enter pick option 1.
    if (isTypedAnswerStart(ch, key)) {
      setCustom(ch)
      setTyping(true)
    }
  })

  if (typing || !choices.length) {
    return (
      <Box flexDirection="column">
        {heading}

        <Box>
          <Text color={t.color.label}>{'> '}</Text>
          <TextInput
            color={t.color.text}
            columns={Math.max(20, cols - 6)}
            onChange={setCustom}
            onSubmit={onAnswer}
            value={custom}
          />
        </Box>

        <Text color={t.color.muted}>
          Enter send · Esc {choices.length ? 'back' : 'cancel'} ·{' '}
          {isMac ? 'Cmd+C copy · Cmd+V paste · Ctrl+C cancel' : 'Ctrl+C cancel'}
        </Text>
      </Box>
    )
  }

  return (
    <Box flexDirection="column">
      {heading}

      {[...choices, 'Other (type your answer)'].map((c, i) => (
        <Text key={i}>
          <Text color={t.color.muted} {...chipRowProps(t, sel === i)}>
            {sel === i ? '▸ ' : '  '}
            {i + 1}. {c}
          </Text>
        </Text>
      ))}

      <Text color={t.color.muted}>↑/↓ select · Enter confirm · 1-{choices.length} quick pick · Esc/Ctrl+C cancel</Text>
    </Box>
  )
}

export function ConfirmPrompt({ onCancel, onConfirm, req, t }: ConfirmPromptProps) {
  const [sel, setSel] = useState(0)

  useInput((ch, key) => {
    const lower = ch.toLowerCase()

    if (key.escape || (key.ctrl && lower === 'c') || lower === 'n') {
      return onCancel()
    }

    if (lower === 'y') {
      return onConfirm()
    }

    if (key.upArrow) {
      setSel(0)
    }

    if (key.downArrow) {
      setSel(1)
    }

    if (key.return) {
      sel === 0 ? onCancel() : onConfirm()
    }
  })

  const accent = req.danger ? t.color.error : t.color.warn

  const rows = [
    { color: t.color.text, label: req.cancelLabel ?? 'No' },
    { color: req.danger ? t.color.error : t.color.text, label: req.confirmLabel ?? 'Yes' }
  ]

  return (
    <Box borderColor={accent} borderStyle="double" flexDirection="column" paddingX={1}>
      <Text bold color={accent}>
        {req.danger ? '⚠' : '?'} {req.title}
      </Text>

      {req.detail ? (
        <Box paddingLeft={1}>
          <Text color={t.color.text} wrap="truncate-end">
            {req.detail}
          </Text>
        </Box>
      ) : null}

      <Text />

      {rows.map((row, i) => (
        <Text key={row.label}>
          <Text color={sel === i ? accent : t.color.muted}>{sel === i ? '▸ ' : '  '}</Text>
          <Text color={sel === i ? row.color : t.color.muted}>{row.label}</Text>
        </Text>
      ))}

      <Text color={t.color.muted}>↑/↓ select · Enter confirm · Y/N quick · Esc cancel</Text>
    </Box>
  )
}

interface ApprovalPromptProps {
  cols?: number
  onChoice: (s: string) => void
  req: ApprovalReq
  t: Theme
}

interface ClarifyPromptProps {
  cols?: number
  onAnswer: (s: string) => void
  onCancel: () => void
  req: ClarifyReq
  t: Theme
}

interface ConfirmPromptProps {
  onCancel: () => void
  onConfirm: () => void
  req: ConfirmReq
  t: Theme
}
