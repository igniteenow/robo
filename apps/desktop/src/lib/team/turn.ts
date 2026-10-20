/**
 * Wait for one member's turn to settle. The AUTHORITATIVE end of a turn is the
 * gateway's `message.complete` event (`awaitTurnViaEvents`): the backend emits
 * exactly one per turn, with the final text, so the controller never mistakes
 * a mid-turn blip for the answer. The busy flag alone cannot be trusted —
 * `session.info running:false` heartbeats arrive between tool batches once the
 * model has emitted anything (reasoning included), flipping `busy` false while
 * the turn runs on; reading that as the turn end is what made a lead that had
 * plainly answered report "no reply". Busy is kept only as a debounced fallback
 * for the rare turn whose completion event never arrives (a reconnect gap).
 *
 * Everything is pure over small injected sources (`get`/`listen` for state, a
 * subscribe function for completion events) so both paths are exercised with
 * plain fakes in tests; the real host wires `$sessionStates` and the
 * `message.complete` gateway event.
 */

import type { ClientSessionState } from '@/app/types'
import { type ChatMessage, chatMessageText } from '@/lib/chat-messages'

export interface SessionStatesSource {
  get(): Record<string, ClientSessionState>
  listen(listener: (states: Record<string, ClientSessionState>) => void): () => void
}

export interface TurnOutcome {
  /** The reply text (the last assistant message of the turn). */
  text: string
  /** Set when the turn ended in an error bubble, a timeout, or an interrupt. */
  error?: string
  interrupted: boolean
  timedOut: boolean
}

export interface AwaitTurnOptions {
  /** Give up after this long; the caller decides whether to interrupt.
   *  `Infinity` (the team's default) means never: a turn runs until it truly
   *  ends, and only Stop cuts it short. */
  timeoutMs: number
  /** Resolves early (as interrupted) when the signal aborts — the Stop button. */
  signal?: AbortSignal
}

/** The reply text + error a `message.complete` event carries, already coerced
 *  from the raw payload by the caller (so this module stays free of the
 *  gateway's payload shapes). */
export interface TurnComplete {
  text: string
  error?: string
}

/** Subscribe to turn-completion events for ONE session; returns a disposer.
 *  The real host wraps `onGatewayEvent('message.complete')` filtered by
 *  session id; a test passes a trivial emitter. */
export type TurnCompleteSource = (runtimeId: string, listener: (complete: TurnComplete) => void) => () => void

/** How long a session must stay idle with no completion event before the
 *  fallback settles the turn from state. Long enough that a mid-turn
 *  `running:false` blip (followed within ~1s by the next model request) is
 *  absorbed, short enough that a genuinely stuck turn doesn't hang the run. */
export const TEAM_IDLE_SETTLE_MS = 2500

/** How long a session may sit idle with NO committed reply and no completion
 *  event before the turn is settled anyway (as no reply). Not a cap on work —
 *  a working seat is busy — but the one way out when the completion event is
 *  lost (a reconnect gap) on a turn that has no clock of its own. A mid-turn
 *  `running:false` blip is followed by the next model request within about a
 *  second; five minutes of true silence is a stall. */
export const TEAM_IDLE_STALL_MS = 5 * 60 * 1000

/** Last non-hidden assistant message in a transcript, or null. */
export function lastAssistantMessage(messages: readonly ChatMessage[]): ChatMessage | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i]

    if (message.role === 'assistant' && !message.hidden) {
      return message
    }
  }

  return null
}

/** The assistant text produced since `sinceCount` messages — the turn's
 *  reply. Nothing new after the submit means NO reply (never the previous
 *  turn's text — a stale settle must not be mistaken for a fresh vote). The
 *  one exception is a transcript rewritten underneath us (a resume
 *  re-hydration can renumber it): then the last assistant message is the
 *  best available reading. */
export function turnReplyText(messages: readonly ChatMessage[], sinceCount: number): { text: string; error?: string } {
  const renumbered = messages.length < sinceCount

  const candidates = renumbered
    ? [lastAssistantMessage(messages)].filter((m): m is ChatMessage => m !== null)
    : messages.slice(sinceCount).filter(m => m.role === 'assistant' && !m.hidden)

  const texts = candidates.map(m => chatMessageText(m).trim()).filter(Boolean)
  const error = candidates.map(m => m.error).find(Boolean)

  return { text: texts.join('\n\n'), ...(error ? { error } : {}) }
}

