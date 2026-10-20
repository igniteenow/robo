/**
 * TEAM MODE PROTOCOL — the pure, model-agnostic half of desktop Team mode.
 *
 * A team is 2–4 ordinary Robo sessions, each on its own model. One is the
 * LEAD: it works the goal with its full toolset and, whenever it reaches a
 * real fork (or a result worth checking), ends its turn with a small block
 * listing the options it sees. The other members are REVIEWERS: each gets the
 * same options — in a different order, so no position is favored — verifies
 * them independently, and ranks them. The ranking is tallied (Borda count,
 * with first-choice plurality as the human-readable summary), the winner is
 * handed back to the lead together with every reviewer's GUIDANCE — what it
 * missed, what they verified, what to do next — and the lead continues.
 * Reviewers that are idle also pick up SIDE TASKS the lead delegates and
 * bring the result back for the same review. When the lead reports done, the
 * reviewers run a COMPLETION CHECK against the goal and can send it back to
 * work (a bounded number of times) before the Final seat writes the outcome.
 * There is no cap on rounds or on turn time unless the user sets one.
 *
 * The design borrows from the multi-agent literature on purpose:
 *  - Mixture-of-Agents / round-table debate: diverse models reviewing one
 *    another beat any single model — so reviewers use their own tools and are
 *    told to be independent and critical, not to rubber-stamp the lead.
 *  - Self-consistency / majority voting: a ranked vote across models is more
 *    robust than one model's pick; Borda rewards broad second-choice support
 *    over a narrow plurality.
 *  - LLM-as-a-judge bias findings: options are shuffled per reviewer
 *    (position bias), the lead never votes on its own options
 *    (self-preference), reviewers must give a reason (verbosity bias), and a
 *    tie falls to the lead's own ordering only as the last resort.
 *
 * Everything here is deterministic and without side effects: prompt builders,
 * the two block parsers, the shuffle, the tally and the shared-memory digest.
 * The controller (app/team/controller.ts) owns sessions and time.
 */

export type TeamRole = 'final' | 'lead' | 'reviewer'

export type TeamResultStatus = 'continue' | 'done'

export interface TeamOption {
  /** The label the lead used (A, B, C…), normalized to one upper-case letter. */
  label: string
  text: string
}

/** The lead's (or a side-task worker's) structured result. */
export interface TeamResult {
  /** True when a block was found; false means the reply had no block at all
   *  and the fields below are best-effort fallbacks from plain prose. */
  found: boolean
  status: TeamResultStatus
  /** The summary, clipped to a prompt-sized budget — what the notes, the log
   *  lines and the reviewers' briefs carry. */
  summary: string
  /** The same text UNCLIPPED. When the reply is the answer (status done, or
   *  the wrap-up), this is what the Final seat is briefed with and what stands
   *  as the outcome if the Final cannot write one — a thorough closing answer
   *  is routinely longer than the summary budget and must not lose its tail. */
  answer: string
  options: TeamOption[]
  sideTasks: string[]
}

export interface TeamVote {
  found: boolean
  /** Option labels in the reviewer's own (presented) label space, best first. */
  ranking: string[]
  /** 0–1; defaults to 0.5 when absent or unparseable. */
  confidence: number
  reason: string
  /** The reviewer's guidance for the lead — what to do next, what it missed
   *  or got wrong, what the reviewer verified. Empty when none was given. */
  guidance: string
}

export interface TeamBallot {
  /** Reviewer member index. */
  memberIndex: number
  /** Ranking in the LEAD's label space (un-shuffled), best first. */
  ranking: string[]
  confidence: number
  reason: string
  /** See TeamVote.guidance; carried to the lead with the decision. */
  guidance: string
  /** False when the reviewer failed, timed out, or sent no usable vote. */
  valid: boolean
}

export interface TeamTally {
  /** Winning option label in the lead's label space. */
  winner: string
  /** Borda points per label. */
  points: Record<string, number>
  /** First-choice counts per label. */
  firstChoices: Record<string, number>
  /** How the winner was decided. */
  decidedBy: 'borda' | 'confidence' | 'lead-order' | 'no-votes'
  validBallots: number
}

export interface TeamDecision {
  round: number
  summary: string
  options: TeamOption[]
  ballots: TeamBallot[]
  tally: TeamTally
  /** The winning option's text. */
  chosen: TeamOption
}

export interface TeamSideResult {
  memberIndex: number
  task: string
  summary: string
  /** The option the idle reviewers chose for this result, when it had any. */
  chosen?: TeamOption
}

/** The team's shared notebook — what every prompt carries forward. */
export interface TeamMemory {
  goal: string
  decisions: TeamDecision[]
  sideResults: TeamSideResult[]
}

export const TEAM_MIN_MEMBERS = 2
export const TEAM_MAX_MEMBERS = 4
/** `maxRounds` value meaning "no cap": the team works until the lead reports
 *  done and the reviewers agree it is. The default — a complex goal needs as
 *  many rounds as it needs, and Stop is always there. */
export const TEAM_UNLIMITED_ROUNDS = 0
export const TEAM_DEFAULT_ROUNDS = TEAM_UNLIMITED_ROUNDS
export const TEAM_MIN_ROUNDS = 1
export const TEAM_MAX_ROUNDS = 99
/** How many times the reviewers may send a "done" lead back to work before
 *  its answer is accepted as it stands — enough to close real gaps, bounded
 *  so a team that cannot agree still ends. */
