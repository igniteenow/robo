import type { Theme } from '../theme.js'
import type { Msg, Role } from '../types.js'

/**
 * Robo's label: the chat box's tag and the header row that opens each of
 * Robo's replies in the transcript (`$Robo ─────`). `$<agent name>` when a
 * skin renames the agent. Whitespace is dropped and the name is clamped so a
 * long skin name can never eat the header.
 */
export const AGENT_LABEL_MAX = 16

const dollarLabel = (name: string): string => `$${name.replace(/\s+/g, '').slice(0, AGENT_LABEL_MAX - 1)}`

export function agentLabel(name: string | undefined): string {
  return dollarLabel(String(name ?? '').trim() || 'Robo')
}

/**
 * The person's label, from display.user_name: `$Ahmi` for "Ahmi", built the
 * same way as Robo's. '' when no name is set — their messages then keep the
 * plain prompt glyph and no header row.
 */
export const USER_NAME_MAX = 40

export function normalizeUserName(value: unknown): string {
  return String(value ?? '')
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
    .slice(0, USER_NAME_MAX)
}

export function userLabel(name: string | undefined): string {
  const clean = normalizeUserName(name)

  return clean ? dollarLabel(clean) : ''
}

export const ROLE: Record<Role, (t: Theme) => { body: string; glyph: string; prefix: string }> = {
  assistant: t => ({ body: t.color.text, glyph: agentLabel(t.brand.name), prefix: t.color.primary }),
  system: t => ({ body: '', glyph: '·', prefix: t.color.muted }),
  tool: t => ({ body: t.color.muted, glyph: '⚙', prefix: t.color.accent }),
  // The person's own words read at full text strength: `label` is a step
  // above muted and was washing sent messages out next to the reply.
  user: t => ({ body: t.color.text, glyph: t.brand.prompt, prefix: t.color.label })
}

// Robo's prose — not slash output, diffs, or an empty streaming placeholder —
// opens with the `$Robo ─────` header row. Every reply segment gets one, so
// whatever Robo says while it works is labelled the same way as its answer.
export const shouldShowReplyHeader = (msg: Msg): boolean =>
  msg.role === 'assistant' && msg.kind !== 'slash' && msg.kind !== 'diff' && /\S/.test(msg.text)