/**
 * Resolve when `runtimeId`'s state leaves `busy`. The caller must have put
 * the session INTO busy (the optimistic submit seed) before calling, so the
 * first idle publish is the settle; a session that was never busy resolves
 * on the next idle publish or immediately.
 *
 * The timeout is model time, not user time: while the member is blocked on
 * the user (`needsInput` — a command approval, a clarify question, a
 * fact-check correction) the clock pauses, and resumes when the answer lands.
 */
export function awaitSessionTurn(
  source: SessionStatesSource,
  runtimeId: string,
  sinceCount: number,
  { signal, timeoutMs }: AwaitTurnOptions
): Promise<TurnOutcome> {
  return new Promise(resolve => {
    let done = false
    let unlisten: (() => void) | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    let remainingMs = timeoutMs
    let armedAt = 0

    const finish = (outcome: TurnOutcome) => {
      if (done) {
        return
      }

      done = true

      if (unlisten) {
        unlisten()
      }

      if (timer !== null) {
        clearTimeout(timer)
      }

      signal?.removeEventListener('abort', onAbort)
      resolve(outcome)
    }

    const onTimeout = () => {
      const state = source.get()[runtimeId]
      const reply = turnReplyText(state?.messages ?? [], sinceCount)
      finish({ error: 'timed out', interrupted: false, text: reply.text, timedOut: true })
    }

    const arm = () => {
      // No clock at all for an unlimited turn (a non-finite delay would fire
      // at once in the browser).
      if (!Number.isFinite(remainingMs)) {
        return
      }

      armedAt = Date.now()
      timer = setTimeout(onTimeout, remainingMs)
    }

    const pause = () => {
      if (timer !== null) {
        clearTimeout(timer)
        timer = null
        remainingMs = Math.max(1000, remainingMs - (Date.now() - armedAt))
      }
    }

    const settle = (state: ClientSessionState | undefined) => {
      const reply = turnReplyText(state?.messages ?? [], sinceCount)

      finish({
        interrupted: Boolean(state?.interrupted),
        text: reply.text,
        timedOut: false,
        ...(reply.error ? { error: reply.error } : {})
      })
    }

    const onAbort = () => {
      const state = source.get()[runtimeId]
      const reply = turnReplyText(state?.messages ?? [], sinceCount)
      finish({ error: 'stopped', interrupted: true, text: reply.text, timedOut: false })
    }

    if (signal?.aborted) {
      onAbort()

      return
    }

    signal?.addEventListener('abort', onAbort)

    const check = (states: Record<string, ClientSessionState>) => {
      const state = states[runtimeId]

      if (state && !state.busy) {
        settle(state)

        return
      }

      if (state?.needsInput) {
        pause()
      } else if (timer === null && !done) {
        arm()
      }
    }

    unlisten = source.listen(check)
    check(source.get())
  })
}

/**
 * Resolve when `runtimeId`'s turn truly completes. Primary signal: a
 * `message.complete` event (via `onComplete`). Because that event fires before
 * the store commits the final bubble, the reply is read a microtask later,
 * preferring the settled transcript and falling back to the event's own text.
 * Fallbacks: a deliberate interrupt settles at once; an idle stretch with no
 * completion event settles after `idleSettleMs` when a reply is committed (a
 * mid-turn blip is cancelled when `busy` returns), or after `idleStallMs` when
 * none is — so a lost event cannot hold an unlimited turn forever; the
 * timeout and its `needsInput` pause are unchanged.
 */