export const TEAM_MAX_COMPLETION_PUSHBACKS = 3
/** At most this many options per result — more than four and a vote stops
 *  meaning anything. */
export const TEAM_MAX_OPTIONS = 4
export const TEAM_MAX_SIDE_TASKS = 2

/** The Final-outcome seat is modeled as a member too, but off the grid: a
 *  high, fixed index keeps it clear of the 0..3 working seats and out of every
 *  reviewer scan, so it is created, reused, and chatted-to through exactly the
 *  same machinery without ever being mistaken for a reviewer. */
export const TEAM_FINAL_INDEX = 100

const LABELS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'] as const

const SUMMARY_BUDGET = 1600
const OPTION_BUDGET = 700
const SIDE_TASK_BUDGET = 600
/** The notebook is not trimmed by default: every decision stays in every
 *  prompt, so a long run never loses what it decided early. (A caller can
 *  still pass a budget; the per-entry clips keep each line short.) */
const MEMORY_BUDGET = Number.POSITIVE_INFINITY
const REASON_BUDGET = 500
/** Guidance is the reviewer's working notes for the lead — room for a real
 *  list of gaps, risks and verified facts, not a one-liner. */
const GUIDANCE_BUDGET = 2400
/** The Final seat's detail notes (every reviewer's reason and guidance per
 *  round) are the one rendering that grows with rounds × reviewers, so they
 *  get a budget of their own: generous, but a 50-round run cannot hand the
 *  Final a 200 KB brief. Trimmed oldest-first, like any budgeted notes. */
const FINAL_NOTES_BUDGET = 60_000
/** The lead's closing answer as the Final seat sees it: generous (a detailed
 *  answer is the point) but bounded, so one runaway reply cannot blow up the
 *  Final's brief. */
const FINAL_ANSWER_BUDGET = 16000

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

/** Trim to `max` characters on a word boundary, marking the cut. */
export function clip(text: string, max: number): string {
  const trimmed = text.trim()

  if (trimmed.length <= max) {
    return trimmed
  }

  const cut = trimmed.slice(0, max)
  const space = cut.lastIndexOf(' ')

  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).trimEnd()}…`
}

export function clampTeamSize(size: number): number {
  const n = Number.isFinite(size) ? Math.round(size) : TEAM_MIN_MEMBERS

  return Math.min(TEAM_MAX_MEMBERS, Math.max(TEAM_MIN_MEMBERS, n))
}

/** A round cap, or TEAM_UNLIMITED_ROUNDS (0) for none; junk → the default. */
export function clampTeamRounds(rounds: number): number {
  const n = Number.isFinite(rounds) ? Math.round(rounds) : TEAM_DEFAULT_ROUNDS

  if (n <= TEAM_UNLIMITED_ROUNDS) {
    return TEAM_UNLIMITED_ROUNDS
  }

  return Math.min(TEAM_MAX_ROUNDS, Math.max(TEAM_MIN_ROUNDS, n))
}

/** True when `maxRounds` caps the run (false: unlimited). */
export function hasRoundCap(maxRounds: number): boolean {
  return maxRounds > TEAM_UNLIMITED_ROUNDS
}

export function teamRole(memberIndex: number): TeamRole {
  if (memberIndex === TEAM_FINAL_INDEX) {
    return 'final'
  }

  return memberIndex === 0 ? 'lead' : 'reviewer'
}

/** Human name used in prompts and the log: "Lead", "Reviewer 2", "Final"… */
export function teamMemberName(memberIndex: number): string {
  if (memberIndex === TEAM_FINAL_INDEX) {
    return 'Final'
  }

  return memberIndex === 0 ? 'Lead' : `Reviewer ${memberIndex + 1}`
}

/** A tiny deterministic PRNG (mulberry32) so a reviewer's shuffle is stable
 *  for a given round and tests can pin it. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0

  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)

    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// ---------------------------------------------------------------------------
// Result block: what the lead (and a side-task worker) must end a turn with.
// ---------------------------------------------------------------------------

export const TEAM_RESULT_FENCE = 'team'
export const TEAM_VOTE_FENCE = 'vote'

/** The last fenced block tagged `fence` (```team / ```vote), or null. */
function lastFencedBlock(text: string, fence: string): null | string {
  const re = new RegExp('```[ \\t]*' + fence + '[ \\t]*\\r?\\n([\\s\\S]*?)```', 'gi')
  let match: null | RegExpExecArray = null
  let last: null | string = null

  while ((match = re.exec(text)) !== null) {
    last = match[1]
  }

  return last
}

interface KeyLine {
  key: string
  value: string
}

/** Split block text into `key: value` entries. Inside a fenced block a line
 *  that does not start a known key continues the previous value (multi-line
 *  options); in loose prose it is just prose and is dropped, so the sentence
 *  after an option list never becomes part of the last option. Keys are
 *  normalized to lower case without surrounding spaces. */
function keyLines(block: string, keys: RegExp, continuation: boolean): KeyLine[] {
  const entries: KeyLine[] = []

  for (const raw of block.split(/\r?\n/)) {
    // Bullets, headings and bold markers around a key are presentation, not
    // meaning: `- **Option A:** text` is still option A.
    const line = raw
      .replace(/^\s*(?:[-*•>]|#{1,6})\s+/, '')
      .replace(/^[*_]+/, '')
      .trim()

    if (!line) {
      continue
    }

    const m = keys.exec(line)

    if (m) {
      entries.push({
        key: m[1].toLowerCase().replace(/\s+/g, ' ').trim(),
        value: line
          .slice(m[0].length)
          .replace(/^[*_`]+\s*/, '')
          .trim()
      })
    } else if (continuation && entries.length > 0) {
      const last = entries[entries.length - 1]
      last.value = last.value ? `${last.value}\n${line}` : line
    }
  }

  return entries
}

