/**
 * TEAM MODE STATE — the desktop-only "several models working as a team"
 * surface (`/team`). Three things live here, each with its own authority:
 *
 *  - `$teamConfig` (persisted, per machine): how many seats, which model
 *    sits in each, and the round cap. Pure UI preference — the user's picks.
 *  - `$teamMembers` (in memory): the live crew — one ordinary backend session
 *    per seat, created lazily on the first Start and REUSED across runs so a
 *    team keeps what it learned (and its cached prompt prefix) between goals.
 *  - `$teamRun` (in memory): the run in progress or just finished — status,
 *    round, log, shared memory, final answer. A run never survives a
 *    restart; its sessions do, as ordinary chats in the sidebar.
 *
 * Nothing here touches the primary chat's atoms: a team member renders from
 * its own `$sessionStates` slice exactly like a session tile does.
 */

import { atom } from 'nanostores'

import { readJson, writeJson } from '@/lib/storage'
import {
  clampTeamRounds,
  clampTeamSize,
  emptyTeamMemory,
  TEAM_DEFAULT_ROUNDS,
  TEAM_MAX_MEMBERS,
  type TeamMemory,
  type TeamRole,
  teamRole
} from '@/lib/team/protocol'

// ---------------------------------------------------------------------------
// Config (persisted).
// ---------------------------------------------------------------------------

export interface TeamMemberConfig {
  model: string
  provider: string
}

export interface TeamConfig {
  /** Seats in use (2–4). `members` always holds TEAM_MAX_MEMBERS entries so a
   *  seat keeps its model pick when the size shrinks and grows back. */
  size: number
  members: TeamMemberConfig[]
  /** Round cap, or TEAM_UNLIMITED_ROUNDS (0, the default) for none. */
  maxRounds: number
}

const CONFIG_KEY = 'robo.desktop.team.config.v1'

const emptyMember = (): TeamMemberConfig => ({ model: '', provider: '' })

export function defaultTeamConfig(): TeamConfig {
  return {
    maxRounds: TEAM_DEFAULT_ROUNDS,
    members: Array.from({ length: TEAM_MAX_MEMBERS }, emptyMember),
    size: 3
  }
}

/** Whatever was persisted → a valid config (missing fields, bad numbers, junk). */
export function normalizeTeamConfig(raw: unknown): TeamConfig {
  const base = defaultTeamConfig()

  if (!raw || typeof raw !== 'object') {
    return base
  }

  const value = raw as Partial<TeamConfig>
  const members = Array.isArray(value.members) ? value.members : []

  return {
    maxRounds: clampTeamRounds(Number(value.maxRounds ?? base.maxRounds)),
    members: base.members.map((fallback, i) => {
      const m = members[i] as Partial<TeamMemberConfig> | undefined

      return {
        model: typeof m?.model === 'string' ? m.model : fallback.model,
        provider: typeof m?.provider === 'string' ? m.provider : fallback.provider
      }
    }),
    size: clampTeamSize(Number(value.size ?? base.size))
  }
}

export const $teamConfig = atom<TeamConfig>(normalizeTeamConfig(readJson<unknown>(CONFIG_KEY)))

function saveConfig(next: TeamConfig) {
  $teamConfig.set(next)
  writeJson(CONFIG_KEY, next)
}

export function setTeamSize(size: number) {
  saveConfig({ ...$teamConfig.get(), size: clampTeamSize(size) })
}

export function setTeamMaxRounds(rounds: number) {
  saveConfig({ ...$teamConfig.get(), maxRounds: clampTeamRounds(rounds) })
}

export function setTeamMemberModel(index: number, selection: TeamMemberConfig) {
  const current = $teamConfig.get()

  if (index < 0 || index >= current.members.length) {
    return
  }

  saveConfig({
    ...current,
    members: current.members.map((m, i) =>
      i === index ? { model: selection.model.trim(), provider: selection.provider.trim() } : m
    )
  })
}

/** Reset the persisted picks (used by tests and the page's "reset" affordance). */
export function resetTeamConfig() {
  saveConfig(defaultTeamConfig())
}

// ---------------------------------------------------------------------------
// Live crew + run (in memory).
// ---------------------------------------------------------------------------

export type TeamMemberStatus = 'creating' | 'error' | 'idle' | 'reviewing' | 'sideTask' | 'synthesizing' | 'working'

