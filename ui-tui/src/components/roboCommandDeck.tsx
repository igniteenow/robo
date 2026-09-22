import { Box, Text } from '@robo/ink'

import type { Theme } from '../theme.js'

const clip = (value: string, width: number) => {
  const clean = value.replace(/\s+/g, ' ').trim()

  return clean.length <= width ? clean : `${clean.slice(0, Math.max(0, width - 1))}…`
}

export type RoboExpression = 'approval' | 'error' | 'happy' | 'idle' | 'working'

export function expressionForStatus(status: string, busy: boolean): RoboExpression {
  const value = status.toLowerCase()

  if (/approv|permission|confirm|waiting for you|needs input/.test(value)) {return 'approval'}

  if (/error|failed|failure|blocked|denied|unavailable/.test(value)) {return 'error'}

  if (/success|complete|completed|done|ready/.test(value)) {return 'happy'}

  if (busy || /think|work|run|execut|scan|search|build|install|deploy|connect/.test(value)) {return 'working'}

  return 'idle'
}

// A single color-coded dot carries the state signal instead of a kaomoji
// face — one small accent against an otherwise monochrome header, matching
// the same "mostly muted text, one deliberate spot of color" rule the rest
// of the minimal redesign follows.
const DOT_TONE: Record<RoboExpression, (t: Theme) => string> = {
  approval: t => t.color.warn,
  error: t => t.color.error,
  happy: t => t.color.ok,
  idle: t => t.color.muted,
  working: t => t.color.accent
}

const phaseLabel = (status: string, busy: boolean) => {
  const cleaned = status.replace(/[.…]+$/g, '').trim()

  if (cleaned) {return cleaned.toUpperCase()}

  return busy ? 'WORKING' : 'READY'
}

export function RoboCommandDeck({
  busy,
  cols,
  cwdLabel,
  model,
  profile,
  sessionId,
  sessionTitle,
  status,
  statusColor: _statusColor,
  t
}: RoboCommandDeckProps) {
  const wide = cols >= 78
  const medium = cols >= 54
  const expression = expressionForStatus(status, busy)
  const dotColor = DOT_TONE[expression](t)
  const phase = clip(phaseLabel(status, busy), wide ? 28 : 16)
  const title = clip(sessionTitle || 'New engineering mission', wide ? 34 : 22)
  const modelName = clip(model || 'model connecting', 26)
  const profileName = clip(profile || 'default', 14)
  const session = sessionId ? sessionId.slice(0, 8) : 'new'

  return (
    <Box flexDirection="column" flexShrink={0} paddingTop={1} paddingX={1}>
      <Box>
        <Text bold color={t.color.text}>{t.brand.name}</Text>
        {medium ? <Text color={t.color.muted}>  {title}</Text> : null}
        <Box flexGrow={1} />
        <Text color={dotColor}>●</Text>
        <Text color={t.color.muted}> {phase}</Text>
      </Box>

      {wide ? (
        <Text color={t.color.muted} wrap="truncate-end">
          {modelName}
          {'  ·  '}
          {profileName}
          {cwdLabel ? `  ·  ${cwdLabel}` : ''}
          {'  ·  #'}
          {session}
        </Text>
      ) : medium ? (
        <Text color={t.color.muted} wrap="truncate-end">
          {modelName}
        </Text>
      ) : null}

      <Text color={t.color.border}>{'─'.repeat(Math.max(4, Math.min(cols - 2, 80)))}</Text>
    </Box>
  )
}

interface RoboCommandDeckProps {
  busy: boolean
  cols: number
  cwdLabel: string
  model: string
  profile?: string
  sessionId: null | string
  sessionTitle: string
  status: string
  statusColor: string
  t: Theme
}