// `option(?!s\s*[:：])` keeps a prose "Options:" heading from reading as
// option S; the key still needs its colon right after the single label.
const RESULT_KEYS =
  /^(status|summary|answer|result|option(?!s\s*[:：])\s*[A-Za-z0-9]|side\s*task(?:\s*[0-9])?|next)\s*\*{0,2}\s*[:：]\s*/i

const OPTION_KEY = /^option\s*([A-Za-z0-9])$/i
const SIDE_TASK_KEY = /^side task(?:\s*[0-9])?$/i

function normalizeOptionLabel(raw: string, index: number): string {
  const upper = raw.toUpperCase()

  if (/^[A-Z]$/.test(upper)) {
    return upper
  }

  // Numbered options (1, 2, 3) map onto letters so the vote space is uniform.
  const n = Number.parseInt(upper, 10)

  if (Number.isFinite(n) && n >= 1 && n <= LABELS.length) {
    return LABELS[n - 1]
  }

  return LABELS[Math.min(index, LABELS.length - 1)]
}

/**
 * Parse the lead's reply. Looks for the LAST ```team block; without one, it
 * still scans the whole reply for `Option A:` style lines (models often drop
 * the fence but keep the shape) and otherwise treats the reply as a finished
 * answer (status done, summary = the reply's tail).
 */
export function parseTeamResult(reply: string): TeamResult {
  const text = (reply ?? '').trim()
  const block = lastFencedBlock(text, TEAM_RESULT_FENCE)
  const source = block ?? text
  const entries = keyLines(source, RESULT_KEYS, block !== null)
  const options: TeamOption[] = []
  const sideTasks: string[] = []
  let status: null | TeamResultStatus = null
  let summary = ''

  for (const entry of entries) {
    const optionMatch = OPTION_KEY.exec(entry.key)

    if (optionMatch) {
      if (options.length < TEAM_MAX_OPTIONS && entry.value) {
        const label = normalizeOptionLabel(optionMatch[1], options.length)

        if (!options.some(o => o.label === label)) {
          options.push({ label, text: clip(entry.value, OPTION_BUDGET) })
        }
      }
    } else if (SIDE_TASK_KEY.test(entry.key)) {
      if (sideTasks.length < TEAM_MAX_SIDE_TASKS && entry.value) {
        sideTasks.push(clip(entry.value, SIDE_TASK_BUDGET))
      }
    } else if (entry.key === 'status') {
      status = /done|final|finish|complete/i.test(entry.value) ? 'done' : 'continue'
    } else if (entry.key === 'summary' || entry.key === 'answer' || entry.key === 'result') {
      summary = summary ? `${summary}\n${entry.value}` : entry.value
    }
  }

  const found = block !== null || options.length > 0 || status !== null
  // The prose before the block is the work itself (the whole reply when there
  // is no block). The answer keeps all of it, plus the block's summary line
  // when there is one — a done reply is usually a long answer in prose and a
  // short summary in the block, and the Final must see both.
  const prose = block ? text.slice(0, text.lastIndexOf('```' + TEAM_RESULT_FENCE)).trim() : text
  let answer = prose

  if (summary) {
    if (block) {
      answer = prose ? `${prose}\n\n${summary}` : summary
    }
    // Without a block the summary line sits inside the prose already.
  } else {
    // No summary line: the summary keeps the tail of the prose, where a
    // reply's conclusion lives.
    summary = prose.length > SUMMARY_BUDGET ? prose.slice(-SUMMARY_BUDGET).trim() : prose
  }

  if (status === null) {
    // No status line: two or more options is a fork to vote on; anything less
    // reads as a finished answer. (The controller handles a declared
    // `continue` with fewer than two options — a single option is a decision
    // already made, none at all gets one repair prompt.)
    status = options.length >= 2 ? 'continue' : 'done'
  }

  return { answer: answer.trim(), found, options, sideTasks, status, summary: clip(summary, SUMMARY_BUDGET) }
}

// ---------------------------------------------------------------------------
// Vote block: what a reviewer must end a turn with.
// ---------------------------------------------------------------------------

const VOTE_KEYS =
  /^(ranking|rank|order|vote|choice|pick|best|confidence|reason|why|reasons|guidance(?:\s+for\s+the\s+lead)?|advice|suggestions?|next\s+steps?|notes?\s+for\s+the\s+lead)\s*[:：]\s*/i

const GUIDANCE_KEYS = new Set([
  'guidance',
  'guidance for the lead',
  'advice',
  'suggestion',
  'suggestions',
  'next step',
  'next steps',
  'note for the lead',
  'notes for the lead'
])