export function awaitTurnViaEvents(
  onComplete: TurnCompleteSource,
  source: SessionStatesSource,
  runtimeId: string,
  sinceCount: number,
  { signal, timeoutMs }: AwaitTurnOptions,
  idleSettleMs: number = TEAM_IDLE_SETTLE_MS,
  idleStallMs: number = TEAM_IDLE_STALL_MS
): Promise<TurnOutcome> {
  return new Promise(resolve => {
    let done = false
    let unlisten: (() => void) | null = null
    let offComplete: (() => void) | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    let idleTimer: ReturnType<typeof setTimeout> | null = null
    // Whether the armed idle timer is the long stall window (no reply yet)
    // rather than the short settle debounce (reply committed).
    let idleTimerIsStall = false
    let remainingMs = timeoutMs
    let armedAt = 0

    const finish = (outcome: TurnOutcome) => {
      if (done) {
        return
      }

      done = true
      unlisten?.()
      offComplete?.()

      if (timer !== null) {
        clearTimeout(timer)
      }

      if (idleTimer !== null) {
        clearTimeout(idleTimer)
      }

      signal?.removeEventListener('abort', onAbort)
      resolve(outcome)
    }

    const settleFromState = (extra?: Partial<TurnOutcome>) => {
      const state = source.get()[runtimeId]
      const reply = turnReplyText(state?.messages ?? [], sinceCount)

      finish({
        interrupted: Boolean(state?.interrupted),
        text: reply.text,
        timedOut: false,
        ...(reply.error ? { error: reply.error } : {}),
        ...extra
      })
    }

    const arm = () => {
      if (!Number.isFinite(remainingMs)) {
        return
      }

      armedAt = Date.now()
      timer = setTimeout(() => settleFromState({ error: 'timed out', timedOut: true }), remainingMs)
    }

    const pause = () => {
      if (timer !== null) {
        clearTimeout(timer)
        timer = null
        remainingMs = Math.max(1000, remainingMs - (Date.now() - armedAt))
      }
    }

    const onAbort = () => settleFromState({ error: 'stopped', interrupted: true })

    if (signal?.aborted) {
      onAbort()

      return
    }

    signal?.addEventListener('abort', onAbort)

    offComplete = onComplete(runtimeId, complete => {
      // The event beats the store update, so read the committed reply a
      // microtask later; fall back to the event's own text when the stream
      // left the final bubble empty (text arrived only via deltas).
      queueMicrotask(() => {
        if (done) {
          return
        }

        const state = source.get()[runtimeId]
        const reply = turnReplyText(state?.messages ?? [], sinceCount)
        const error = reply.error ?? complete.error

        finish({
          interrupted: Boolean(state?.interrupted),
          text: reply.text || complete.text.trim(),
          timedOut: false,
          ...(error ? { error } : {})
        })
      })
    })

    const check = (states: Record<string, ClientSessionState>) => {
      const state = states[runtimeId]

      if (!state) {
        return
      }

      // Timeout clock: pause while the member waits on the user.
      if (state.needsInput) {
        pause()
      } else if (timer === null) {
        arm()
      }

      if (state.busy) {
        // A new or continuing turn — a mid-turn idle blip has resolved.
        if (idleTimer !== null) {
          clearTimeout(idleTimer)
          idleTimer = null
        }

        return
      }

      // A deliberate interrupt is terminal (no spurious-false risk) — settle now.
      if (state.interrupted) {
        settleFromState()

        return
      }

      const reply = turnReplyText(state.messages, sinceCount)

      // A turn that ended in an error bubble — the gateway's bare `error`
      // event (agent init failed, a refused prompt, a build cancelled before
      // the agent was ready) — never gets a completion event, and the error
      // is terminal: settle now rather than hold the seat until the timeout.
      if (reply.error) {
        settleFromState()

        return
      }

      // Idle fallback, for the rare turn whose completion event never arrives
      // (a reconnect gap): settle after the debounce. Gated on a committed
      // reply actually being present — a mid-turn `running:false` blip leaves
      // only a pending/empty bubble, and settling on that is the very bug this
      // waiter exists to avoid, so an empty idle keeps waiting for the event
      // for a long while (the stall window) before giving up on it.
      const hasReply = reply.text.length > 0

      // A reply that lands while the stall window is running shortens the
      // wait to the ordinary settle debounce.
      if (idleTimer === null || (hasReply && idleTimerIsStall)) {
        if (idleTimer !== null) {
          clearTimeout(idleTimer)
        }

        idleTimerIsStall = !hasReply
        idleTimer = setTimeout(settleFromState, hasReply ? idleSettleMs : idleStallMs)
      }
    }

    unlisten = source.listen(check)
    check(source.get())
  })
}
