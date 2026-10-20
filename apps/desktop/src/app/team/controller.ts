/**
 * TEAM MODE CONTROLLER — runs a team over ordinary backend sessions.
 *
 * Each seat is a real `session.create` with its own model/provider; the
 * controller only ever APPENDS user prompts to those sessions (never rebuilds
 * a system prompt, never edits history), so every member keeps its cached
 * prefix across rounds and runs. Turn completion is observed on the same
 * per-runtime state the panes render from (`$sessionStates` busy edge), so
 * what the team acts on is exactly what the user sees.
 *
 * The loop (no round cap and no turn clock by default — a goal takes the
 * rounds and the time it takes; an optional cap and Stop bound it):
 *
 *   round k:  lead works ──▶ ```team block (summary, 2–4 options, side task?)
 *             reviewers (idle ones) rank the options in parallel, each in its
 *             own shuffled order, and write GUIDANCE for the lead ──▶ Borda
 *             tally ──▶ decision
 *             finished side tasks with options get the same mini-review
 *             lead gets: decision + reviewers' reasons + guidance + side
 *             results ──▶ k+1
 *   status: done ──▶ COMPLETION CHECK: the reviewers verify the result
 *             against the goal; "not done" sends the lead back with their
 *             guidance (up to TEAM_MAX_COMPLETION_PUSHBACKS times) ──▶ the
 *             Final seat writes the outcome
 *   rounds exhausted (capped runs only) → one wrap-up turn ──▶ final answer
 *
 * A reviewer that is busy on a side task simply skips that vote; a reviewer
 * that errors or times out casts no ballot; no valid ballots at all falls
 * back to the lead's first option — the run keeps moving, the log says why.
 * Stop aborts every wait and interrupts the members that are mid-turn.
 *
 * Everything that touches the gateway or the stores goes through `TeamHost`,
 * so the whole loop runs against a fake in tests.
 */

import { onGatewayEvent } from '@/contrib/events'
import { translateNow } from '@/i18n'
import { textPart } from '@/lib/chat-messages'
import { coerceGatewayText } from '@/lib/chat-runtime'
import { setCompletionSoundQuiet } from '@/lib/completion-sound'
import {
  buildCompletionReviewPrompt,
  buildFinalPrompt,
  buildFinalSynthesisPrompt,
  buildLeadContinuePrompt,
  buildLeadKickoffPrompt,
  buildPushbackPrompt,
  buildRepairPrompt,
  buildReviewPrompt,
  buildSideReviewPrompt,
  buildSideTaskPrompt,
  clampTeamSize,
  clip,
  COMPLETION_NOT_DONE,
  COMPLETION_OPTIONS,
  completionVerdict,
  hasRoundCap,
  parseTeamResult,
  parseTeamVote,
  shuffleOptionsFor,
  tallyBallots,
  TEAM_FINAL_INDEX,
  TEAM_MAX_COMPLETION_PUSHBACKS,
  type TeamBallot,
  type TeamDecision,
  teamMemberName,
  type TeamOption,
  type TeamResult,
  type TeamSideResult,
  unshuffleRanking
} from '@/lib/team/protocol'
import { awaitTurnViaEvents, type SessionStatesSource, type TurnComplete, type TurnOutcome } from '@/lib/team/turn'
import { $gateway } from '@/store/gateway'
import { notify } from '@/store/notifications'
import { $activeGatewayProfile, $newChatProfile, ensureGatewayProfile, normalizeProfileKey } from '@/store/profile'
import { resolveNewSessionCwd } from '@/store/projects'
import { $activeSessionId, $gatewayState } from '@/store/session'
import { $sessionStates, sessionTileDelegate } from '@/store/session-states'
import { broadcastSessionsChanged } from '@/store/session-sync'
import {
  $teamConfig,
  $teamMembers,
  $teamRun,
  appendTeamLog,
  createTeamMember,
  createTeamRun,
  patchTeamMember,
  patchTeamRun,
  type TeamMember,
  type TeamMemberConfig,
  teamRunActive
} from '@/store/team'
import type { SessionCreateResponse } from '@/types/robo'

/** No clock on a member turn: a very complex goal takes the time it takes,
 *  and a turn ends when the backend says so (completion, error, interrupt).
 *  Stop is the user's cut-off. */
export const TEAM_TURN_TIMEOUT_MS = Number.POSITIVE_INFINITY
/** Reviews are unlimited too: a reviewer that re-runs the tests or re-checks
 *  the sources is doing the team's work, not stalling it. */
export const TEAM_REVIEW_TIMEOUT_MS = Number.POSITIVE_INFINITY

export interface TeamHost {
  /** Create a backend session for a seat; returns its runtime + stored ids. */
  createSession(index: number, config: TeamMemberConfig, title: string): Promise<{
    runtimeId: string
    storedSessionId: string
  }>
  /** Re-bind a seat's stored session after a reconnect; returns the new
   *  runtime id. Throws when the session is gone (the seat is re-created). */
  resumeSession(storedSessionId: string): Promise<string>
  /** Best-effort close of a seat's session (crew reset). */
  closeSession(runtimeId: string): Promise<void>
  /** Paint the prompt as the user's bubble, mark the session busy, submit.
   *  Sent as a queued prompt: should the session turn out to be mid-turn
   *  after all, the gateway holds it for the next turn instead of redirecting
   *  the live one. */
  submit(runtimeId: string, text: string): Promise<void>
  interrupt(runtimeId: string): Promise<void>
  /** Transcript length right now — the turn's reply is what lands after it. */
  messageCount(runtimeId: string): number
  /** Wait for a member's turn to truly end (authoritative completion event,
   *  with a busy-idle fallback) and return its reply. Owned by the host so the
   *  real path uses gateway events and tests drive it off a state atom. */
  awaitTurn(runtimeId: string, sinceCount: number, options: AwaitTurnArgs): Promise<TurnOutcome>
  states: SessionStatesSource
  turnTimeoutMs: number
  reviewTimeoutMs: number
}