function parseLabelList(value: string, allowed: readonly string[]): string[] {
  const seen: string[] = []

  for (const token of value.toUpperCase().split(/[\s>,;/→]+/)) {
    const label = token.replace(/^OPTION/, '').replace(/[^A-Z0-9]/g, '')
    const letter = /^[0-9]+$/.test(label) ? (LABELS[Number.parseInt(label, 10) - 1] ?? '') : label

    if (letter && allowed.includes(letter) && !seen.includes(letter)) {
      seen.push(letter)
    }
  }

  return seen
}

function parseConfidence(value: string): null | number {
  const m = /(-?\d+(?:\.\d+)?)\s*(%?)/.exec(value)

  if (!m) {
    return null
  }

  let n = Number.parseFloat(m[1])

  if (m[2] === '%' || n > 1) {
    n = n / 100
  }

  if (!Number.isFinite(n)) {
    return null
  }

  return Math.min(1, Math.max(0, n))
}

/**
 * Parse a reviewer's reply against the labels it was shown. Accepts the
 * ```vote block, or bare `Ranking:` / `Vote:` lines; a lone first choice is a
 * valid (partial) ranking. Labels outside `allowed` are ignored.
 */
export function parseTeamVote(reply: string, allowed: readonly string[]): TeamVote {
  const text = (reply ?? '').trim()
  const block = lastFencedBlock(text, TEAM_VOTE_FENCE)
  const entries = keyLines(block ?? text, VOTE_KEYS, block !== null)
  let ranking: string[] = []
  let confidence: null | number = null
  let reason = ''
  let guidance = ''
  let inGuidance = false

  for (const entry of entries) {
    // Guidance is the last field and runs several lines; once it has
    // started, a line in it that happens to open with another key
    // ("Confidence: high", "Order: do A, then B") is part of the guidance,
    // not a late vote that silently rewrites the ranking or confidence.
    if (inGuidance) {
      guidance = `${guidance}\n${entry.key}: ${entry.value}`

      continue
    }

    if (GUIDANCE_KEYS.has(entry.key)) {
      guidance = entry.value
      inGuidance = true
    } else if (['ranking', 'rank', 'order'].includes(entry.key)) {
      const parsed = parseLabelList(entry.value, allowed)

      if (parsed.length > ranking.length) {
        ranking = parsed
      }
    } else if (['vote', 'choice', 'pick', 'best'].includes(entry.key)) {
      const parsed = parseLabelList(entry.value, allowed)

      if (parsed.length > 0 && ranking.length === 0) {
        ranking = parsed
      }
    } else if (entry.key === 'confidence') {
      confidence = parseConfidence(entry.value)
    } else if (['reason', 'why', 'reasons'].includes(entry.key)) {
      reason = reason ? `${reason}\n${entry.value}` : entry.value
    }
  }

  // Last resort for a reply with no keyed line: a bare "B" / "Option B" at the
  // very end, the way terse models answer.
  if (ranking.length === 0 && !block) {
    const tail = text.split(/\r?\n/).filter(Boolean).slice(-2).join(' ')
    const m = /(?:option\s*)?\b([A-Z])\b\s*[.!]?\s*$/i.exec(tail)

    if (m) {
      ranking = parseLabelList(m[1], allowed)
    }
  }

  return {
    confidence: confidence ?? 0.5,
    found: ranking.length > 0,
    guidance: clip(guidance, GUIDANCE_BUDGET),
    ranking,
    reason: clip(reason, REASON_BUDGET)
  }
}

// ---------------------------------------------------------------------------
// Shuffle (position-bias mitigation) and the tally.
// ---------------------------------------------------------------------------

export interface ShuffledOptions {
  /** The options as presented to this reviewer, relabeled A, B, C… in order. */
  presented: TeamOption[]
  /** Presented label → lead label. */
  toLead: Record<string, string>
}

/**
 * A deterministic per-reviewer permutation of the lead's options, relabeled
 * from A. The seed mixes the round and the reviewer index so every reviewer
 * in a round sees a different order and the same inputs always shuffle the
 * same way (tests, logs).
 */
export function shuffleOptionsFor(options: readonly TeamOption[], round: number, memberIndex: number): ShuffledOptions {
  const order = options.map((_, i) => i)
  const rand = mulberry32(round * 7919 + memberIndex * 104729 + options.length)

  for (let i = order.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rand() * (i + 1))
    const tmp = order[i]
    order[i] = order[j]
    order[j] = tmp
  }

  const presented: TeamOption[] = []
  const toLead: Record<string, string> = {}

  order.forEach((sourceIndex, i) => {
    const label = LABELS[i]
    presented.push({ label, text: options[sourceIndex].text })
    toLead[label] = options[sourceIndex].label
  })

  return { presented, toLead }
}

/** Map a reviewer's ranking (presented labels) back into the lead's labels. */
export function unshuffleRanking(ranking: readonly string[], toLead: Record<string, string>): string[] {
  const out: string[] = []

  for (const label of ranking) {
    const lead = toLead[label]

    if (lead && !out.includes(lead)) {
      out.push(lead)
    }
  }

  return out
}

/**
 * Borda count over valid ballots. With k options a first place is worth k
 * points, second k-1, … unranked options score 0. Ties break on the summed
 * confidence of first choices, then on the lead's own ordering. No valid
 * ballots → the lead's first option (the lead's prior) wins, flagged as such.
 */
