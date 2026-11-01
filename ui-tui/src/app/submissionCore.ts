import type { GatewayClient } from '../gatewayClient.js'
import type { InputDetectDropResponse, PromptSubmitResponse } from '../gatewayTypes.js'
import type { Msg } from '../types.js'

import type { MidTurnSentStatus } from './interfaces.js'
import { turnController } from './turnController.js'
import { getUiState, patchUiState } from './uiStore.js'

const SESSION_BUSY_RE = /session busy|waiting for model response/i

export const isSessionBusyError = (e: unknown) => e instanceof Error && SESSION_BUSY_RE.test(e.message)

export interface SubmitPromptDeps {
  /** Mid-turn sends: place the bubble in the live turn; false → appendMessage. */
  appendLiveUserMessage?: (msg: Msg) => boolean
  appendMessage: (msg: Msg) => void
  enqueue: (text: string) => void
  expand: (text: string) => string
  gw: GatewayClient
  setLastUserMsg: (value: string) => void
  sys: (text: string) => void
}

// Optimistically flip the session to busy the INSTANT a prompt is accepted for
// submission — synchronously, before we await anything.
//
// This is the fix for the queue-mode race (display.busy_input_mode: queue):
// the submit path first fires an async `input.detect_drop` RPC and only marked
// the session busy inside that RPC's `.then`. A second Enter pressed inside
// that round-trip window read `busy === false` in dispatchSubmission and raced
// a second `prompt.submit` onto the backend instead of landing in the local
// queue. That produced the reported symptom: the second message "waited for
// the first to respond, then went to the queue", and the client lost track of
// it (the backend accepts a mid-turn submit as {status:"queued"} — a success,
// not an error — so the local drain effect that watches the client-side queue
// never fires, leaving the UI stuck on "analyzing…" until Ctrl+C).
//
// Marking busy at the choke point closes the gap for every caller: the mainline
// submit, queue-edit picks, and the drain effect all funnel through here.
export function markSubmitting(): void {
  patchUiState({ busy: true, status: 'running…' })
}

// The gateway echoes an accepted mid-turn message back as `message.user` so
// every client renders it from the authoritative source. This client already
// appends its own bubble synchronously at submit time, so remember what it
// echoed and let the event handler skip the duplicate. Keyed on trimmed text.
// The echo is sent when the gateway ACCEPTS the message, which on a busy
// turn (heavy tool batch, long stream) can trail the submit by well over the
// RPC round-trip; a short window let the late echo through as a second
// bubble. Entries are consumed on match, so a wide window costs nothing.
const LOCAL_ECHO_TTL_MS = 120_000
const recentLocalEchoes: { at: number; text: string }[] = []

export function rememberLocalUserEcho(text: string): void {
  const now = Date.now()
  recentLocalEchoes.push({ at: now, text: text.trim() })

  while (recentLocalEchoes.length && now - recentLocalEchoes[0]!.at > LOCAL_ECHO_TTL_MS) {
    recentLocalEchoes.shift()
  }
}

// True (and consumes the entry) when this text was just echoed locally.
export function consumeLocalUserEcho(text: string): boolean {
  const now = Date.now()
  const wanted = text.trim()
  const idx = recentLocalEchoes.findIndex(e => e.text === wanted && now - e.at <= LOCAL_ECHO_TTL_MS)

  if (idx === -1) {
    return false
  }

  recentLocalEchoes.splice(idx, 1)

  return true
}

// ── Mid-turn sends ───────────────────────────────────────────────────
//
// A message sent while a turn is running gets its transcript bubble like any
// other — but that bubble is appended to settled history, which renders ABOVE
// the live reply block (streamed text, tool trail, reasoning). Once that block
// is taller than the viewport the bubble is out of sight, and the user has no
// way to tell whether Enter did anything until the model reacts, seconds or
// minutes later. So the composer pane also shows each mid-turn send
// (components/midTurnSent.tsx): 'sending' the instant Enter is pressed, then
// what the gateway did with it. The row is an acknowledgement, not a fixture:
// once settled it stays for MID_TURN_SETTLED_MS and then goes — the bubble is
// the record — so nothing sits under the transcript for the rest of the turn.
// turnController.idle() clears whatever is left when the turn ends.
const MID_TURN_SENT_LIMIT = 5
export const MID_TURN_SETTLED_MS = 4000
let midTurnSentSeq = 0
const midTurnDismissTimers = new Map<number, ReturnType<typeof setTimeout>>()

