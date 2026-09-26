/**
 * Mirror of "which chats are mid-turn" (and whether a voice chat is live) to
 * the main process.
 *
 * The renderer is the only side that knows a turn is in flight, and the main
 * process is the only side that can intercept a quit. This module bridges the
 * two: it publishes a small summary on every membership change, and
 * `electron/quit-guard.ts` turns that into the confirmation dialog.
 *
 * Imported for its side effect from `main.tsx`, alongside `store/translucency`.
 */

import { computed } from 'nanostores'

import type { RoboActiveWork } from '@/global'
import { $sessions } from '@/store/session'
import { $workingSessionIds } from '@/store/session-states'
import { $voiceConversation } from '@/store/voice-conversation'

// Only the on/off edge matters here; the view itself republishes with every
// mic level change.
const $voiceChatLive = computed($voiceConversation, view => view.active)

const $activeWork = computed(
  [$workingSessionIds, $sessions, $voiceChatLive],
  (workingIds, sessions, voiceChatLive): RoboActiveWork => {
    const titleById = new Map(sessions.map(session => [session.id, session.title?.trim() ?? '']))

    return {
      count: workingIds.length,
      titles: workingIds.map(id => titleById.get(id) ?? '').filter(Boolean),
      // A live voice chat keeps its window unthrottled so the mic loop keeps
      // running while the window is minimized or covered. Never prompts on
      // quit (quit-guard counts turns only).
      ...(voiceChatLive && { voice: true as const })
    }
  }
)

if (typeof window !== 'undefined') {
  // `$sessions` republishes on unrelated churn (previews, heartbeats), so only
  // send when the summary itself moved — this crosses a process boundary.
  let lastSent = ''

  $activeWork.subscribe(work => {
    const next = JSON.stringify(work)

    if (next === lastSent) {
      return
    }

    lastSent = next
    window.roboDesktop?.setActiveWork?.(work)
  })
}
