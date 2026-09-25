import type { GatewayClient } from '../gatewayClient.js'
import type { InputDetectDropResponse, PromptSubmitResponse } from '../gatewayTypes.js'
import type { Msg } from '../types.js'

import type { MidTurnSentStatus } from './interfaces.js'
import { turnController } from './turnController.js'
import { getUiState, patchUiState } from './uiStore.js'

const SESSION_BUSY_RE = /session busy|waiting for model response/i

export const isSessionBusyError = (e: unknown) => e instanceof Error && SESSION_BUSY_RE.test(e.message)

export interface SubmitPromptDeps {
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
// echoed and let the event handler skip the duplicate. Keyed on trimmed text;
// a few seconds is plenty for the RPC round-trip.
const LOCAL_ECHO_TTL_MS = 15_000
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
// minutes later. So the composer pane also lists every mid-turn send
// (components/midTurnSent.tsx) — 'sending' at once, then what the gateway did
// with it — until the turn ends (turnController.idle() clears the list).
const MID_TURN_SENT_LIMIT = 5
let midTurnSentSeq = 0

export function trackMidTurnSend(text: string, status: MidTurnSentStatus = 'sending'): number {
  const id = ++midTurnSentSeq
  const label = text.trim()

  patchUiState(state => ({
    ...state,
    midTurnSent: [...state.midTurnSent, { id, status, text: label }].slice(-MID_TURN_SENT_LIMIT)
  }))

  return id
}

// Resolve a tracked send once the gateway has answered. 'dropped' removes the
// row: the text went back to the local queue (its own panel shows it) or the
// send errored (a sys note says so) — either way the strip must not claim it
// reached the live turn.
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
}

export function clearMidTurnSends(): void {
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

  const tracked = midTurn ? trackMidTurnSend(displayOverride || text) : null

  if (showUserMessage) {
    deps.setLastUserMsg(text)
    deps.appendMessage({ role: 'user', text: displayOverride || text })
    rememberLocalUserEcho(text)
  }

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
        if (tracked !== null) {
          settleMidTurnSend(tracked, midTurnStatusFromGateway(r?.status))
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