function scheduleMidTurnDismiss(id: number): void {
  const previous = midTurnDismissTimers.get(id)

  if (previous) {
    clearTimeout(previous)
  }

  midTurnDismissTimers.set(
    id,
    setTimeout(() => {
      midTurnDismissTimers.delete(id)
      dismissMidTurnSend(id)
    }, MID_TURN_SETTLED_MS)
  )
}

function cancelMidTurnDismiss(id: number): void {
  const timer = midTurnDismissTimers.get(id)

  if (timer) {
    clearTimeout(timer)
    midTurnDismissTimers.delete(id)
  }
}

export function trackMidTurnSend(text: string, status: MidTurnSentStatus = 'sending'): number {
  const id = ++midTurnSentSeq
  const label = text.trim()

  patchUiState(state => ({
    ...state,
    midTurnSent: [...state.midTurnSent, { id, status, text: label }].slice(-MID_TURN_SENT_LIMIT)
  }))

  // A row that arrives already settled (the gateway's echo of a message
  // another client sent) is acknowledged for the same short while.
  if (status !== 'sending') {
    scheduleMidTurnDismiss(id)
  }

  return id
}

// Resolve a tracked send once the gateway has answered. 'dropped' removes the
// row at once: the text went back to the local queue (its own panel shows it)
// or the send errored (a sys note says so) — either way the strip must not
// claim it reached the live turn. Any other status shows briefly, then the
// row dismisses itself.
export function settleMidTurnSend(id: number, status: 'dropped' | MidTurnSentStatus): void {
  patchUiState(state => {
    if (!state.midTurnSent.some(item => item.id === id)) {
      return state
    }

    return {
      ...state,
      midTurnSent:
        status === 'dropped'
          ? state.midTurnSent.filter(item => item.id !== id)
          : state.midTurnSent.map(item => (item.id === id ? { ...item, status } : item))
    }
  })

  if (status === 'dropped') {
    cancelMidTurnDismiss(id)
  } else if (status !== 'sending') {
    scheduleMidTurnDismiss(id)
  }
}

// Remove one acknowledged row. A no-op when the row is already gone (the turn
// ended first, or a later clear took it).
export function dismissMidTurnSend(id: number): void {
  cancelMidTurnDismiss(id)
  patchUiState(state =>
    state.midTurnSent.some(item => item.id === id)
      ? { ...state, midTurnSent: state.midTurnSent.filter(item => item.id !== id) }
      : state
  )
}

export function clearMidTurnSends(): void {
  for (const timer of midTurnDismissTimers.values()) {
    clearTimeout(timer)
  }

  midTurnDismissTimers.clear()

  if (getUiState().midTurnSent.length) {
    patchUiState({ midTurnSent: [] })
  }
}

// Maps the gateway's answer to a mid-turn prompt.submit / session.steer onto a
// strip status. 'queued' means "runs as the next turn"; anything else the
// gateway accepted ('redirected', 'steered', a legacy bare ok) reached the
// live turn.
export const midTurnStatusFromGateway = (status: unknown): MidTurnSentStatus =>
  status === 'queued' || status === 'redirected' || status === 'steered' ? status : 'sent'