interface AwaitTurnArgs {
  signal?: AbortSignal
  timeoutMs: number
}

/** Map a `message.complete` event to a `TurnComplete`, or `null` when it is
 *  for another session. Pure, so the session-id filter and the payload
 *  coercion (text / rendered fallback, terminal `status: 'error'`) are tested
 *  without a live gateway. */
export function completionFromEvent(
  event: { payload?: unknown; session_id?: string; type?: string },
  runtimeId: string
): null | TurnComplete {
  if ((event.session_id || '') !== runtimeId) {
    return null
  }

  const payload = event.payload as { error?: unknown; rendered?: unknown; status?: string; text?: unknown } | undefined
  const text = (coerceGatewayText(payload?.text) || coerceGatewayText(payload?.rendered)).trim()

  const error =
    payload?.status === 'error' ? coerceGatewayText(payload.error).trim() || text || 'Robo reported an error' : undefined

  return { text, ...(error ? { error } : {}) }
}

/** The real completion signal: one `message.complete` per turn for this
 *  session (subagent completions carry the child's id and are filtered out). */
const realTurnComplete = (runtimeId: string, listener: (complete: TurnComplete) => void): (() => void) =>
  onGatewayEvent('message.complete', event => {
    const complete = completionFromEvent(event, runtimeId)

    if (complete) {
      listener(complete)
    }
  })

// ---------------------------------------------------------------------------
// The real host: gateway + session-state cache through the tile delegate.
// ---------------------------------------------------------------------------

function requireDelegate() {
  const delegate = sessionTileDelegate()

  if (!delegate) {
    throw new Error(translateNow('team.errors.notReady'))
  }

  return delegate
}

function requireGateway() {
  const gateway = $gateway.get()

  if (!gateway) {
    throw new Error(translateNow('team.notConnected'))
  }

  return gateway
}

/**
 * Send a prompt to a seat and paint it there at once — the one path for both
 * the controller's briefs and a message the user types in the page composer.
 *
 * `prompt.submit` to an IDLE seat runs the turn without echoing the user's
 * text (the main composer paints its own bubble), so a page-composer message
 * that went straight to the RPC never appeared in the pane: the user typed
 * to the Final, saw nothing, and had no idea whether it was received. Idle:
 * the same optimistic seed the composer's submit path uses — the bubble,
 * busy / awaitingResponse, a fresh turn — so the pane shows the message and
 * the thinking indicator before the gateway answers. BUSY (the seat is
 * mid-turn): only the bubble, at the tail. The gateway parks the text for the
 * next turn and echoes it as `message.user`, which the stream dedupes on
 * text; the live stream's bookkeeping (streamId, sawAssistantPayload) is left
 * alone so the reply keeps streaming into its own bubble. A failed submit
 * rolls the bubble back and rethrows, so the caller can keep the text.
 */