export function tallyBallots(options: readonly TeamOption[], ballots: readonly TeamBallot[]): TeamTally {
  const k = options.length
  const points: Record<string, number> = {}
  const firstChoices: Record<string, number> = {}
  const confidenceByFirst: Record<string, number> = {}

  for (const option of options) {
    points[option.label] = 0
    firstChoices[option.label] = 0
    confidenceByFirst[option.label] = 0
  }

  const valid = ballots.filter(b => b.valid && b.ranking.length > 0)

  for (const ballot of valid) {
    ballot.ranking.forEach((label, rank) => {
      if (label in points) {
        points[label] += Math.max(0, k - rank)
      }
    })

    const first = ballot.ranking[0]

    if (first in firstChoices) {
      firstChoices[first] += 1
      confidenceByFirst[first] += ballot.confidence
    }
  }

  if (valid.length === 0 || k === 0) {
    return { decidedBy: 'no-votes', firstChoices, points, validBallots: 0, winner: options[0]?.label ?? 'A' }
  }

  const best = Math.max(...options.map(o => points[o.label]))
  const leaders = options.filter(o => points[o.label] === best)

  if (leaders.length === 1) {
    return { decidedBy: 'borda', firstChoices, points, validBallots: valid.length, winner: leaders[0].label }
  }

  const bestConfidence = Math.max(...leaders.map(o => confidenceByFirst[o.label]))
  const byConfidence = leaders.filter(o => confidenceByFirst[o.label] === bestConfidence)

  if (byConfidence.length === 1) {
    return {
      decidedBy: 'confidence',
      firstChoices,
      points,
      validBallots: valid.length,
      winner: byConfidence[0].label
    }
  }

  return { decidedBy: 'lead-order', firstChoices, points, validBallots: valid.length, winner: byConfidence[0].label }
}

// ---------------------------------------------------------------------------
// Shared memory digest.
// ---------------------------------------------------------------------------

export function emptyTeamMemory(goal: string): TeamMemory {
  return { decisions: [], goal: goal.trim(), sideResults: [] }
}

/**
 * The team's notebook as prompt text, newest last. Untrimmed by default (see
 * MEMORY_BUDGET); given a finite budget it is trimmed from the OLDEST entries
 * so the latest decisions always survive. `detail` adds each reviewer's
 * reason and guidance under its round — for the Final seat's one brief,
 * where the reviewers' findings are part of what it must weigh.
 */
export function renderTeamMemory(memory: TeamMemory, budget: number = MEMORY_BUDGET, detail = false): string {
  const lines: string[] = []

  for (const decision of memory.decisions) {
    const votes = Object.entries(decision.tally.firstChoices)
      .filter(([, n]) => n > 0)
      .map(([label, n]) => `${label}×${n}`)
      .join(' ')

    lines.push(
      `Round ${decision.round}: chose ${decision.chosen.label} — ${clip(decision.chosen.text, 240)}` +
        (votes ? ` (first choices: ${votes})` : ' (no valid votes; lead order)')
    )

    if (detail) {
      for (const ballot of decision.ballots.filter(b => b.valid && (b.reason || b.guidance))) {
        lines.push(
          `  ${teamMemberName(ballot.memberIndex)} (${ballot.ranking.join(' > ')}): ${clip(ballot.reason, 400)}` +
            (ballot.guidance ? `\n    Guidance: ${clip(ballot.guidance, 800)}` : '')
        )
      }
    }
  }

  for (const result of memory.sideResults) {
    lines.push(
      `${teamMemberName(result.memberIndex)} side task "${clip(result.task, 120)}": ${clip(result.summary, 400)}` +
        (result.chosen ? ` → team chose ${result.chosen.label}: ${clip(result.chosen.text, 200)}` : '')
    )
  }

  if (lines.length === 0) {
    return ''
  }

  let text = lines.join('\n')

  while (text.length > budget && lines.length > 1) {
    lines.shift()
    text = `… (older notes trimmed)\n${lines.join('\n')}`
  }

  return text
}

// ---------------------------------------------------------------------------
// Prompts.
// ---------------------------------------------------------------------------

const RESULT_CONTRACT = [
  'End EVERY reply with this block (keep the fence exactly):',
  '```team',
  'status: continue | done',
  'summary: one to three sentences on what you did, found, or built',
  'option A: a concrete next step or candidate answer',
  'option B: a genuinely different one (2–4 options while status is continue)',
  'side task: optional — independent work a teammate can do in parallel',
  '```',
  'Use status: done only when the goal is fully met; then summary IS the final answer and options are not needed.'
].join('\n')

const VOTE_CONTRACT = [
  'End your reply with this block (keep the fence exactly):',
  '```vote',
  'ranking: B > A > C   (ALL options, best first)',
  'confidence: 0.0–1.0',
  'reason: two to four sentences — what you checked and why this order',
  'guidance: your working notes FOR THE LEAD — what it missed or got wrong, the risks ahead, what you verified (with the evidence), and the concrete next steps you recommend; several lines are fine, be specific',
  '```'
].join('\n')

/** The reviewer's standing brief: a senior partner to the lead, not a judge
 *  with a scorecard. The vote picks the direction; the guidance is how the
 *  reviewers carry their share of the work to the lead. */
