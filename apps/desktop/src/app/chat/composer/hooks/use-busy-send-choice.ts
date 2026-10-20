import { type RefObject, useCallback, useEffect, useRef, useState } from 'react'

interface UseBusySendChoiceArgs {
  activeQueueSessionKey: string | null
  busy: boolean
  draftRef: RefObject<string>
  hasText: boolean
}

/**
 * The "Robo is still working" choice. Enter on a text draft while a turn runs
 * no longer fires anything by itself — it opens this choice above the composer:
 * **Send now** (stop the current step and read this first) or **Queue** (after
 * Robo finishes), Esc to keep editing. The words stay in the composer until the
 * person picks, so nothing is sent, redirected or parked without them seeing
 * it — the old Enter redirected the live turn, and when the turn had no model
 * request to redirect the words landed in the queue with nothing on screen to
 * say so. It closes itself when the draft is emptied, when the composer moves
 * to another session, and when the turn ends (the words stay in the composer;
 * Enter then sends them the ordinary way).
 */
export function useBusySendChoice({ activeQueueSessionKey, busy, draftRef, hasText }: UseBusySendChoiceArgs) {
  const [open, setOpen] = useState(false)
  const openRef = useRef(false)

  const show = useCallback(() => {
    openRef.current = true
    setOpen(true)
  }, [])

  const hide = useCallback(() => {
    openRef.current = false
    setOpen(false)
  }, [])

  // The draft was emptied (sent, queued, deleted), the turn ended, or the
  // composer moved to another session → nothing left to decide. `hasText` is
  // the composer state, which lags the editor by a render; the ref holds the
  // live words, so a choice opened on a fast Enter is not closed by the lag.
  useEffect(() => {
    if (!busy || (!hasText && !draftRef.current.trim())) {
      hide()
    }
  }, [busy, draftRef, hasText, hide])

  useEffect(() => {
    hide()
  }, [activeQueueSessionKey, hide])

  return { hide, open, openRef, show }
}