export async function submitTeamPrompt(runtimeId: string, text: string): Promise<void> {
  const delegate = requireDelegate()
  const optimisticId = `team-user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const busy = Boolean($sessionStates.get()[runtimeId]?.busy)
  const bubble = { id: optimisticId, parts: [textPart(text)], role: 'user' as const }

  delegate.updateSession(runtimeId, state =>
    busy
      ? { ...state, messages: [...state.messages, bubble] }
      : {
          ...state,
          awaitingResponse: true,
          busy: true,
          interrupted: false,
          messages: [...state.messages, bubble],
          pendingBranchGroup: null,
          sawAssistantPayload: false,
          streamId: null,
          turnStartedAt: Date.now()
        }
  )

  try {
    // Queued: should the seat turn out to be mid-turn after all, the gateway
    // holds the text for the next turn instead of redirecting the live one.
    await delegate.submitToSession(runtimeId, text, { queued: true })
  } catch (error) {
    delegate.updateSession(runtimeId, state => ({
      ...state,
      ...(busy ? {} : { awaitingResponse: false, busy: false, turnStartedAt: null }),
      messages: state.messages.filter(m => m.id !== optimisticId)
    }))

    throw error
  }
}

export function createDefaultTeamHost(): TeamHost {
  return {
    closeSession: async runtimeId => {
      setCompletionSoundQuiet(runtimeId, false)

      // A member the user has since opened as the main chat stays alive.
      if (runtimeId === $activeSessionId.get()) {
        return
      }

      await $gateway
        .get()
        ?.request('session.close', { session_id: runtimeId })
        .catch(() => undefined)
    },
    createSession: async (_index, config, title) => {
      const gateway = requireGateway()
      const delegate = requireDelegate()
      const profile = $newChatProfile.get() ?? normalizeProfileKey($activeGatewayProfile.get())
      await ensureGatewayProfile(profile)
      const cwd = resolveNewSessionCwd().trim()

      const created = await gateway.request<SessionCreateResponse>('session.create', {
        // Team seats share one ROBO_HOME and run at the same time: their
        // post-turn self-improvement reviews would patch the same skill and
        // memory files in the same moment ("updated by teammates already").
        // Opt every seat out; an older backend ignores the flag harmlessly.
        background_review: false,
        cols: 96,
        // The team verifies its own answers (the reviewers' votes and the
        // completion check). The per-answer fact check — claim extraction
        // plus a research loop after EVERY turn of every seat — is what made
        // the Final take minutes to answer a follow-up while its pane still
        // looked busy; a question typed meanwhile waited behind it.
        fact_check: false,
        source: 'desktop',
        title,
        ...(cwd ? { cwd } : {}),
        ...(profile ? { profile } : {}),
        ...(config.model ? { model: config.model, ...(config.provider ? { provider: config.provider } : {}) } : {})
      })

      const storedSessionId = created.stored_session_id

      if (!storedSessionId) {
        await gateway.request('session.close', { session_id: created.session_id }).catch(() => undefined)

        throw new Error(translateNow('team.errors.noSessionId'))
      }

      // Seed the per-runtime cache so the member's pane renders at once, with
      // the model it was created on (the pill reads from this slice).
      delegate.updateSession(
        created.session_id,
        state => ({
          ...state,
          cwd: created.info?.cwd ?? state.cwd,
          model: created.info?.model ?? config.model,
          provider: created.info?.provider ?? config.provider
        }),
        storedSessionId
      )

      setCompletionSoundQuiet(created.session_id, true)

      return { runtimeId: created.session_id, storedSessionId }
    },
    awaitTurn: (runtimeId, sinceCount, options) =>
      awaitTurnViaEvents(realTurnComplete, $sessionStates, runtimeId, sinceCount, options),
    interrupt: async runtimeId => {
      await requireDelegate().interruptSession(runtimeId)
    },
    messageCount: runtimeId => $sessionStates.get()[runtimeId]?.messages.length ?? 0,
    resumeSession: async storedSessionId => {
      // A seat is resumed only after its runtime was lost (a reconnect, a
      // profile switch back): the cached binding may name a runtime the
      // respawned backend no longer has, so always ask the gateway afresh.
      const runtimeId = await requireDelegate().resumeTile(storedSessionId, { fresh: true })
      setCompletionSoundQuiet(runtimeId, true)
      // The create-time opt-outs do not survive a resume (the session is
      // rebuilt from its stored row): re-assert them. Best effort — a backend
      // without the method leaves the seat as it was.
      await $gateway
        .get()
        ?.request('session.background_review', { enabled: false, fact_check: false, session_id: runtimeId })
        .catch(() => undefined)

      return runtimeId
    },
    reviewTimeoutMs: TEAM_REVIEW_TIMEOUT_MS,
    states: $sessionStates,
    // The controller only briefs an idle seat (memberTurn waits for a running
    // turn first), so this is the idle seed: busy/awaitingResponse keep a
    // stale `running:false` heartbeat from settling the turn early (see the
    // session.info guard in the stream handler).
    submit: submitTeamPrompt,
    turnTimeoutMs: TEAM_TURN_TIMEOUT_MS
  }
}

let host: TeamHost | null = null

/** Swap the host (tests). `null` restores the real one lazily. */
export function setTeamHost(next: TeamHost | null) {
  host = next
}

function getHost(): TeamHost {
  host ??= createDefaultTeamHost()

  return host
}

// ---------------------------------------------------------------------------
// Run bookkeeping.
// ---------------------------------------------------------------------------

interface RunContext {
  runId: string
  abort: AbortController
  /** Side-task results that have come back since the lead was last briefed. */
  sideResults: TeamSideResult[]
  /** Reviewers mid side task (member index → the job's settle promise). */
  sideJobs: Map<number, Promise<void>>
  /** How many times the reviewers have sent a "done" lead back to work. */
  pushbacks: number
}

let context: RunContext | null = null

const isLive = (ctx: RunContext) => context === ctx && $teamRun.get()?.id === ctx.runId && !ctx.abort.signal.aborted

const member = (index: number): TeamMember | undefined => $teamMembers.get().find(m => m.index === index)

const log = (ctx: RunContext, entry: Parameters<typeof appendTeamLog>[1]) => appendTeamLog(ctx.runId, entry)

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** Run one member turn: submit, wait for the settle, return the reply.
 *  `null` when the run went away underneath us. */
async function memberTurn(
  ctx: RunContext,
  index: number,
  prompt: string,
  timeoutMs: number
): Promise<null | { text: string; error?: string; interrupted: boolean; timedOut: boolean }> {
  const seat = member(index)

  if (!seat?.runtimeId || !isLive(ctx)) {
    return null
  }

  const teamHost = getHost()
  const runtimeId = seat.runtimeId

  // The member may be mid-turn on its own account (the user is talking to it
  // in its pane): a prompt sent now would queue behind that turn and the
  // settle we wait for would be that turn's, not ours. Let it finish first.
  if (teamHost.states.get()[runtimeId]?.busy) {
    const idle = await teamHost.awaitTurn(runtimeId, teamHost.messageCount(runtimeId), {
      signal: ctx.abort.signal,
      timeoutMs
    })

    if (idle.timedOut || !isLive(ctx)) {
      return idle.timedOut
        ? { error: translateNow('team.errors.turnTimedOut'), interrupted: false, text: '', timedOut: true }
        : null
    }
  }

  const since = teamHost.messageCount(runtimeId)

  try {
    await teamHost.submit(runtimeId, prompt)
  } catch (error) {
    return { error: errorText(error), interrupted: false, text: '', timedOut: false }
  }

  const outcome = await teamHost.awaitTurn(runtimeId, since, { signal: ctx.abort.signal, timeoutMs })

  if (outcome.timedOut) {
    // Give up on the turn, not the session: an interrupted member is reusable.
    await teamHost.interrupt(runtimeId).catch(() => undefined)
  }

  // The waiter's own markers (`timed out`, `stopped`) are not user-facing;
  // the timeout reaches the status line and the log, so it is worded here.
  const error = outcome.timedOut ? translateNow('team.errors.turnTimedOut') : outcome.error

  return {
    interrupted: outcome.interrupted,
    text: outcome.text,
    timedOut: outcome.timedOut,
    ...(error ? { error } : {})
  }
}

/** Reviewers that can take a prompt right now: idle (not mid-review, not on a
 *  side task — a second prompt to a busy session would steer or queue behind
 *  the turn it is on), bound, and not excluded. */
function freeReviewers(ctx: RunContext, exclude: number[] = []): TeamMember[] {
  const states = getHost().states.get()

  return $teamMembers
    .get()
    .filter(m => m.role === 'reviewer' && m.runtimeId && m.status === 'idle' && !ctx.sideJobs.has(m.index))
    .filter(m => !states[m.runtimeId!]?.busy)
    .filter(m => !exclude.includes(m.index))
}

/** One ranked vote: every idle reviewer ranks `options` in its own order. */
async function holdVote(
  ctx: RunContext,
  round: number,
  options: TeamOption[],
  prompt: (presented: TeamOption[], reviewerName: string) => string,
  exclude: number[] = [],
  /** How the log shows a ranking (labels by default; verdict words for a
   *  completion check, whose A / B mean nothing to the reader). */
  voteText: (ranking: string[]) => string = ranking => ranking.join(' > ')
): Promise<TeamBallot[]> {
  const reviewers = freeReviewers(ctx, exclude)

  const ballots = await Promise.all(
    reviewers.map(async reviewer => {
      const shuffled = shuffleOptionsFor(options, round, reviewer.index)
      patchTeamMember(reviewer.index, { status: 'reviewing' })

      const reply = await memberTurn(
        ctx,
        reviewer.index,
        prompt(shuffled.presented, teamMemberName(reviewer.index)),
        getHost().reviewTimeoutMs
      )

      if (member(reviewer.index)?.status === 'reviewing') {
        patchTeamMember(reviewer.index, { status: 'idle' })
      }

      const invalid: TeamBallot = {
        confidence: 0,
        guidance: '',
        memberIndex: reviewer.index,
        ranking: [],
        reason: '',
        valid: false
      }

      if (!reply || !isLive(ctx)) {
        return invalid
      }

      if (reply.error && !reply.text) {
        log(ctx, { code: 'reviewerFailed', detail: reply.error, kind: 'note', memberIndex: reviewer.index, round, text: '' })

        return invalid
      }

      // A reply cut short (stopped from its pane) is not a vote.
      if (reply.interrupted) {
        log(ctx, { code: 'noVote', kind: 'note', memberIndex: reviewer.index, round, text: '' })

        return invalid
      }

      const vote = parseTeamVote(reply.text, shuffled.presented.map(o => o.label))
      const ranking = unshuffleRanking(vote.ranking, shuffled.toLead)

      if (!vote.found || ranking.length === 0) {
        log(ctx, { code: 'noVote', kind: 'note', memberIndex: reviewer.index, round, text: '' })

        return invalid
      }

      log(ctx, {
        detail: [vote.reason, vote.guidance].filter(Boolean).join('\n\n'),
        kind: 'vote',
        memberIndex: reviewer.index,
        round,
        text: voteText(ranking)
      })

      return {
        confidence: vote.confidence,
        guidance: vote.guidance,
        memberIndex: reviewer.index,
        ranking,
        reason: vote.reason,
        valid: true
      }
    })
  )

  return ballots
}

/** Decide among the lead's options (a one-option result is its own decision). */
async function decide(ctx: RunContext, round: number, result: TeamResult): Promise<null | TeamDecision> {
  const run = $teamRun.get()

  if (!run || !isLive(ctx)) {
    return null
  }

  const options = result.options

  if (options.length === 1) {
    const only = options[0]
    const tally = tallyBallots(options, [])

    return { ballots: [], chosen: only, options, round, summary: result.summary, tally }
  }

  const ballots = await holdVote(ctx, round, options, (presented, name) =>
    buildReviewPrompt(run.goal, result.summary, presented, run.memory, name)
  )

  if (!isLive(ctx)) {
    return null
  }

  const tally = tallyBallots(options, ballots)
  const chosen = options.find(o => o.label === tally.winner) ?? options[0]

  return { ballots, chosen, options, round, summary: result.summary, tally }
}

/** Hand a side task to the least-loaded idle reviewer; its result is
 *  collected (and mini-reviewed) when the lead's next round settles. */
function assignSideTask(ctx: RunContext, round: number, task: string) {
  const run = $teamRun.get()
  const candidates = freeReviewers(ctx).sort((a, b) => a.sideTasksDone - b.sideTasksDone)
  const worker = candidates[0]

  if (!run || !worker) {
    log(ctx, { code: 'sideTaskSkipped', kind: 'note', round, text: task })

    return
  }

  patchTeamMember(worker.index, { status: 'sideTask' })
  log(ctx, { code: 'sideTaskAssigned', kind: 'side', memberIndex: worker.index, round, text: task })

  const job = (async () => {
    const reply = await memberTurn(
      ctx,
      worker.index,
      buildSideTaskPrompt(run.goal, task, run.memory, teamMemberName(worker.index)),
      getHost().turnTimeoutMs
    )

    if (!reply || !isLive(ctx)) {
      return
    }

    patchTeamMember(worker.index, { sideTasksDone: worker.sideTasksDone + 1, status: 'idle' })

    if ((reply.error && !reply.text) || reply.interrupted || !reply.text.trim()) {
      log(ctx, {
        detail: reply.error,
        code: 'sideTaskFailed',
        kind: 'note',
        memberIndex: worker.index,
        round,
        text: task
      })

      return
    }

    const parsed = parseTeamResult(reply.text)
    const summary = parsed.summary || reply.text
    const sideResult: TeamSideResult = { memberIndex: worker.index, summary, task }

    // A result with a real fork gets the same review from whoever is idle —
    // never the worker itself (no self-preference).
    if (parsed.options.length >= 2) {
      const ballots = await holdVote(
        ctx,
        round,
        parsed.options,
        (presented, name) => buildSideReviewPrompt(run.goal, task, summary, presented, name),
        [worker.index]
      )

      if (!isLive(ctx)) {
        return
      }

      const tally = tallyBallots(parsed.options, ballots)

      // Nobody was idle to vote: hand the options to the lead undecided.
      if (tally.validBallots > 0) {
        sideResult.chosen = parsed.options.find(o => o.label === tally.winner) ?? parsed.options[0]
      } else {
        sideResult.summary = `${summary}\n${parsed.options.map(o => `option ${o.label}: ${o.text}`).join('\n')}`
      }
    }

    ctx.sideResults.push(sideResult)
    patchTeamRun(ctx.runId, current => ({
      memory: { ...current.memory, sideResults: [...current.memory.sideResults, sideResult] }
    }))

    log(ctx, {
      detail: sideResult.chosen ? `${sideResult.chosen.label}: ${sideResult.chosen.text}` : undefined,
      kind: 'side',
      memberIndex: worker.index,
      round,
      text: summary
    })
  })().finally(() => {
    ctx.sideJobs.delete(worker.index)
  })

  ctx.sideJobs.set(worker.index, job)
}

function finish(ctx: RunContext, status: 'done' | 'failed' | 'stopped', final: null | string, error: null | string) {
  patchTeamRun(ctx.runId, { endedAt: Date.now(), error, final, status })

  // A side task still running belongs to this run: end it with the run (its
  // await resolves on the abort; the member is interrupted so it idles).
  if (ctx.sideJobs.size > 0) {
    ctx.abort.abort()

    for (const index of ctx.sideJobs.keys()) {
      const runtimeId = member(index)?.runtimeId

      if (runtimeId) {
        void getHost().interrupt(runtimeId).catch(() => undefined)
      }
    }
  }

  for (const seat of $teamMembers.get()) {
    if (seat.status !== 'error') {
      patchTeamMember(seat.index, { status: 'idle' })
    }
  }

  if (context === ctx) {
    context = null
  }

  // The members' sessions now have turns — surface them in the sidebar.
  broadcastSessionsChanged()
}

/**
 * The reviewers' COMPLETION CHECK: when the lead reports done, every free
 * reviewer verifies the result against the goal and votes to accept it or to
 * send the lead back with guidance. Returns the decision to continue on, or
 * null when the result stands (accepted, no usable verdict, send-backs used
 * up, or the run went away). Every held check is recorded as a decision —
 * accepted or not — so the Final seat's brief carries what the reviewers
 * found on their last look, and the log says which way it went.
 */
async function completionCheck(ctx: RunContext, round: number, leadAnswer: string): Promise<null | TeamDecision> {
  const run = $teamRun.get()

  if (!run || !isLive(ctx)) {
    return null
  }

  if (freeReviewers(ctx).length === 0) {
    log(ctx, { code: 'completionSkipped', kind: 'note', round, text: '' })

    return null
  }

  const sendBacksLeft = TEAM_MAX_COMPLETION_PUSHBACKS - ctx.pushbacks
  const options = [...COMPLETION_OPTIONS]

  const ballots = await holdVote(
    ctx,
    round,
    options,
    (presented, name) => buildCompletionReviewPrompt(run.goal, leadAnswer, presented, run.memory, name, sendBacksLeft),
    [],
    ranking => ranking.map(completionVerdict).join(' > ')
  )

  if (!isLive(ctx)) {
    return null
  }

  const tally = tallyBallots(options, ballots)
  const chosen = options.find(o => o.label === tally.winner) ?? options[0]
  const decision: TeamDecision = { ballots, chosen, options, round, summary: clip(leadAnswer, 1600), tally }
  const notDone = chosen.label === COMPLETION_NOT_DONE
  const sendBack = notDone && sendBacksLeft > 0

  patchTeamRun(ctx.runId, current => ({
    memory: { ...current.memory, decisions: [...current.memory.decisions, decision] }
  }))

  log(ctx, {
    code: sendBack
      ? 'completionPushback'
      : tally.validBallots === 0
        ? 'completionNoVerdict'
        : notDone
          ? 'completionExhausted'
          : 'completionAccepted',
    detail: ballots
      .filter(b => b.valid && b.guidance)
      .map(b => `${teamMemberName(b.memberIndex)}: ${b.guidance}`)
      .join('\n\n'),
    kind: 'note',
    round,
    text: ''
  })

  if (!sendBack) {
    return null
  }

  ctx.pushbacks += 1

  return decision
}

/** The Final seat reads the whole run — goal, the lead's closing answer, every
 *  decision and side result — and writes the one answer the team stands
 *  behind; that reply is the run's outcome and the seat stays open for the
 *  user to question it. Anything short of a clean reply (no Final session
 *  because its creation failed, a stop, a timeout, an empty turn) falls back
 *  to the lead's answer, so a run is never worse off for having the seat. */
async function synthesizeFinal(ctx: RunContext, round: number, leadAnswer: string): Promise<string> {
  const run = $teamRun.get()
  const seat = member(TEAM_FINAL_INDEX)

  if (!run || !isLive(ctx)) {
    return leadAnswer
  }

  if (!seat?.runtimeId) {
    log(ctx, { code: 'finalFallback', detail: seat?.error, kind: 'note', memberIndex: TEAM_FINAL_INDEX, round, text: '' })

    return leadAnswer
  }

  patchTeamMember(TEAM_FINAL_INDEX, { status: 'synthesizing' })

  const reply = await memberTurn(
    ctx,
    TEAM_FINAL_INDEX,
    buildFinalSynthesisPrompt(run.goal, run.memory, leadAnswer),
    getHost().turnTimeoutMs
  )

  if (member(TEAM_FINAL_INDEX)?.status === 'synthesizing') {
    patchTeamMember(TEAM_FINAL_INDEX, { status: 'idle' })
  }

  if (!reply || !isLive(ctx)) {
    return leadAnswer
  }

  // Any error on the Final's turn — even after some streamed text — means a
  // possibly truncated synthesis; the lead's complete answer is the safer
  // outcome, and the Final's pane still shows what it managed to write.
  if (reply.error || reply.interrupted || reply.timedOut || !reply.text.trim()) {
    log(ctx, { code: 'finalFallback', detail: reply.error, kind: 'note', memberIndex: TEAM_FINAL_INDEX, round, text: '' })

    return leadAnswer
  }

  return reply.text.trim()
}

async function runLoop(ctx: RunContext) {
  const teamHost = getHost()
  const run = $teamRun.get()

  if (!run || !isLive(ctx)) {
    return
  }

  // The roster the lead is told about is the working crew; the Final seat
  // only speaks once the work is done and is not a teammate to delegate to.
  const roster = {
    members: $teamMembers
      .get()
      .filter(m => m.role !== 'final')
      .map(m => ({ model: m.model, name: teamMemberName(m.index) }))
  }

  let prompt = buildLeadKickoffPrompt(run.goal, roster)
  let lastAnswer = ''
  const capped = hasRoundCap(run.maxRounds)

  for (let round = 1; !capped || round <= run.maxRounds; round += 1) {
    if (!isLive(ctx)) {
      return
    }

    patchTeamRun(ctx.runId, { round, status: 'running' })
    patchTeamMember(0, { status: 'working' })
    log(ctx, { kind: 'round', round, text: '' })

    let reply = await memberTurn(ctx, 0, prompt, teamHost.turnTimeoutMs)

    if (!reply || !isLive(ctx)) {
      return
    }

    if (reply.error && !reply.text) {
      patchTeamMember(0, { error: reply.error, status: 'error' })
      log(ctx, { detail: reply.error, kind: 'error', memberIndex: 0, round, text: '' })
      finish(ctx, 'failed', null, reply.error)

      return
    }

    // The user stopped the lead from its own pane: that is Stop for the team.
    if (reply.interrupted && !reply.timedOut) {
      log(ctx, { code: 'leadInterrupted', kind: 'note', memberIndex: 0, round, text: '' })
      finish(ctx, 'stopped', null, null)

      return
    }

    // The turn settled without a word from the lead — a stale settle or a
    // model that returned nothing. Not an answer; say so rather than guess.
    if (!reply.text.trim()) {
      const reason = reply.error ?? translateNow('team.errors.noReply')
      log(ctx, { detail: reason, kind: 'error', memberIndex: 0, round, text: '' })
      finish(ctx, 'failed', null, reason)

      return
    }

    let result = parseTeamResult(reply.text)

    // No block and no recognizable shape: one repair prompt, then take the
    // plain reply as the answer rather than looping on a model that will not
    // follow the format.
    if (!result.found && reply.text.trim()) {
      log(ctx, { code: 'repair', kind: 'note', memberIndex: 0, round, text: '' })
      const repaired = await memberTurn(ctx, 0, buildRepairPrompt(), teamHost.turnTimeoutMs)

      if (!repaired || !isLive(ctx)) {
        return
      }

      const parsedRepair = parseTeamResult(repaired.text)

      if (parsedRepair.found) {
        // The repair reply is the block alone; the work stays in the first
        // reply, so the answer keeps that work (plus whatever the restated
        // block adds) and the summary falls back to it.
        result = {
          ...parsedRepair,
          answer: [result.answer, parsedRepair.answer].filter(Boolean).join('\n\n'),
          summary: parsedRepair.summary || result.summary
        }

        reply = repaired
      }
    }

    lastAnswer = result.answer || reply.text

    if (result.status === 'done' || result.options.length === 0) {
      patchTeamMember(0, { status: 'idle' })

      // A side task still in flight belongs to this run's answer: let it land
      // (its result joins the notes) before the reviewers check the result
      // and the Final reads them, exactly as the rounds-exhausted path does.
      await Promise.all([...ctx.sideJobs.values()]).catch(() => undefined)

      if (!isLive(ctx)) {
        return
      }

      // The reviewers verify "done" before the team accepts it. Sent back,
      // the lead continues on their guidance as the next round. On a capped
      // run's last round there is no next round, so the cap is the bound
      // and the result stands unchecked (as the wrap-up turn does).
      const pushback = capped && round >= run.maxRounds ? null : await completionCheck(ctx, round, lastAnswer)

      if (!isLive(ctx)) {
        return
      }

      if (pushback) {
        const sideResults = ctx.sideResults.splice(0, ctx.sideResults.length)
        prompt = buildPushbackPrompt(pushback, $teamRun.get()?.memory ?? run.memory, sideResults)

        continue
      }

      const final = await synthesizeFinal(ctx, round, lastAnswer)

      if (!isLive(ctx)) {
        return
      }

      log(ctx, { kind: 'final', round, text: final })
      finish(ctx, 'done', final, null)

      return
    }

    patchTeamMember(0, { status: 'idle' })

    for (const task of result.sideTasks) {
      assignSideTask(ctx, round, task)
    }

    const decision = await decide(ctx, round, result)

    if (!decision || !isLive(ctx)) {
      return
    }

    log(ctx, {
      code: decision.options.length === 1 ? 'single' : decision.tally.decidedBy,
      detail: decision.options.map(o => `${o.label}: ${o.text}`).join('\n'),
      kind: 'decision',
      round,
      text: `${decision.chosen.label}: ${decision.chosen.text}`
    })

    const sideResults = ctx.sideResults.splice(0, ctx.sideResults.length)

    patchTeamRun(ctx.runId, current => ({
      memory: { ...current.memory, decisions: [...current.memory.decisions, decision] }
    }))

    const memory = $teamRun.get()?.memory ?? run.memory
    prompt = buildLeadContinuePrompt(decision, memory, sideResults)
  }

  // Rounds exhausted: let any side job land, then one wrap-up turn.
  await Promise.all([...ctx.sideJobs.values()]).catch(() => undefined)

  if (!isLive(ctx)) {
    return
  }

  const memory = $teamRun.get()?.memory ?? run.memory
  patchTeamMember(0, { status: 'working' })
  log(ctx, { code: 'roundsExhausted', kind: 'note', round: run.maxRounds, text: '' })

  const wrap = await memberTurn(ctx, 0, buildFinalPrompt(memory), teamHost.turnTimeoutMs)

  if (!wrap || !isLive(ctx)) {
    return
  }

  patchTeamMember(0, { status: 'idle' })

  // Stop from the lead's pane during the wrap-up is Stop for the team, as in
  // the rounds — not a cue to write the outcome from half an answer.
  if (wrap.interrupted && !wrap.timedOut) {
    log(ctx, { code: 'leadInterrupted', kind: 'note', memberIndex: 0, round: run.maxRounds, text: '' })
    finish(ctx, 'stopped', null, null)

    return
  }

  const leadAnswer = wrap.text ? parseTeamResult(wrap.text).answer || wrap.text : lastAnswer
  const final = await synthesizeFinal(ctx, run.maxRounds, leadAnswer)

  if (!isLive(ctx)) {
    return
  }

  log(ctx, { kind: 'final', round: run.maxRounds, text: final })
  finish(ctx, 'done', final, wrap.error && !wrap.text ? wrap.error : null)
}

// ---------------------------------------------------------------------------
// Public actions.
// ---------------------------------------------------------------------------

/** Make sure every seat in use has a live session on the configured model.
 *  A seat whose model pick changed is re-created; others are reused. */
async function ensureCrew(ctx: RunContext, goal: string): Promise<TeamMember[]> {
  const config = $teamConfig.get()
  const size = clampTeamSize(config.size)
  const existing = $teamMembers.get()
  const title = goal.trim().slice(0, 48)
  const seats: TeamMember[] = []

  for (let index = 0; index < size; index += 1) {
    const pick = config.members[index] ?? { model: '', provider: '' }
    const current = existing.find(m => m.index === index)
    const samePick = Boolean(current && current.model === pick.model && current.provider === pick.provider)

    if (samePick && current?.runtimeId) {
      seats.push({ ...current, error: undefined, status: 'idle' })
    } else if (samePick && current?.storedSessionId) {
      // The gateway reconnected since the last run: the session is still
      // there, only its runtime binding is gone — resume it (context kept).
      seats.push({ ...current, error: undefined, runtimeId: null, status: 'creating' })
    } else {
      if (current?.runtimeId) {
        void getHost().closeSession(current.runtimeId)
      }

      seats.push({ ...createTeamMember(index, pick.model, pick.provider), status: 'creating' })
    }
  }

  // Seats beyond the new size are retired (the Final seat is not a working
  // seat and has its own lifecycle below).
  for (const retired of existing.filter(m => m.index >= size && m.index !== TEAM_FINAL_INDEX)) {
    if (retired.runtimeId) {
      void getHost().closeSession(retired.runtimeId)
    }
  }

  // The Final-outcome seat: the same reuse rules as a working seat, on the
  // lead's model, created up front so its pane is there from the start. It
  // stays idle until the run ends and it is asked to synthesise.
  const leadPick = config.members[0] ?? { model: '', provider: '' }
  const currentFinal = existing.find(m => m.index === TEAM_FINAL_INDEX)

  const sameFinalPick = Boolean(
    currentFinal && currentFinal.model === leadPick.model && currentFinal.provider === leadPick.provider
  )

  let finalSeat: TeamMember

  if (sameFinalPick && currentFinal?.runtimeId) {
    finalSeat = { ...currentFinal, error: undefined, status: 'idle' }
  } else if (sameFinalPick && currentFinal?.storedSessionId) {
    finalSeat = { ...currentFinal, error: undefined, runtimeId: null, status: 'creating' }
  } else {
    if (currentFinal?.runtimeId) {
      void getHost().closeSession(currentFinal.runtimeId)
    }

    finalSeat = { ...createTeamMember(TEAM_FINAL_INDEX, leadPick.model, leadPick.provider), status: 'creating' }
  }

  const allSeats = [...seats, finalSeat]
  $teamMembers.set(allSeats)

  // A seat bound after the run was reset or stopped underneath us would leak
  // a backend session nobody can see — close it instead of keeping it.
  const bind = (seat: TeamMember, runtimeId: string, storedSessionId: string) => {
    if (!isLive(ctx)) {
      void getHost().closeSession(runtimeId)

      return
    }

    patchTeamMember(seat.index, { runtimeId, status: 'idle', storedSessionId })
  }

  await Promise.all(
    allSeats
      .filter(seat => seat.status === 'creating')
      .map(async seat => {
        try {
          if (seat.storedSessionId) {
            try {
              bind(seat, await getHost().resumeSession(seat.storedSessionId), seat.storedSessionId)

              return
            } catch {
              // Gone (deleted, other profile): fall through to a fresh seat.
            }
          }

          const created = await getHost().createSession(
            seat.index,
            { model: seat.model, provider: seat.provider },
            `Team · ${teamMemberName(seat.index)}${title ? ` · ${title}` : ''}`
          )

          bind(seat, created.runtimeId, created.storedSessionId)
        } catch (error) {
          patchTeamMember(seat.index, { error: errorText(error), status: 'error' })
        }
      })
  )

  // The working crew only: the start checks count the lead and reviewers,
  // and a Final seat that failed to open is not fatal (the lead's answer
  // stands in for it).
  return $teamMembers.get().filter(m => m.role !== 'final')
}

export async function startTeamRun(goal: string): Promise<boolean> {
  const trimmed = goal.trim()

  if (!trimmed || teamRunActive($teamRun.get())) {
    return false
  }

  const run = createTeamRun(trimmed, $teamConfig.get().maxRounds)
  $teamRun.set(run)

  const ctx: RunContext = {
    abort: new AbortController(),
    pushbacks: 0,
    runId: run.id,
    sideJobs: new Map(),
    sideResults: []
  }

  context = ctx

  let crew: TeamMember[]

  try {
    crew = await ensureCrew(ctx, trimmed)
  } catch (error) {
    finish(ctx, 'failed', null, errorText(error))

    return false
  }

  if (!isLive(ctx)) {
    return false
  }

  const lead = crew.find(m => m.index === 0)

  if (!lead?.runtimeId) {
    const reason = lead?.error ?? translateNow('team.errors.leadNotCreated')
    log(ctx, { detail: reason, kind: 'error', memberIndex: 0, round: 0, text: '' })
    finish(ctx, 'failed', null, reason)

    return false
  }

  const failedReviewers = crew.filter(m => m.role === 'reviewer' && !m.runtimeId)

  for (const seat of failedReviewers) {
    log(ctx, { detail: seat.error, kind: 'error', memberIndex: seat.index, round: 0, text: '' })
  }

  if (failedReviewers.length === crew.length - 1) {
    const reason = failedReviewers[0]?.error ?? translateNow('team.errors.noReviewer')
    finish(ctx, 'failed', null, reason)

    return false
  }

  void runLoop(ctx).catch(error => {
    if (isLive(ctx)) {
      notify({ kind: 'error', message: errorText(error), title: translateNow('team.errors.runFailed') })
      finish(ctx, 'failed', null, errorText(error))
    }
  })

  return true
}

/** Stop the run: abort every wait and interrupt members mid-turn. */
export async function stopTeamRun(): Promise<void> {
  const ctx = context
  const run = $teamRun.get()

  if (!ctx || !run || !teamRunActive(run)) {
    return
  }

  patchTeamRun(ctx.runId, { status: 'stopping' })
  ctx.abort.abort()

  const busy = $teamMembers
    .get()
    .filter(m => m.runtimeId && getHost().states.get()[m.runtimeId]?.busy)
    .map(m => m.runtimeId!)

  await Promise.all(busy.map(runtimeId => getHost().interrupt(runtimeId).catch(() => undefined)))
  finish(ctx, 'stopped', null, null)
}

/** Forget the crew: stop any run and close every seat's session, so the
 *  next Start builds a fresh team (new models, clean context). */
export async function resetTeam(): Promise<void> {
  await stopTeamRun()

  const seats = $teamMembers.get()
  $teamMembers.set([])
  $teamRun.set(null)

  await Promise.all(seats.filter(m => m.runtimeId).map(m => getHost().closeSession(m.runtimeId!)))
}

/** A gateway that is no longer open has recycled or dropped every runtime:
 *  unbind the crew (their stored sessions resume on the next Start) and end a
 *  run in flight — its members cannot be heard any more. */
export function onGatewayUnavailable(): void {
  const ctx = context

  if (ctx && teamRunActive($teamRun.get())) {
    ctx.abort.abort()
    finish(ctx, 'failed', null, translateNow('team.errors.disconnected'))
  }

  const members = $teamMembers.get()

  if (members.some(m => m.runtimeId)) {
    $teamMembers.set(members.map(m => ({ ...m, runtimeId: null, status: m.status === 'error' ? 'error' : 'idle' })))
  }
}

$gatewayState.listen(state => {
  if (state === 'closed' || state === 'error') {
    onGatewayUnavailable()
  }
})

// A profile switch moves the live socket to another backend: the crew's
// runtimes are no longer reachable from here (tiles drop their bindings the
// same way), and their stored sessions belong to the profile just left —
// resuming those on the next Start would run that profile's config and
// skills next to any seat re-created on the new one. Forget the crew (the
// sessions stay in history); the next Start builds fresh on the active profile.
$activeGatewayProfile.listen(() => {
  onGatewayUnavailable()
  $teamMembers.set([])
})

/** Test seam: the live run context (abort state), if any. */
export function teamRunContextForTests(): null | { runId: string; aborted: boolean } {
  return context ? { aborted: context.abort.signal.aborted, runId: context.runId } : null
}