const REVIEWER_STANCE = [
  'You are not only ranking: you are the lead’s senior partner on this goal and you share the result. Dig into the lead’s work with your tools — read the files it touched, run the project’s tests, re-check the facts and sources, reproduce a risky step in a scratch copy of your own (never in the files the lead is working in) — and put everything you learn in the guidance: mistakes, missing pieces, better approaches, what you verified and how. The lead acts on your guidance next turn, so write it as you would for a colleague you are helping to finish a very hard job.'
].join('\n')

/**
 * Rules every member follows while the team runs. The members are sessions on
 * one backend, so they share one home directory and working tree — and several
 * of them writing the SAME file at once is the one thing that reliably breaks a
 * run. The "could not find … the reference file has been updated by teammates
 * already" error the user hit is exactly two members patching the same skill or
 * memory file in the same moment. These rules hold every member to read-only on
 * shared state and to its own scratch files, and off destructive or background
 * commands, while leaving research and computation unrestricted — so the
 * team can work in parallel without colliding, and without the self-improvement
 * noise that was firing on every seat.
 */
const TEAM_ETIQUETTE = [
  'TEAM RULES (several models are working at the same time in the SAME home directory and working tree — follow these exactly):',
  '- Robo’s own shared state is read-only during the run: do NOT edit, patch, create, or delete skills, memory, or config, and do NOT run any self-improvement or skill-maintenance step. Two members touching one of those files at once corrupts it and fails the turn — leave all of that until after the run.',
  '- Project files: the LEAD edits whatever the goal requires. A reviewer, while reviewing, changes no project file — put findings, test results, or a proposed diff in the reply instead. A side-task worker creates or edits only the files its task names or that it creates itself, never a file the lead is working in. Keep scratch notes in a file named for your role (e.g. "reviewer2-notes.md").',
  '- No destructive, global, or long-lived commands: no system-wide installs, resets, deletes outside your own scratch files, servers, watchers, or background jobs. Reading, searching, analysing, computing, and running the project’s own tests are unrestricted — use them freely.',
  '- Spend every bit of effort on the goal itself: go deep, check your facts against real evidence, and be exact. A thorough, verified, precise answer — better than any single model would give alone — is the entire reason the team exists.'
].join('\n')

export interface TeamRoster {
  /** Member names + models, lead first. */
  members: Array<{ name: string; model: string }>
}

function rosterText(roster: TeamRoster): string {
  return roster.members.map(m => `${m.name}${m.model ? ` (${m.model})` : ''}`).join(', ')
}

export function buildLeadKickoffPrompt(goal: string, roster: TeamRoster): string {
  return [
    `You are the LEAD of a Robo team of ${roster.members.length}: ${rosterText(roster)}.`,
    'You have all your usual tools. Work on the goal below yourself — plan, research, run commands, write files, whatever it takes.',
    'Whenever you reach a real decision point, or produce a result worth checking, STOP and present 2–4 concrete options. The reviewers will verify them independently and vote; you will be told which one won, together with each reviewer’s guidance — their findings, corrections and recommended next steps — then you continue from there.',
    'If some independent piece of work could run in parallel, hand it over as a side task — a reviewer will do it and report back.',
    'Keep each turn focused: one step, one honest summary, real options (not a fake choice). There is no cap on rounds or on how long a turn may take: take the time the goal needs, and only say done when it is truly, verifiably met — the reviewers will check your result against the goal before the team accepts it. Aim for the best possible answer, not merely an acceptable one — that is what the team is for.',
    '',
    `GOAL:\n${goal.trim()}`,
    '',
    TEAM_ETIQUETTE,
    '',
    RESULT_CONTRACT
  ].join('\n')
}

export function buildReviewPrompt(
  goal: string,
  summary: string,
  presented: readonly TeamOption[],
  memory: TeamMemory,
  reviewerName: string
): string {
  const notes = renderTeamMemory(memory)

  return [
    `You are ${reviewerName}, a reviewer on a Robo team working on this goal:\n${goal.trim()}`,
    '',
    `The lead just reported:\n${clip(summary, SUMMARY_BUDGET)}`,
    '',
    'Options on the table:',
    ...presented.map(o => `option ${o.label}: ${o.text}`),
    '',
    'Review them INDEPENDENTLY and critically: check facts, run the tests or look at the files, and judge by what will actually reach the goal — not by length or confidence of wording. If every option is flawed, still rank them, and say what is missing in the reason.',
    REVIEWER_STANCE,
    notes ? `Team notes so far:\n${notes}\n` : '',
    TEAM_ETIQUETTE,
    '',
    VOTE_CONTRACT
  ].join('\n')
}