// Submit a ready prompt (already resolved to be neither a slash command nor a
// shell escape, with a live session). Pulled out of useSubmission so the
// synchronous-busy and synchronous-message-display invariants above are
// unit-testable without React test infra.
//
// `displayOverride` is what the transcript shows when it differs from what the
// agent receives — a `/skill` invocation expands into the whole skill body, and
// that scaffolding is model-facing only.
//
// `midTurn` marks a send made while a turn was already running (the busy
// interrupt/redirect policy): it is tracked in the composer strip until the
// gateway says what became of it. A fresh turn clears any stale strip.
export function submitPrompt(
  text: string,
  deps: SubmitPromptDeps,
  showUserMessage = true,
  displayOverride?: string,
  midTurn = false
): void {
  const sid = getUiState().sid

  if (!sid) {
    return deps.sys('session not ready yet')
  }

  // Close the async-busy gap up front, before the detect_drop round-trip —
  // same fix as markSubmitting() below, extended to cover the user's own
  // message bubble. Previously this only showed once detect_drop resolved,
  // so a submit made while the gateway's event loop is busy running the
  // agent's active turn (heavy tool execution, long streaming) could sit
  // invisible for a real, user-noticeable stretch even though the message
  // was already accepted — the agent would eventually pick it up and
  // respond, but nothing on screen showed it had been sent at all.
  markSubmitting()

  if (!midTurn) {
    clearMidTurnSends()
  }

  // A mid-turn send placed in the live block is its own acknowledgement: it
  // sits under the work so far, where Robo reads it next. The strip would
  // only repeat it. The strip is kept for a send the live block could not
  // take (it went to settled history, above the block and out of sight) —
  // and, below, for the one thing the bubble cannot say: that the gateway
  // parked the text (queued / steered) instead of reading it now.
  let placedLive = false

  if (showUserMessage) {
    const bubble: Msg = { role: 'user', text: displayOverride || text }

    deps.setLastUserMsg(text)
    placedLive = Boolean(midTurn && deps.appendLiveUserMessage?.(bubble))

    if (!placedLive) {
      deps.appendMessage(bubble)
    }

    rememberLocalUserEcho(text)
  }

  const tracked = midTurn && !placedLive ? trackMidTurnSend(displayOverride || text) : null

  const startSubmit = (submitText: string) => {
    const liveSid = getUiState().sid

    if (!liveSid) {
      if (tracked !== null) {
        settleMidTurnSend(tracked, 'dropped')
      }

      return deps.sys('session not ready yet')
    }

    // The gateway echoes back the text it received — the expanded payload,
    // not the composer text with its [[ paste ]] tokens — so remember that
    // form too or the echo would paint a second bubble.
    if (showUserMessage && submitText !== text) {
      rememberLocalUserEcho(submitText)
    }

    turnController.clearStatusTimer()

    patchUiState({ busy: true, status: 'running…' })
    turnController.bufRef = ''
    turnController.interrupted = false

    deps.gw
      .request<PromptSubmitResponse>('prompt.submit', { session_id: liveSid, text: submitText })
      .then(r => {
        const outcome = midTurnStatusFromGateway(r?.status)

        if (tracked !== null) {
          settleMidTurnSend(tracked, outcome)
        } else if (placedLive && (outcome === 'queued' || outcome === 'steered')) {
          // Not read now after all: say so briefly, then let it go.
          trackMidTurnSend(displayOverride || text, outcome)
        }

        // The gateway consumed a typed voice stop phrase server-side (voice
        // chat ended, no turn started) — release the busy latch; the
        // voice.transcript {stop_phrase} event handles the mode flags + notice.
        if (r?.voice_stopped) {
          patchUiState({ busy: false, status: 'ready' })
        }
      })
      .catch((e: Error) => {
        if (tracked !== null) {
          settleMidTurnSend(tracked, 'dropped')
        }

        // Defensive: prompt.submit no longer rejects a mid-turn send with
        // "session busy" (the gateway queues it and returns success), but keep
        // the re-queue path as a safety net for any future/legacy gateway that
        // still errors, so a message is never silently dropped.
        if (isSessionBusyError(e)) {
          deps.enqueue(submitText)
          patchUiState({ busy: true, status: 'queued for next turn' })

          return deps.sys(`queued: "${submitText.slice(0, 50)}${submitText.length > 50 ? '…' : ''}"`)
        }

        deps.sys(`error: ${e.message}`)
        patchUiState({ busy: false, status: 'ready' })
      })
  }

  // Always ask the backend whether this looks like a file drop. The backend's
  // _detect_file_drop handles paths with spaces, quotes, Windows drive letters,
  // and escaped characters correctly.
  //
  // No notice is emitted for a match: an image dropped into the composer already
  // shows as an `[[ Image N ]]` token, and a matched non-image path is rewritten
  // in place. Announcing it a second time above the status bar was the old
  // out-of-band attachment UI.
  deps.gw
    .request<InputDetectDropResponse>('input.detect_drop', { session_id: sid, text })
    .then(r => {
      if (!r?.matched) {
        return startSubmit(deps.expand(text))
      }

      startSubmit(deps.expand(r.text || text))
    })
    .catch(() => startSubmit(deps.expand(text)))
}
