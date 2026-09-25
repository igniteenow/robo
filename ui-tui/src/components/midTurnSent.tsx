import { Box, Text } from '@robo/ink'

import type { MidTurnSentItem, MidTurnSentStatus } from '../app/interfaces.js'
import { compactPreview } from '../lib/text.js'
import type { Theme } from '../theme.js'

// The label is the one place the user can see WHY a mid-turn message did or
// did not land at once — "delivered" hid the difference between a redirect
// Robo reads now and a steer he only reads after the current step.
export const MID_TURN_STATUS_LABEL: Record<MidTurnSentStatus, string> = {
  queued: 'queued for next turn',
  redirected: 'Robo is reading it now',
  sending: 'sending…',
  sent: 'delivered',
  steered: 'read after this step · /busy interrupt for at once'
}

export const midTurnSentHeading = (count: number) => `sent to the running turn (${count})`

// Messages sent while the current turn was already running. Their transcript
// bubbles land above the live reply block — out of view once that block is
// taller than the screen — so this strip, anchored to the composer like the
// queue panel, is where the user sees that Enter did something and what the
// gateway did with the text. Cleared when the turn ends.
export function MidTurnSent({ cols, items, t }: MidTurnSentProps) {
  if (!items.length) {
    return null
  }

  return (
    <Box flexDirection="column" marginTop={1}>
      <Text color={t.color.muted} dimColor>
        {midTurnSentHeading(items.length)}
      </Text>

      {items.map(item => {
        const label = MID_TURN_STATUS_LABEL[item.status]
        const pending = item.status === 'sending'

        return (
          <Text key={item.id} wrap="truncate-end">
            <Text color={pending ? t.color.muted : t.color.ok}>{pending ? ' …' : ' ✓'}</Text>

            <Text color={t.color.text}> {compactPreview(item.text, Math.max(16, cols - label.length - 8))}</Text>

            <Text color={t.color.muted} dimColor>
              {` · ${label}`}
            </Text>
          </Text>
        )
      })}
    </Box>
  )
}

interface MidTurnSentProps {
  cols: number
  items: MidTurnSentItem[]
  t: Theme
}