export function buildLeadContinuePrompt(decision: TeamDecision, memory: TeamMemory, sideResults: readonly TeamSideResult[]): string {
  const votes = decision.ballots
    .filter(b => b.valid)
    .map(b => `- ${teamMemberName(b.memberIndex)}: ${b.ranking.join(' > ')}${b.reason ? ` — ${clip(b.reason, 300)}` : ''}`)

  const guidance = decision.ballots
    .filter(b => b.valid && b.guidance)
    .map(b => `${teamMemberName(b.memberIndex)}:\n${b.guidance}`)

  const results = sideResults.map(
    r =>
      `- ${teamMemberName(r.memberIndex)} finished "${clip(r.task, 120)}": ${clip(r.summary, 800)}` +
      (r.chosen ? `\n  Team chose: ${r.chosen.label} — ${r.chosen.text}` : '')
  )

  // The decision itself heads this prompt; the notes carry the rounds before it.
  const notes = renderTeamMemory({ ...memory, decisions: memory.decisions.filter(d => d !== decision) })

  return [
    `Team decision for round ${decision.round}: option ${decision.chosen.label} — ${decision.chosen.text}`,
    decision.tally.decidedBy === 'no-votes'
      ? '(No reviewer returned a usable vote, so your first option stands.)'
      : `(${decision.tally.validBallots} vote${decision.tally.validBallots === 1 ? '' : 's'}; decided by ${decision.tally.decidedBy === 'borda' ? 'ranked vote' : decision.tally.decidedBy === 'confidence' ? 'confidence tie-break' : 'your ordering, after a tie'}.)`,
    votes.length > 0 ? `Reviewer notes:\n${votes.join('\n')}` : '',
    guidance.length > 0 ? `\nReviewer guidance — your teammates checked your work and this is what they found and recommend:\n${guidance.join('\n\n')}` : '',
    results.length > 0 ? `\nSide-task results back from the team:\n${results.join('\n')}` : '',
    notes ? `\nTeam notes:\n${notes}` : '',
    '',
    'Continue the work from the chosen option. Act on the reviewers’ guidance: fix what they flagged, use what they verified, pick up the next steps they recommend — and say in your summary what you took from it and what you set aside, and why.',
    '',
    TEAM_ETIQUETTE,
    '',
    RESULT_CONTRACT
  ]
    .filter(line => line !== '')
    .join('\n')
}

export function buildSideTaskPrompt(goal: string, task: string, memory: TeamMemory, workerName: string): string {
  const notes = renderTeamMemory(memory)

  return [
    `You are ${workerName} on a Robo team working on this goal:\n${goal.trim()}`,
    '',
    `The lead handed you this side task to do in parallel:\n${task.trim()}`,
    '',
    'Do it with your tools, then report back. If the result involves a real choice, list 2–4 options for the team to vote on; otherwise use status: done with the result in the summary.',
    notes ? `Team notes so far:\n${notes}\n` : '',
    TEAM_ETIQUETTE,
    '',
    RESULT_CONTRACT
  ].join('\n')
}

export function buildRepairPrompt(): string {
  return [
    'Your last reply did not end with the team block, so the team cannot vote.',
    'Reply ONLY with the block now — restate your summary and 2–4 concrete options, or status: done with the final answer in the summary.',
    '',
    RESULT_CONTRACT
  ].join('\n')
}

/** The options the reviewers vote on when the lead reports done, in the
 *  lead's label space: A accepts the result, B sends the lead back with the
 *  reviewers' guidance. */
export const COMPLETION_OPTIONS: readonly TeamOption[] = [
  { label: 'A', text: 'Done — the result meets the goal completely and verifiably; it is accepted as the team’s answer.' },
  { label: 'B', text: 'Not done — something is missing, wrong, or unverified; the lead continues on the reviewers’ guidance.' }
]

/** The first words of a completion option, for log lines ("Not done > Done"). */
export function completionVerdict(label: string): string {
  return COMPLETION_OPTIONS.find(o => o.label === label)?.text.split(' — ')[0] ?? label
}

/** Label of the "send the lead back" completion option. */
export const COMPLETION_NOT_DONE = 'B'

/** Marker every completion-check brief carries, so a test harness (and a
 *  reader of the log) can tell it from an ordinary review. */
export const COMPLETION_CHECK_MARKER = 'COMPLETION CHECK'

/**
 * The reviewers' check when the lead reports done: does the result really
 * meet the goal? Verified with tools, not taken on faith. The vote is a
 * ranked vote like any other (shuffled per reviewer), so no self-vote and no
 * position bias; the guidance is what the lead continues on if sent back.
 */
export function buildCompletionReviewPrompt(
  goal: string,
  leadAnswer: string,
  presented: readonly TeamOption[],
  memory: TeamMemory,
  reviewerName: string,
  /** Send-backs the team may still use, THIS check included: 0 means the
   *  answer is accepted whatever the vote. */
  sendBacksLeft: number
): string {
  const notes = renderTeamMemory(memory)

  const stakes =
    sendBacksLeft <= 0
      ? 'This is the last check: the answer will be accepted after it whatever the vote, so put every remaining gap in the guidance — the Final seat reads it when it writes the outcome.'
      : sendBacksLeft === 1
        ? 'If you send the lead back, the guidance IS the work order: list exactly what is missing or wrong and how to fix it, with what you verified. This is the team’s last send-back — the lead’s next report will be accepted as it stands, so the guidance must be complete.'
        : `If you send the lead back, the guidance IS the work order: list exactly what is missing or wrong and how to fix it, with what you verified. (The team can send the lead back ${sendBacksLeft} more times in this run, counting this check.)`

  return [
    `${COMPLETION_CHECK_MARKER} — you are ${reviewerName}, a reviewer on a Robo team working on this goal:\n${goal.trim()}`,
    '',
    `The lead reports the goal is DONE. Its result:\n${clip(leadAnswer, FINAL_ANSWER_BUDGET)}`,
    '',
    'Check it against the goal, line by line, with your tools: does it do everything the goal asks, is every claim and every change correct, is anything unverified, untested or hand-waved? Then choose:',
    ...presented.map(o => `option ${o.label}: ${o.text}`),
    '',
    stakes,
    REVIEWER_STANCE,
    notes ? `Team notes so far:\n${notes}\n` : '',
    TEAM_ETIQUETTE,
    '',
    VOTE_CONTRACT
  ].join('\n')
}

