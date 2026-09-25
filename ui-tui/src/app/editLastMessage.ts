// /edit — change your last message and let Robo start again from there.
//
// The gateway already has the rewind (`command.dispatch /undo`: soft-deletes
// the last exchange on disk, reloads the live history, and hands back the
// text of the message it backed up to, like an editor's undo). What the TUI adds:
// stop a running turn first, wait for it to actually unwind, drop the old
// exchange from the transcript, and put the text in the composer under an
// ✎ EDIT tag so Enter sends the edit as a fresh turn from that point.
import { asCommandDispatch } from '../lib/rpc.js'
import type { Msg } from '../types.js'

/** Retry schedule (ms) for the rewind while the interrupted turn unwinds —
 * about ten seconds in total before giving up. */
export const EDIT_REWIND_RETRY_MS = [250, 500, 750, 1000, 1500, 2000, 2000, 2000] as const

/**
 * Everything from the last user message to the end: the bubble, Robo's
 * partial answer, tool trails, the "interrupted" note. This is the exchange
 * the edit replaces — the gateway has already dropped it from history.
 * (Unlike /undo's trim, a trailing system line does not protect the bubble.)
 * An answer to a clarify question (`kind: 'clarify'`) is a user bubble but
 * not a prompt: it belongs to the exchange above it and goes with it.
 */
export function trimFromLastUser(items: Msg[]): Msg[] {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    if (items[i]!.role === 'user' && items[i]!.kind !== 'clarify') {
      return items.slice(0, i)
    }
  }

  return items
}

export interface RewindDeps {
  isBusyError: (e: unknown) => boolean
  request: (method: string, params: Record<string, unknown>) => Promise<unknown>
  sleep: (ms: number) => Promise<void>
}

export interface RewindResult {
  message: string
  notice?: string
}

/**
 * Back the session up to (and including) the last user message and return
 * its text. `command.dispatch /undo` refuses with "session busy" while an
 * interrupted turn is still unwinding; that error — and only that error — is
 * retried on the schedule. Anything else propagates. Resolves null when the
 * gateway answered with something other than a prefill (nothing to undo).
 */
export async function rewindLastTurn(
  sid: string,
  deps: RewindDeps,
  delays: readonly number[] = EDIT_REWIND_RETRY_MS
): Promise<null | RewindResult> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      const raw = await deps.request('command.dispatch', { arg: '', name: 'undo', session_id: sid })
      const d = asCommandDispatch(raw)

      return d?.type === 'prefill' ? { message: d.message, notice: d.notice } : null
    } catch (e) {
      if (!deps.isBusyError(e) || attempt >= delays.length) {
        throw e
      }

      await deps.sleep(delays[attempt]!)
    }
  }
}