export interface TeamMember {
  index: number
  role: TeamRole
  /** The model/provider the session was created with. */
  model: string
  provider: string
  storedSessionId: null | string
  runtimeId: null | string
  status: TeamMemberStatus
  error?: string
  /** Side tasks this member has completed — the controller spreads work to
   *  the least-loaded idle reviewer. */
  sideTasksDone: number
}

export function createTeamMember(index: number, model: string, provider: string): TeamMember {
  return {
    index,
    model,
    provider,
    role: teamRole(index),
    runtimeId: null,
    sideTasksDone: 0,
    status: 'idle',
    storedSessionId: null
  }
}

export const $teamMembers = atom<TeamMember[]>([])

export function patchTeamMember(index: number, patch: Partial<TeamMember>) {
  $teamMembers.set($teamMembers.get().map(m => (m.index === index ? { ...m, ...patch } : m)))
}

export type TeamRunStatus = 'done' | 'failed' | 'running' | 'starting' | 'stopped' | 'stopping'

export type TeamLogKind = 'decision' | 'error' | 'final' | 'note' | 'round' | 'side' | 'vote'

/** Why a line exists, for the page to phrase in the user's language: how a
 *  decision was reached (`borda` | `confidence` | `lead-order` | `no-votes` |
 *  `single`) or which note it is. */
export type TeamLogCode =
  | 'borda'
  | 'completionAccepted'
  | 'completionExhausted'
  | 'completionNoVerdict'
  | 'completionPushback'
  | 'completionSkipped'
  | 'confidence'
  | 'finalFallback'
  | 'lead-order'
  | 'leadInterrupted'
  | 'no-votes'
  | 'noVote'
  | 'repair'
  | 'reviewerFailed'
  | 'roundsExhausted'
  | 'sideTaskAssigned'
  | 'sideTaskFailed'
  | 'sideTaskSkipped'
  | 'single'

export interface TeamLogEntry {
  id: string
  at: number
  kind: TeamLogKind
  round: number
  /** The member this line is about (absent for team-level lines). */
  memberIndex?: number
  code?: TeamLogCode
  /** Model-written content (an option, a ranking, a summary) — never localized. */
  text: string
  /** Secondary text — a reason, an option list, an error — shown smaller. */
  detail?: string
}

export interface TeamRun {
  id: string
  goal: string
  status: TeamRunStatus
  round: number
  maxRounds: number
  memory: TeamMemory
  log: TeamLogEntry[]
  final: null | string
  error: null | string
  startedAt: number
  endedAt: null | number
}

export const $teamRun = atom<null | TeamRun>(null)

let logCounter = 0

export function createTeamRun(goal: string, maxRounds: number): TeamRun {
  return {
    endedAt: null,
    error: null,
    final: null,
    goal: goal.trim(),
    id: `team-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
    log: [],
    maxRounds: clampTeamRounds(maxRounds),
    memory: emptyTeamMemory(goal),
    round: 0,
    startedAt: Date.now(),
    status: 'starting'
  }
}

/** Patch the current run — a no-op when `runId` is not the live run (a
 *  stale continuation after Stop/restart must never write). */
export function patchTeamRun(runId: string, patch: Partial<TeamRun> | ((run: TeamRun) => Partial<TeamRun>)) {
  const current = $teamRun.get()

  if (!current || current.id !== runId) {
    return
  }

  $teamRun.set({ ...current, ...(typeof patch === 'function' ? patch(current) : patch) })
}

export function appendTeamLog(runId: string, entry: Omit<TeamLogEntry, 'at' | 'id'>) {
  patchTeamRun(runId, run => ({
    log: [...run.log, { ...entry, at: Date.now(), id: `log-${(logCounter += 1)}` }]
  }))
}

/** Is a run currently live (anything that can still move)? */
export function teamRunActive(run: null | TeamRun): boolean {
  return run?.status === 'starting' || run?.status === 'running' || run?.status === 'stopping'
}

/** Open the log by default; the user's choice sticks. */
const LOG_OPEN_KEY = 'robo.desktop.team.logOpen.v1'

export const $teamLogOpen = atom<boolean>(readJson<boolean>(LOG_OPEN_KEY) ?? true)

export function setTeamLogOpen(open: boolean) {
  $teamLogOpen.set(open)
  writeJson(LOG_OPEN_KEY, open)
}