/**
 * The lead's brief after the reviewers refused to accept its "done": not a
 * choice among its own options (it offered none) but a verdict with a work
 * order — every reviewer's guidance, in full — and the instruction to close
 * the gaps, verify, and report again.
 */
export function buildPushbackPrompt(decision: TeamDecision, memory: TeamMemory, sideResults: readonly TeamSideResult[]): string {
  const valid = decision.ballots.filter(b => b.valid)
  const notDone = valid.filter(b => b.ranking[0] === COMPLETION_NOT_DONE).length

  const guidance = valid
    .filter(b => b.guidance || b.reason)
    .map(b => `${teamMemberName(b.memberIndex)} (${completionVerdict(b.ranking[0] ?? '')}):\n${b.guidance || b.reason}`)

  const results = sideResults.map(
    r =>
      `- ${teamMemberName(r.memberIndex)} finished "${clip(r.task, 120)}": ${clip(r.summary, 800)}` +
      (r.chosen ? `\n  Team chose: ${r.chosen.label} — ${r.chosen.text}` : '')
  )

  const notes = renderTeamMemory({ ...memory, decisions: memory.decisions.filter(d => d !== decision) })

  return [
    `COMPLETION CHECK for round ${decision.round}: the reviewers checked your result against the goal and do NOT accept it as done yet (${notDone} of ${valid.length} said not done).`,
    guidance.length > 0 ? `\nWhat they found and what to do — this is your work order:\n${guidance.join('\n\n')}` : '',
    results.length > 0 ? `\nSide-task results back from the team:\n${results.join('\n')}` : '',
    notes ? `\nTeam notes:\n${notes}` : '',
    '',
    'Continue the work: close every gap they list, verify each fix with your tools, and say in your summary what you changed and what you checked. Report again with status: done when the goal is truly met — or with options if you reach a real fork on the way.',
    '',
    TEAM_ETIQUETTE,
    '',
    RESULT_CONTRACT
  ]
    .filter(line => line !== '')
    .join('\n')
}

export function buildFinalPrompt(memory: TeamMemory): string {
  const notes = renderTeamMemory(memory)

  return [
    'The team has used its rounds. Wrap up now: give the final, complete answer to the goal based on everything decided so far.',
    notes ? `\nTeam notes:\n${notes}\n` : '',
    'End with a ```team block using status: done and the final answer in the summary.'
  ].join('\n')
}

/** The side-task result's own mini-review — the same vote, framed for a
 *  teammate's result rather than the lead's. */
export function buildSideReviewPrompt(
  goal: string,
  task: string,
  summary: string,
  presented: readonly TeamOption[],
  reviewerName: string
): string {
  return [
    `You are ${reviewerName}, a reviewer on a Robo team working on this goal:\n${goal.trim()}`,
    '',
    `A teammate finished the side task "${clip(task, 200)}" and reported:\n${clip(summary, SUMMARY_BUDGET)}`,
    '',
    'Options on the table:',
    ...presented.map(o => `option ${o.label}: ${o.text}`),
    '',
    'Rank them independently and critically — verify with your tools when it helps — and put what you found and recommend in the guidance.',
    TEAM_ETIQUETTE,
    '',
    VOTE_CONTRACT
  ].join('\n')
}

/**
 * The FINAL member's brief. A separate session on the lead's model, created
 * when the run ends, that reads the whole run — the goal, the lead's closing
 * answer, and every decision and side-task result the team recorded — and
 * writes the one answer the team stands behind. Its reply becomes the run's
 * final outcome, and the user can then chat with this same session directly,
 * so it carries the full context forward.
 */
export function buildFinalSynthesisPrompt(goal: string, memory: TeamMemory, leadAnswer: string): string {
  const notes = renderTeamMemory(memory, FINAL_NOTES_BUDGET, true)

  return [
    'You are the FINAL member of a Robo team of different models. The team — a lead and its reviewers — has finished working on the goal below. Your job is to produce the single best, most complete and accurate final answer: the outcome the whole team stands behind.',
    '',
    `GOAL:\n${goal.trim()}`,
    '',
    `The lead’s closing answer:\n${clip(leadAnswer, FINAL_ANSWER_BUDGET)}`,
    notes ? `\nWhat the team decided along the way (each round’s winner, every reviewer’s reason and guidance, plus side-task results):\n${notes}` : '',
    '',
    'Synthesise all of it into one answer: keep what the team got right, fix what the reviewers flagged, fill every gap with the detail and evidence a careful expert would expect, and resolve any remaining disagreement with your own judgement. Verify anything you are unsure of with your tools before you commit to it. Be thorough, precise, and well-structured — this is the answer the user reads and acts on.',
    'Reply with the final answer in plain prose; no team block is needed. After this, the user may message you directly with follow-up questions — answer them from everything the team established.',
    '',
    TEAM_ETIQUETTE
  ].join('\n')
}
