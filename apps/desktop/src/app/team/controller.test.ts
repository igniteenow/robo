import { atom } from 'nanostores'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { ClientSessionState } from '@/app/types'
import { type ChatMessage, chatMessageText, textPart } from '@/lib/chat-messages'
import { createClientSessionState } from '@/lib/chat-runtime'
import { COMPLETION_CHECK_MARKER, TEAM_FINAL_INDEX, TEAM_MAX_COMPLETION_PUSHBACKS } from '@/lib/team/protocol'
import { awaitSessionTurn } from '@/lib/team/turn'
import { $activeGatewayProfile } from '@/store/profile'
import { $sessionStates, type SessionTileDelegate, setSessionTileDelegate } from '@/store/session-states'
import {
  $teamConfig,
  $teamMembers,
  $teamRun,
  resetTeamConfig,
  setTeamMemberModel,
  setTeamSize,
  type TeamLogEntry,
  type TeamMemberConfig
} from '@/store/team'

import {
  completionFromEvent,
  onGatewayUnavailable,
  resetTeam,
  setTeamHost,
  startTeamRun,
  stopTeamRun,
  submitTeamPrompt,
  TEAM_REVIEW_TIMEOUT_MS,
  TEAM_TURN_TIMEOUT_MS,
  type TeamHost,
  teamRunContextForTests
} from './controller'

// ---------------------------------------------------------------------------
// A scripted crew: every seat is a fake session whose reply to each prompt is
// decided by the test. `submit` paints the prompt + busy exactly like the real
// host, then answers on a macrotask so the controller's awaits are real.
// ---------------------------------------------------------------------------

type Responder = (prompt: string, turn: number) => null | string

interface FakeHost extends TeamHost {
  prompts: Array<{ index: number; prompt: string }>
  created: Array<{ config: TeamMemberConfig; index: number; title: string }>
  resumed: string[]
  closed: string[]
  interrupted: string[]
  script: Record<number, Responder>
  settle(runtimeId: string, text: string, extra?: Partial<ChatMessage>): void
  patchState(runtimeId: string, fn: (state: ClientSessionState) => ClientSessionState): void
  runtimeOf(index: number): string
  failCreate?: Set<number>
  failSubmit?: Set<number>
}

const tick = () => new Promise<void>(resolve => setTimeout(resolve, 0))

/** The Final seat, when a test leaves it unscripted, hands the lead's answer
 *  back unchanged — so a run that is not about synthesis ends with the same
 *  `final` it always did, and the brief it received is still the real one. */
const echoLeadAnswer: Responder = prompt => /closing answer:\n([\s\S]*?)\n\n/.exec(prompt)?.[1] ?? 'final'

async function settled(predicate: () => boolean, tries = 200): Promise<void> {
  for (let i = 0; i < tries; i += 1) {
    if (predicate()) {
      return
    }

    await tick()
  }

  throw new Error('condition never met')
}

function makeHost(): FakeHost {
  const $states = atom<Record<string, ClientSessionState>>({})
  const turns = new Map<string, number>()
  const indexByRuntime = new Map<string, number>()

  const patch = (runtimeId: string, fn: (state: ClientSessionState) => ClientSessionState) => {
    const current = $states.get()[runtimeId] ?? createClientSessionState(`stored-${runtimeId}`)
    $states.set({ ...$states.get(), [runtimeId]: fn(current) })
  }

  const host: FakeHost = {
    awaitTurn: (runtimeId, sinceCount, options) => awaitSessionTurn($states, runtimeId, sinceCount, options),
    closed: [],
    closeSession: async runtimeId => {
      host.closed.push(runtimeId)
    },
    created: [],
    createSession: async (index, config, title) => {
      if (host.failCreate?.has(index)) {
        throw new Error(`no session for seat ${index}`)
      }

      host.created.push({ config, index, title })
      const runtimeId = `rt-${index}-${host.created.length}`
      indexByRuntime.set(runtimeId, index)
      patch(runtimeId, state => ({ ...state, model: config.model, provider: config.provider }))

      return { runtimeId, storedSessionId: `stored-${runtimeId}` }
    },
    interrupt: async runtimeId => {
      host.interrupted.push(runtimeId)
      // Like production: the RPC returns at once, the stream settles later.
      await tick()
      patch(runtimeId, state => ({ ...state, busy: false, interrupted: true }))
    },
    interrupted: [],
    messageCount: runtimeId => $states.get()[runtimeId]?.messages.length ?? 0,
    patchState: patch,
    prompts: [],
    resumed: [],
    resumeSession: async storedSessionId => {
      if (storedSessionId.includes('gone')) {
        throw new Error('Session not found')
      }

      host.resumed.push(storedSessionId)
      const index = Number(storedSessionId.split('-')[2])
      const runtimeId = `${storedSessionId.replace('stored-', '')}-resumed`
      indexByRuntime.set(runtimeId, index)
      patch(runtimeId, state => ({ ...state, storedSessionId }))

      return runtimeId
    },
    reviewTimeoutMs: 2000,
    runtimeOf: index => {
      const runtimeId = $teamMembers.get().find(m => m.index === index)?.runtimeId

      if (!runtimeId) {
        throw new Error(`seat ${index} has no runtime`)
      }

      return runtimeId
    },
    script: {},
    settle: (runtimeId, text, extra = {}) => {
      patch(runtimeId, state => ({
        ...state,
        awaitingResponse: false,
        busy: false,
        messages: [...state.messages, { id: `a-${state.messages.length}`, parts: [textPart(text)], role: 'assistant', ...extra }]
      }))
    },
    states: $states,
    submit: async (runtimeId, text) => {
      const index = indexByRuntime.get(runtimeId) ?? -1

      if (host.failSubmit?.has(index)) {
        throw new Error('Robo is at the active session limit (2/2).')
      }

      host.prompts.push({ index, prompt: text })
      patch(runtimeId, state => ({
        ...state,
        awaitingResponse: true,
        busy: true,
        messages: [...state.messages, { id: `u-${state.messages.length}`, parts: [textPart(text)], role: 'user' }]
      }))

      const turn = (turns.get(runtimeId) ?? 0) + 1
      turns.set(runtimeId, turn)
      // Unscripted seats: the Final echoes the lead's answer; a reviewer
      // accepts a completion check (so a run that is not about the check
      // ends as it always did) and otherwise stays silent.
      const responder =
        host.script[index] ??
        (index === TEAM_FINAL_INDEX ? echoLeadAnswer : isCompletionCheck(text) ? acceptDone : undefined)
      const reply = responder?.(text, turn) ?? null

      if (reply !== null) {
        setTimeout(() => host.settle(runtimeId, reply), 0)
      }
    },
    turnTimeoutMs: 2000
  }

  return host
}

const teamBlock = (lines: string[]) => ['```team', ...lines, '```'].join('\n')

const voteBlock = (ranking: string, reason = 'checked', confidence = 0.7, guidance = '') =>
  [
    '```vote',
    `ranking: ${ranking}`,
    `confidence: ${confidence}`,
    `reason: ${reason}`,
    ...(guidance ? [`guidance: ${guidance}`] : []),
    '```'
  ].join('\n')

const isCompletionCheck = (prompt: string) => prompt.startsWith(COMPLETION_CHECK_MARKER)

const presentedOptions = (prompt: string) =>
  [...prompt.matchAll(/^option ([A-Z]): (.*)$/gm)].map(m => ({ label: m[1], text: m[2] }))

/** Rank the options whose text contains `want` first (stable otherwise). */
const rankBy = (prompt: string, want: string) => {
  const options = presentedOptions(prompt)

  return [...options].sort((a, b) => Number(b.text.includes(want)) - Number(a.text.includes(want))).map(o => o.label)
}

/** A completion-check vote that accepts the lead's result. */
const acceptDone: Responder = prompt => voteBlock(rankBy(prompt, 'Done —').join(' > '), 'verified, it is done')

/** A completion-check vote that sends the lead back, with guidance. */
const sendBack =
  (guidance: string): Responder =>
  prompt =>
    voteBlock(rankBy(prompt, 'Not done').join(' > '), 'gaps remain', 0.9, guidance)

/** A reviewer that always prefers the option whose text contains `want` —
 *  and accepts a completion check, like a reviewer with no complaints. */
const prefers =
  (want: string): Responder =>
  prompt =>
    isCompletionCheck(prompt) ? acceptDone(prompt, 0) : voteBlock(rankBy(prompt, want).join(' > '), `${want} is better`)

const logKinds = (log: TeamLogEntry[]) => log.map(entry => entry.kind)

/** Prompts that went to a reviewer seat as a round's review (not the lead,
 *  not the Final, not a completion check). */
const reviewerPrompts = () =>
  host.prompts.filter(p => p.index !== 0 && p.index !== TEAM_FINAL_INDEX && !isCompletionCheck(p.prompt))

/** The completion-check briefs the reviewers got. */
const completionPrompts = () => host.prompts.filter(p => isCompletionCheck(p.prompt))

let host: FakeHost

beforeEach(() => {
  resetTeamConfig()
  setTeamSize(3)
  setTeamMemberModel(0, { model: 'lead-model', provider: 'p1' })
  setTeamMemberModel(1, { model: 'rev-a', provider: 'p2' })
  setTeamMemberModel(2, { model: 'rev-b', provider: 'p3' })
  host = makeHost()
  setTeamHost(host)
})

afterEach(async () => {
  await resetTeam()
  setTeamHost(null)
  $teamMembers.set([])
  $teamRun.set(null)
})

describe('startTeamRun', () => {
  it('creates one session per seat on its own model, lead first, plus the Final seat on the lead’s model', async () => {
    host.script = { 0: () => teamBlock(['status: done', 'summary: trivial']) }

    expect(await startTeamRun('Say hi')).toBe(true)
    await settled(() => $teamRun.get()?.status === 'done')

    expect(host.created.map(c => [c.index, c.config.model, c.config.provider])).toEqual([
      [0, 'lead-model', 'p1'],
      [1, 'rev-a', 'p2'],
      [2, 'rev-b', 'p3'],
      [TEAM_FINAL_INDEX, 'lead-model', 'p1']
    ])
    expect(host.created[0].title).toBe('Team · Lead · Say hi')
    expect(host.created[3].title).toBe('Team · Final · Say hi')
    expect($teamMembers.get().map(m => m.role)).toEqual(['lead', 'reviewer', 'reviewer', 'final'])
    expect($teamMembers.get().every(m => m.runtimeId && m.storedSessionId)).toBe(true)
  })

  it('refuses an empty goal and a second run while one is live', async () => {
    host.script = { 0: () => null }

    expect(await startTeamRun('   ')).toBe(false)
    expect(await startTeamRun('Goal')).toBe(true)
    expect(await startTeamRun('Another')).toBe(false)
    expect($teamRun.get()?.goal).toBe('Goal')
  })

  it('briefs the lead with the goal, the roster and the block contract', async () => {
    host.script = { 0: () => teamBlock(['status: done', 'summary: ok']) }
    await startTeamRun('Write the changelog')
    await settled(() => $teamRun.get()?.status === 'done')

    const kickoff = host.prompts.find(p => p.index === 0)!.prompt
    expect(kickoff).toContain('team of 3: Lead (lead-model), Reviewer 2 (rev-a), Reviewer 3 (rev-b)')
    expect(kickoff).toContain('GOAL:\nWrite the changelog')
    expect(kickoff).toContain('```team')
  })
})

describe('the round loop', () => {
  it('lead proposes → reviewers rank in their own order → the winner comes back to the lead → done', async () => {
    host.script = {
      0: (_prompt, turn) =>
        turn === 1
          ? teamBlock([
              'status: continue',
              'summary: Two ways to store it.',
              'option A: Use SQLite',
              'option B: Use Postgres',
              'option C: Use flat files'
            ])
          : teamBlock(['status: done', 'summary: Shipped with the chosen store.']),
      1: prefers('Postgres'),
      2: prefers('Postgres')
    }

    await startTeamRun('Pick a store')
    await settled(() => $teamRun.get()?.status === 'done')

    const run = $teamRun.get()!
    expect(run.round).toBe(2)
    expect(run.final).toBe('Shipped with the chosen store.')
    // The round's decision, then the accepted completion check (recorded so
    // the Final sees what the reviewers found on their last look).
    expect(run.memory.decisions).toHaveLength(2)
    expect(run.memory.decisions[0].chosen).toEqual({ label: 'B', text: 'Use Postgres' })
    expect(run.memory.decisions[1].chosen.label).toBe('A')
    expect(run.memory.decisions[1].options.map(o => o.label)).toEqual(['A', 'B'])
    expect(run.memory.decisions[0].tally.decidedBy).toBe('borda')
    expect(run.memory.decisions[0].ballots.filter(b => b.valid)).toHaveLength(2)

    // Each reviewer was shown the options relabeled from A in a shuffled order
    // and voted on the labels it saw; the tally still lands on Postgres.
    const reviewPrompts = reviewerPrompts()
    expect(reviewPrompts).toHaveLength(2)

    for (const { prompt } of reviewPrompts) {
      expect(prompt).toContain('option A: ')
      expect(prompt).toContain('Use Postgres')
      expect(prompt).toContain('```vote')
    }

    // The lead's second prompt carries the decision and the reviewers' reasons.
    const continuePrompt = host.prompts.filter(p => p.index === 0)[1].prompt
    expect(continuePrompt).toContain('Team decision for round 1: option B — Use Postgres')
    expect(continuePrompt).toContain('Postgres is better')
    // Round 2's "done" was checked by both reviewers before the Final wrote.
    expect(completionPrompts().map(p => p.index)).toEqual([1, 2])
    expect(logKinds(run.log)).toEqual(['round', 'vote', 'vote', 'decision', 'round', 'vote', 'vote', 'note', 'final'])
    expect(run.log.find(e => e.kind === 'note')?.code).toBe('completionAccepted')
    expect($teamMembers.get().every(m => m.status === 'idle')).toBe(true)
  })

  it('never asks the lead to vote on its own options', async () => {
    host.script = {
      0: (_p, turn) =>
        turn === 1
          ? teamBlock(['status: continue', 'option A: x', 'option B: y'])
          : teamBlock(['status: done', 'summary: fin']),
      1: prefers('y'),
      2: prefers('y')
    }

    await startTeamRun('Goal')
    await settled(() => $teamRun.get()?.status === 'done')

    const leadPrompts = host.prompts.filter(p => p.index === 0).map(p => p.prompt)
    expect(leadPrompts).toHaveLength(2)
    expect(leadPrompts.some(p => p.includes('```vote'))).toBe(false)
  })

  it('keeps moving when a reviewer sends no usable vote, and falls back to the lead order when nobody does', async () => {
    host.script = {
      0: (_p, turn) =>
        turn === 1
          ? teamBlock(['status: continue', 'option A: first', 'option B: second'])
          : teamBlock(['status: done', 'summary: fin']),
      1: () => 'I really cannot decide between these two.',
      2: () => 'Neither, honestly.'
    }

    await startTeamRun('Goal')
    await settled(() => $teamRun.get()?.status === 'done')

    const decision = $teamRun.get()!.memory.decisions[0]
    expect(decision.chosen.label).toBe('A')
    expect(decision.tally.decidedBy).toBe('no-votes')
    expect($teamRun.get()!.log.filter(e => e.code === 'noVote' && e.round === 1)).toHaveLength(2)
    expect(host.prompts.filter(p => p.index === 0)[1].prompt).toContain('No reviewer returned a usable vote')
    // The same prose on the completion check is no vote either: with no
    // usable verdict, the lead's answer stands and the log says why.
    expect($teamRun.get()!.log.filter(e => e.code === 'noVote' && e.round === 2)).toHaveLength(2)
    expect($teamRun.get()!.log.some(e => e.code === 'completionNoVerdict')).toBe(true)
  })

  it('asks for the block once when the lead forgets it, then takes the repaired answer', async () => {
    host.script = {
      0: (_p, turn) => {
        if (turn === 1) {
          return 'I did a bunch of work and here is my prose with no block at all.'
        }

        if (turn === 2) {
          return teamBlock(['status: continue', 'option A: left', 'option B: right'])
        }

        return teamBlock(['status: done', 'summary: fin'])
      },
      1: prefers('right'),
      2: prefers('right')
    }

    await startTeamRun('Goal')
    await settled(() => $teamRun.get()?.status === 'done')

    const leadPrompts = host.prompts.filter(p => p.index === 0).map(p => p.prompt)
    expect(leadPrompts[1]).toContain('did not end with the team block')
    expect($teamRun.get()!.log.some(e => e.code === 'repair')).toBe(true)
    expect($teamRun.get()!.memory.decisions[0].chosen.text).toBe('right')
  })

  it('a plain reply that is repaired into a done block keeps its prose as the answer', async () => {
    host.script = {
      0: (_p, turn) =>
        turn === 1 ? 'Full write-up of the work, in prose, with no block.' : teamBlock(['status: done', 'summary: fin'])
    }

    await startTeamRun('Goal')
    await settled(() => $teamRun.get()?.status === 'done')

    // The Final is briefed with the work AND the restated summary; the
    // unscripted Final echoes the first paragraph back, so that is the final.
    const brief = host.prompts.find(p => p.index === TEAM_FINAL_INDEX)!.prompt
    expect(brief).toContain('closing answer:\nFull write-up of the work, in prose, with no block.\n\nfin')
    expect($teamRun.get()!.final).toBe('Full write-up of the work, in prose, with no block.')
  })

  it('treats a plain answer with no options as finished', async () => {
    host.script = { 0: (_p, turn) => (turn === 1 ? 'Paris is the capital of France.' : 'Paris is the capital of France.') }

    await startTeamRun('Capital of France?')
    await settled(() => $teamRun.get()?.status === 'done')

    expect($teamRun.get()!.final).toBe('Paris is the capital of France.')
    expect(reviewerPrompts()).toHaveLength(0)
  })

  it('a single option is a decision already made — no vote, the lead continues', async () => {
    host.script = {
      0: (_p, turn) =>
        turn === 1
          ? teamBlock(['status: continue', 'summary: one road', 'option A: keep going'])
          : teamBlock(['status: done', 'summary: fin']),
      1: () => 'should not be asked',
      2: () => 'should not be asked'
    }

    await startTeamRun('Goal')
    await settled(() => $teamRun.get()?.status === 'done')

    expect(reviewerPrompts()).toHaveLength(0)
    expect($teamRun.get()!.log.find(e => e.kind === 'decision')?.code).toBe('single')
  })

  it('stops after maxRounds with one wrap-up turn for the final answer', async () => {
    $teamConfig.set({ ...$teamConfig.get(), maxRounds: 2 })
    host.script = {
      0: (prompt, turn) =>
        prompt.includes('Wrap up now')
          ? teamBlock(['status: done', 'summary: Final after cap.'])
          : teamBlock(['status: continue', `summary: round ${turn}`, 'option A: a', 'option B: b']),
      1: prefers('a'),
      2: prefers('b')
    }

    await startTeamRun('Endless')
    await settled(() => $teamRun.get()?.status === 'done')

    const run = $teamRun.get()!
    expect(run.round).toBe(2)
    expect(run.memory.decisions).toHaveLength(2)
    expect(run.final).toBe('Final after cap.')
    expect(host.prompts.filter(p => p.index === 0)).toHaveLength(3)
    expect(run.log.some(e => e.code === 'roundsExhausted')).toBe(true)
  })
})

describe('the completion check', () => {
  it('sends a "done" lead back to work with the reviewers’ guidance, then accepts the reworked result', async () => {
    host.script = {
      0: (_p, turn) =>
        turn === 1
          ? teamBlock(['status: done', 'summary: Built the importer.'])
          : teamBlock(['status: done', 'summary: Built the importer, with the retry path and its tests.']),
      1: (prompt, turn) =>
        turn === 1 ? sendBack('The retry path is missing: add it and cover it with a test.')(prompt, turn) : acceptDone(prompt, turn),
      2: prefers('Done —')
    }

    await startTeamRun('Build the importer')
    await settled(() => $teamRun.get()?.status === 'done')

    const run = $teamRun.get()!
    // Reviewer 2 said not done, reviewer 3 said done: a tie on points, broken
    // by confidence (0.9 over 0.7) — the lead was sent back once; the second
    // check accepted, and both are on record.
    expect(run.memory.decisions).toHaveLength(2)
    expect(run.memory.decisions[0].chosen.label).toBe('B')
    expect(run.memory.decisions[0].tally.decidedBy).toBe('confidence')
    expect(run.memory.decisions[1].chosen.label).toBe('A')

    // The lead's second brief is a work order, not a choice among options it
    // never offered.
    const leadPrompts = host.prompts.filter(p => p.index === 0).map(p => p.prompt)
    expect(leadPrompts).toHaveLength(2)
    expect(leadPrompts[1]).toContain('COMPLETION CHECK for round 1')
    expect(leadPrompts[1]).toContain('do NOT accept it as done yet (1 of 2 said not done)')
    expect(leadPrompts[1]).toContain('Reviewer 2 (Not done):\nThe retry path is missing: add it and cover it with a test.')
    expect(leadPrompts[1]).toContain('close every gap they list')
    expect(leadPrompts[1]).not.toContain('Team decision for round')

    expect(run.round).toBe(2)
    expect(run.final).toBe('Built the importer, with the retry path and its tests.')
    expect(run.log.filter(e => e.kind === 'note').map(e => e.code)).toEqual(['completionPushback', 'completionAccepted'])
    expect(run.log.find(e => e.code === 'completionPushback')?.detail).toContain('Reviewer 2: The retry path is missing')
    // The vote lines read as verdicts, not as bare labels.
    expect(run.log.filter(e => e.kind === 'vote').map(e => e.text)).toEqual(['Not done > Done', 'Done > Not done', 'Done > Not done', 'Done > Not done'])
    // The completion briefs carried the lead's result and the send-backs left.
    expect(completionPrompts()[0].prompt).toContain('Its result:\nBuilt the importer.')
    expect(completionPrompts()[0].prompt).toContain(`send the lead back ${TEAM_MAX_COMPLETION_PUSHBACKS} more times in this run`)
  })

  it('accepts the result after the pushbacks are used up, so a team that cannot agree still ends', async () => {
    host.script = {
      0: () => teamBlock(['status: done', 'summary: Good enough.']),
      1: sendBack('still not there'),
      2: sendBack('still not there')
    }

    await startTeamRun('Hard goal')
    await settled(() => $teamRun.get()?.status === 'done', 400)

    const run = $teamRun.get()!
    expect(host.prompts.filter(p => p.index === 0)).toHaveLength(1 + TEAM_MAX_COMPLETION_PUSHBACKS)
    expect(run.log.filter(e => e.code === 'completionPushback')).toHaveLength(TEAM_MAX_COMPLETION_PUSHBACKS)
    // The fourth check still said not done, but the send-backs were used up:
    // the log says so rather than claiming a verification.
    expect(run.log.filter(e => e.code === 'completionExhausted')).toHaveLength(1)
    expect(run.log.filter(e => e.code === 'completionAccepted')).toHaveLength(0)
    expect(run.final).toBe('Good enough.')

    // Each brief told the reviewers where they stood: 3 send-backs left
    // (counting that check), then 2, then the last send-back, then the last
    // check — and the lead's briefs carried every pushback's guidance.
    const briefs = completionPrompts().map(p => p.prompt)
    expect(briefs.filter(b => b.includes('3 more times in this run'))).toHaveLength(2)
    expect(briefs.filter(b => b.includes('2 more times in this run'))).toHaveLength(2)
    expect(briefs.filter(b => b.includes('the team’s last send-back'))).toHaveLength(2)
    expect(briefs.filter(b => b.includes('This is the last check'))).toHaveLength(2)
    expect(briefs[briefs.length - 1]).toContain('This is the last check')
    // Every check is on record, so the Final's brief carries the last look.
    expect(run.memory.decisions).toHaveLength(TEAM_MAX_COMPLETION_PUSHBACKS + 1)
    const finalBrief = host.prompts.find(p => p.index === TEAM_FINAL_INDEX)!.prompt
    expect(finalBrief).toContain('Guidance: still not there')
  })

  it('is not held on a capped run’s last round — the cap is the bound there', async () => {
    $teamConfig.set({ ...$teamConfig.get(), maxRounds: 2 })
    host.script = {
      0: (_p, turn) =>
        turn === 1
          ? teamBlock(['status: continue', 'option A: a', 'option B: b'])
          : teamBlock(['status: done', 'summary: Done on the last round.']),
      1: sendBack('would have sent it back'),
      2: sendBack('would have sent it back')
    }

    await startTeamRun('Capped')
    await settled(() => $teamRun.get()?.status === 'done')

    expect(completionPrompts()).toHaveLength(0)
    expect($teamRun.get()!.round).toBe(2)
    expect($teamRun.get()!.final).toBe('Done on the last round.')
    expect(host.prompts.filter(p => p.index === 0)).toHaveLength(2)
  })

  it('no usable verdict leaves the lead’s answer standing, and the log says so', async () => {
    host.script = {
      0: () => teamBlock(['status: done', 'summary: fin']),
      1: () => 'Hmm, I am not sure what to say here.',
      2: () => 'Neither am I.'
    }

    await startTeamRun('Goal')
    await settled(() => $teamRun.get()?.status === 'done')

    expect($teamRun.get()!.log.filter(e => e.kind === 'note').map(e => e.code)).toEqual(['noVote', 'noVote', 'completionNoVerdict'])
    expect($teamRun.get()!.final).toBe('fin')
  })

  it('a plain reply with no block is checked too, and the Final is briefed only after the check', async () => {
    host.script = {
      0: () => 'Paris is the capital of France.',
      1: acceptDone,
      2: acceptDone
    }

    await startTeamRun('Capital of France?')
    await settled(() => $teamRun.get()?.status === 'done')

    expect(completionPrompts()).toHaveLength(2)
    expect(host.prompts[host.prompts.length - 1].index).toBe(TEAM_FINAL_INDEX)
    expect($teamRun.get()!.final).toBe('Paris is the capital of France.')
  })

  it('skips the check when no reviewer is free to do it', async () => {
    // One reviewer could not open; the other does the check on the first
    // run, and is busy with the user on the second — nobody is free then.
    host.failCreate = new Set([2])
    host.script = { 0: () => teamBlock(['status: done', 'summary: alone']) }

    await startTeamRun('Warm up')
    await settled(() => $teamRun.get()?.status === 'done')
    expect(completionPrompts().map(p => p.index)).toEqual([1])

    host.patchState(host.runtimeOf(1), state => ({ ...state, busy: true }))
    await startTeamRun('Second')
    await settled(() => $teamRun.get()?.status === 'done')
    expect(completionPrompts()).toHaveLength(1)
    expect($teamRun.get()!.log.filter(e => e.kind === 'note').map(e => e.code)).toEqual(['completionSkipped'])
    expect($teamRun.get()!.final).toBe('alone')
  })
})

describe('unlimited rounds and turns', () => {
  it('has no round cap by default: a long run continues past the old cap and ends only when done', async () => {
    expect($teamConfig.get().maxRounds).toBe(0)
    host.script = {
      0: (_p, turn) =>
        turn <= 15
          ? teamBlock(['status: continue', `summary: step ${turn}`, 'option A: a', 'option B: b'])
          : teamBlock(['status: done', 'summary: Finished after 16 turns.']),
      1: prefers('a'),
      2: prefers('b')
    }

    await startTeamRun('Long haul')
    await settled(() => $teamRun.get()?.status === 'done', 2000)

    const run = $teamRun.get()!
    expect(run.round).toBe(16)
    expect(run.memory.decisions).toHaveLength(16)
    expect(run.final).toBe('Finished after 16 turns.')
    expect(run.log.some(e => e.code === 'roundsExhausted')).toBe(false)
    // Nothing was trimmed: the Final's brief carries the very first round.
    const brief = host.prompts.find(p => p.index === TEAM_FINAL_INDEX)!.prompt
    expect(brief).toContain('Round 1: chose')
    expect(brief).toContain('Round 15: chose')
    expect(brief).not.toContain('older notes trimmed')
  })

  it('puts no clock on a turn by default', () => {
    expect(TEAM_TURN_TIMEOUT_MS).toBe(Number.POSITIVE_INFINITY)
    expect(TEAM_REVIEW_TIMEOUT_MS).toBe(Number.POSITIVE_INFINITY)
  })
})

describe('side tasks', () => {
  it('hands a side task to an idle reviewer, who skips that round’s vote and reports back for the next brief', async () => {
    let sideRuntime = ''

    host.script = {
      0: (_p, turn) => {
        if (turn === 1) {
          return teamBlock([
            'status: continue',
            'summary: main work',
            'option A: a',
            'option B: b',
            'side task: Benchmark the reads'
          ])
        }

        if (turn === 2) {
          return null // parked until the side task has reported
        }

        return teamBlock(['status: done', 'summary: fin'])
      },
      1: prompt => {
        if (prompt.includes('side task to do in parallel')) {
          sideRuntime = host.runtimeOf(1)

          return null // stays busy until the test settles it
        }

        return prefers('a')(prompt, 0)
      },
      2: prefers('b')
    }

    await startTeamRun('Goal')
    // Round 1 vote happens with reviewer 3 only (reviewer 2 is on the side task).
    await settled(() => $teamRun.get()?.log.some(e => e.kind === 'decision') ?? false)

    const run = $teamRun.get()!
    expect(run.log.find(e => e.code === 'sideTaskAssigned')?.memberIndex).toBe(1)
    expect($teamMembers.get()[1].status).toBe('sideTask')
    expect(run.memory.decisions[0].ballots.filter(b => b.valid).map(b => b.memberIndex)).toEqual([2])

    // The lead is already on round 2 while the side task is still running.
    await settled(() => host.prompts.filter(p => p.index === 0).length === 2)
    host.settle(sideRuntime, teamBlock(['status: done', 'summary: Reads take 3ms.']))
    await settled(() => ($teamRun.get()?.memory.sideResults.length ?? 0) === 1)

    expect($teamMembers.get()[1].sideTasksDone).toBe(1)
    expect($teamMembers.get()[1].status).toBe('idle')
    expect($teamRun.get()!.memory.sideResults).toEqual([
      { memberIndex: 1, summary: 'Reads take 3ms.', task: 'Benchmark the reads' }
    ])

    // Release the lead: its next brief carries the result; both reviewers vote now.
    host.settle(host.runtimeOf(0), teamBlock(['status: continue', 'option A: c', 'option B: d']))
    await settled(() => $teamRun.get()?.status === 'done')

    const briefs = host.prompts.filter(p => p.index === 0).map(p => p.prompt)
    expect(briefs[2]).toContain('Reviewer 2 finished "Benchmark the reads": Reads take 3ms.')
    expect($teamRun.get()!.memory.decisions[1].ballots.filter(b => b.valid).map(b => b.memberIndex)).toEqual([1, 2])
  })

  it('a run that ends while a side task is still running lets it land (or time out) before the outcome is written', async () => {
    // The side worker never answers: its turn times out (short, for the
    // test), it is interrupted, and only then is the Final briefed — so a
    // side result that does land in time reaches the outcome.
    host.turnTimeoutMs = 200
    host.script = {
      0: (_p, turn) =>
        turn === 1
          ? teamBlock(['status: continue', 'option A: a', 'option B: b', 'side task: Long benchmark'])
          : teamBlock(['status: done', 'summary: fin']),
      1: prompt => (prompt.includes('side task to do in parallel') ? null : prefers('a')(prompt, 0)),
      2: prefers('b')
    }

    await startTeamRun('Goal')
    await settled(() => $teamRun.get()?.status === 'done', 2000)

    expect(host.interrupted).toEqual([host.runtimeOf(1)])
    expect($teamRun.get()!.memory.sideResults).toEqual([])
    expect($teamRun.get()!.log.some(e => e.code === 'sideTaskFailed')).toBe(true)
    expect($teamMembers.get()[1].status).toBe('idle')
    expect(host.prompts[host.prompts.length - 1].index).toBe(TEAM_FINAL_INDEX)
    expect($teamRun.get()!.final).toBe('fin')
  })

  it('a side result with options is reviewed by the other idle reviewers, never its author', async () => {
    let sideRuntime = ''

    host.script = {
      0: (_p, turn) => {
        if (turn === 1) {
          return teamBlock(['status: continue', 'option A: a', 'option B: b', 'side task: Compare libs'])
        }

        if (turn === 2) {
          return null // park the lead so the side job finishes within round 2
        }

        return teamBlock(['status: done', 'summary: fin'])
      },
      1: prompt => {
        if (prompt.includes('side task to do in parallel')) {
          sideRuntime = host.runtimeOf(1)

          return null
        }

        return prefers('a')(prompt, 0)
      },
      2: prompt => (prompt.includes('finished the side task') ? prefers('lib Y')(prompt, 0) : prefers('a')(prompt, 0))
    }

    await startTeamRun('Goal')
    await settled(() => host.prompts.filter(p => p.index === 0).length === 2)

    host.settle(sideRuntime, teamBlock(['status: continue', 'summary: Two libs.', 'option A: lib X', 'option B: lib Y']))
    await settled(() => ($teamRun.get()?.memory.sideResults.length ?? 0) === 1)

    const sideResult = $teamRun.get()!.memory.sideResults[0]
    expect(sideResult.chosen?.text).toBe('lib Y')

    const sideReviewPrompts = host.prompts.filter(p => p.prompt.includes('finished the side task'))
    expect(sideReviewPrompts.map(p => p.index)).toEqual([2])

    // Release the parked lead; its next brief carries the side result.
    host.settle(host.runtimeOf(0), teamBlock(['status: continue', 'option A: c', 'option B: d']))
    await settled(() => host.prompts.filter(p => p.index === 0).length === 3)
    expect(host.prompts.filter(p => p.index === 0)[2].prompt).toContain('finished "Compare libs": Two libs.')
    expect(host.prompts.filter(p => p.index === 0)[2].prompt).toContain('Team chose: B — lib Y')
  })
})

describe('members the user is talking to', () => {
  it('waits for a member’s own turn to finish before sending it a team prompt', async () => {
    host.script = {
      0: () => teamBlock(['status: done', 'summary: fin'])
    }

    // Open the crew once so the lead has a session, then put it mid-turn as
    // if the user had typed into its pane.
    await startTeamRun('Warm up')
    await settled(() => $teamRun.get()?.status === 'done')
    const lead = host.runtimeOf(0)
    host.patchState(lead, state => ({ ...state, busy: true }))

    const leadBriefs = () => host.prompts.filter(p => p.index === 0 && p.prompt.includes('GOAL:\nReal goal'))
    const started = startTeamRun('Real goal')
    await tick()
    await tick()
    expect(leadBriefs()).toHaveLength(0)

    host.settle(lead, 'the user’s own reply')
    await started
    await settled(() => $teamRun.get()?.status === 'done')

    expect(leadBriefs()).toHaveLength(1)
    expect($teamRun.get()!.final).toBe('fin')
  })

  it('a reviewer busy with the user is left out of that round’s vote', async () => {
    host.script = {
      0: (_p, turn) =>
        turn === 1
          ? teamBlock(['status: continue', 'option A: a', 'option B: b'])
          : teamBlock(['status: done', 'summary: fin']),
      1: prefers('a'),
      2: prefers('b')
    }

    await startTeamRun('Warm up')
    await settled(() => host.prompts.length === 1)
    host.patchState(host.runtimeOf(1), state => ({ ...state, busy: true }))
    await settled(() => $teamRun.get()?.status === 'done')

    expect($teamRun.get()!.memory.decisions[0].ballots.filter(b => b.valid).map(b => b.memberIndex)).toEqual([2])
    expect(host.prompts.filter(p => p.index === 1)).toHaveLength(0)
  })
})

describe('failures and stop', () => {
  it('fails the run when the lead errors, keeping the reason', async () => {
    host.script = {
      0: () => null
    }

    await startTeamRun('Goal')
    host.settle(host.runtimeOf(0), '', { error: 'Provider rejected the request' })
    await settled(() => $teamRun.get()?.status === 'failed')

    expect($teamRun.get()!.error).toBe('Provider rejected the request')
    expect($teamMembers.get()[0].status).toBe('error')
  })

  it('fails to start when the lead session cannot be created, but tolerates a missing reviewer', async () => {
    host.failCreate = new Set([0])
    expect(await startTeamRun('Goal')).toBe(false)
    expect($teamRun.get()!.status).toBe('failed')
    expect($teamRun.get()!.error).toBe('no session for seat 0')

    await resetTeam()
    host.failCreate = new Set([2])
    host.script = {
      0: (_p, turn) =>
        turn === 1
          ? teamBlock(['status: continue', 'option A: a', 'option B: b'])
          : teamBlock(['status: done', 'summary: fin']),
      1: prefers('b')
    }

    expect(await startTeamRun('Goal')).toBe(true)
    await settled(() => $teamRun.get()?.status === 'done')
    expect($teamRun.get()!.memory.decisions[0].ballots.filter(b => b.valid).map(b => b.memberIndex)).toEqual([1])
    expect($teamMembers.get()[2].status).toBe('error')
  })

  it('a rejected submit surfaces as the run error', async () => {
    host.failSubmit = new Set([0])
    await startTeamRun('Goal')
    await settled(() => $teamRun.get()?.status === 'failed')
    expect($teamRun.get()!.error).toContain('active session limit')
  })

  it('a timed-out reviewer is interrupted and skipped; a timed-out lead fails the run', async () => {
    host.reviewTimeoutMs = 20
    host.turnTimeoutMs = 20
    host.script = {
      0: (_p, turn) =>
        turn === 1
          ? teamBlock(['status: continue', 'option A: a', 'option B: b'])
          : teamBlock(['status: done', 'summary: fin']),
      1: () => null,
      2: prefers('b')
    }

    await startTeamRun('Goal')
    await settled(() => $teamRun.get()?.status === 'done')

    // Skipped (and interrupted) on the round's vote and again on the completion check.
    expect(host.interrupted).toEqual([host.runtimeOf(1), host.runtimeOf(1)])
    expect($teamRun.get()!.memory.decisions[0].ballots.filter(b => b.valid).map(b => b.memberIndex)).toEqual([2])

    await resetTeam()
    host.script = { 0: () => null }
    await startTeamRun('Goal')
    await settled(() => $teamRun.get()?.status === 'failed')
    expect($teamRun.get()!.error).toBe('No reply in time')
  })

  it('stopping the lead from its own pane stops the run', async () => {
    host.script = { 0: () => null }
    await startTeamRun('Goal')
    await settled(() => host.prompts.length === 1)

    // The pane's Stop: the stream marks the turn interrupted and idle.
    await host.interrupt(host.runtimeOf(0))
    await settled(() => $teamRun.get()?.status === 'stopped')

    expect($teamRun.get()!.log.some(e => e.code === 'leadInterrupted')).toBe(true)
    expect(teamRunContextForTests()).toBeNull()
  })

  it('Stop aborts the waits, interrupts busy members and marks the run stopped', async () => {
    host.script = { 0: () => null }
    await startTeamRun('Goal')
    await settled(() => host.prompts.length === 1)

    expect(teamRunContextForTests()?.aborted).toBe(false)
    await stopTeamRun()

    expect($teamRun.get()!.status).toBe('stopped')
    expect(host.interrupted).toEqual([host.runtimeOf(0)])
    expect(teamRunContextForTests()).toBeNull()

    // A late reply from the stopped lead must not revive the run.
    host.settle(host.runtimeOf(0), teamBlock(['status: continue', 'option A: a', 'option B: b']))
    await tick()
    await tick()
    expect($teamRun.get()!.status).toBe('stopped')
    expect(host.prompts).toHaveLength(1)
  })

  it('reuses the crew across runs and rebuilds only the seats whose model changed', async () => {
    host.script = { 0: () => teamBlock(['status: done', 'summary: one']) }
    await startTeamRun('First')
    await settled(() => $teamRun.get()?.status === 'done')
    const firstCrew = $teamMembers.get().map(m => m.runtimeId)

    setTeamMemberModel(2, { model: 'rev-c', provider: 'p3' })
    await startTeamRun('Second')
    await settled(() => $teamRun.get()?.status === 'done')

    const secondCrew = $teamMembers.get().map(m => m.runtimeId)
    expect(secondCrew[0]).toBe(firstCrew[0])
    expect(secondCrew[1]).toBe(firstCrew[1])
    expect(secondCrew[2]).not.toBe(firstCrew[2])
    // The Final seat follows the lead's pick, which did not change: reused.
    expect(secondCrew[3]).toBe(firstCrew[3])
    expect(host.closed).toEqual([firstCrew[2]])
    expect(host.created).toHaveLength(5)

    // The lead's second brief landed in the SAME session: its transcript
    // holds both goals.
    const leadTranscript = host.states.get()[secondCrew[0]!].messages.map(chatMessageText)
    expect(leadTranscript.some(t => t.includes('GOAL:\nFirst'))).toBe(true)
    expect(leadTranscript.some(t => t.includes('GOAL:\nSecond'))).toBe(true)
  })

  it('after a gateway drop the crew resumes its stored sessions instead of opening new ones', async () => {
    host.script = { 0: () => teamBlock(['status: done', 'summary: one']) }
    await startTeamRun('First')
    await settled(() => $teamRun.get()?.status === 'done')
    const stored = $teamMembers.get().map(m => m.storedSessionId!)

    onGatewayUnavailable()
    expect($teamMembers.get().every(m => m.runtimeId === null)).toBe(true)

    await startTeamRun('Second')
    await settled(() => $teamRun.get()?.status === 'done')

    // Every seat, the Final included, resumed its stored session.
    expect(host.resumed).toEqual(stored)
    expect(host.created).toHaveLength(4)
    expect($teamMembers.get().map(m => m.runtimeId)).toEqual(stored.map(id => `${id.replace('stored-', '')}-resumed`))
  })

  it('a seat whose session is gone after the drop is re-created', async () => {
    host.script = { 0: () => teamBlock(['status: done', 'summary: one']) }
    await startTeamRun('First')
    await settled(() => $teamRun.get()?.status === 'done')

    onGatewayUnavailable()
    $teamMembers.set($teamMembers.get().map(m => (m.index === 2 ? { ...m, storedSessionId: 'stored-gone' } : m)))

    await startTeamRun('Second')
    await settled(() => $teamRun.get()?.status === 'done')

    expect(host.resumed).toHaveLength(3)
    expect(host.created).toHaveLength(5)
    expect($teamMembers.get()[2].runtimeId).toBe('rt-2-5')
  })

  it('a profile switch forgets the crew, so the next Start builds fresh on the new profile', async () => {
    host.script = { 0: () => teamBlock(['status: done', 'summary: one']) }
    await startTeamRun('First')
    await settled(() => $teamRun.get()?.status === 'done')
    expect($teamMembers.get().length).toBeGreaterThan(0)

    // The old profile's sessions must not be resumed next to seats created on
    // the new one (a mixed-profile crew on the old profile's config).
    const profileBefore = $activeGatewayProfile.get()
    $activeGatewayProfile.set(`${profileBefore}-other`)
    expect($teamMembers.get()).toEqual([])

    try {
      await startTeamRun('Second')
      await settled(() => $teamRun.get()?.status === 'done')

      expect(host.resumed).toEqual([])
      expect(host.created).toHaveLength(8)
    } finally {
      $activeGatewayProfile.set(profileBefore)
    }
  })

  it('a gateway drop mid-run fails the run and unbinds every seat', async () => {
    host.script = { 0: () => null }
    await startTeamRun('Goal')
    await settled(() => host.prompts.length === 1)

    onGatewayUnavailable()

    expect($teamRun.get()!.status).toBe('failed')
    expect($teamRun.get()!.error).toBe('Robo disconnected')
    expect($teamMembers.get().every(m => m.runtimeId === null)).toBe(true)
    expect(teamRunContextForTests()).toBeNull()
  })

  it('resetTeam closes every seat and clears the run', async () => {
    host.script = { 0: () => teamBlock(['status: done', 'summary: one']) }
    await startTeamRun('Goal')
    await settled(() => $teamRun.get()?.status === 'done')
    const runtimes = $teamMembers.get().map(m => m.runtimeId!)

    await resetTeam()

    expect(host.closed.sort()).toEqual([...runtimes].sort())
    expect($teamMembers.get()).toEqual([])
    expect($teamRun.get()).toBeNull()
  })
})

describe('the Final seat', () => {
  const finalPrompts = () => host.prompts.filter(p => p.index === TEAM_FINAL_INDEX)

  it('is briefed with the goal, the lead’s answer and the team notes once the lead is done, and its reply is the run’s final', async () => {
    host.script = {
      0: (_p, turn) =>
        turn === 1
          ? teamBlock(['status: continue', 'summary: Two stores.', 'option A: Use SQLite', 'option B: Use Postgres'])
          : teamBlock(['status: done', 'summary: Shipped with Postgres.']),
      1: prefers('Postgres'),
      2: prefers('Postgres'),
      [TEAM_FINAL_INDEX]: () => 'SYNTHESIS: Postgres, with the migration the reviewers asked for.'
    }

    await startTeamRun('Pick a store')
    await settled(() => $teamRun.get()?.status === 'done')

    const run = $teamRun.get()!
    expect(run.final).toBe('SYNTHESIS: Postgres, with the migration the reviewers asked for.')
    expect(run.log.filter(e => e.kind === 'final').map(e => e.text)).toEqual([run.final])

    // One brief, sent after the lead's last turn, carrying everything.
    expect(finalPrompts()).toHaveLength(1)
    const brief = finalPrompts()[0].prompt
    expect(brief).toContain('GOAL:\nPick a store')
    expect(brief).toContain('closing answer:\nShipped with Postgres.')
    expect(brief).toContain('Round 1: chose B')
    expect(brief).toContain('TEAM RULES')
    expect(host.prompts[host.prompts.length - 1].index).toBe(TEAM_FINAL_INDEX)

    // The lead is told about the working crew only — the Final is not a teammate.
    expect(host.prompts[0].prompt).toContain('team of 3: Lead (lead-model), Reviewer 2 (rev-a), Reviewer 3 (rev-b)')

    // The seat is a real session the user can keep talking to: its transcript
    // holds the brief and the answer, and it is idle.
    const seat = $teamMembers.get().find(m => m.role === 'final')!
    expect(seat.status).toBe('idle')
    const transcript = host.states.get()[seat.runtimeId!].messages.map(chatMessageText)
    expect(transcript[transcript.length - 1]).toBe(run.final)
  })

  it('synthesises the wrap-up answer when the rounds run out', async () => {
    $teamConfig.set({ ...$teamConfig.get(), maxRounds: 1 })
    host.script = {
      0: prompt =>
        prompt.includes('Wrap up now')
          ? teamBlock(['status: done', 'summary: Best effort after one round.'])
          : teamBlock(['status: continue', 'option A: a', 'option B: b']),
      1: prefers('a'),
      2: prefers('b'),
      [TEAM_FINAL_INDEX]: () => 'SYNTHESIS after the cap.'
    }

    await startTeamRun('Endless')
    await settled(() => $teamRun.get()?.status === 'done')

    expect($teamRun.get()!.final).toBe('SYNTHESIS after the cap.')
    expect(finalPrompts()[0].prompt).toContain('closing answer:\nBest effort after one round.')
  })

  it('falls back to the lead’s answer, and says so, when the Final session could not be opened', async () => {
    host.failCreate = new Set([TEAM_FINAL_INDEX])
    host.script = { 0: () => teamBlock(['status: done', 'summary: The lead’s own answer.']) }

    expect(await startTeamRun('Goal')).toBe(true)
    await settled(() => $teamRun.get()?.status === 'done')

    const run = $teamRun.get()!
    expect(run.final).toBe('The lead’s own answer.')
    expect(run.log.find(e => e.code === 'finalFallback')?.memberIndex).toBe(TEAM_FINAL_INDEX)
    expect(finalPrompts()).toHaveLength(0)
    expect($teamMembers.get().find(m => m.role === 'final')?.status).toBe('error')
  })

  it('falls back to the lead’s answer when the Final seat returns nothing', async () => {
    host.script = {
      0: () => teamBlock(['status: done', 'summary: The lead’s own answer.']),
      [TEAM_FINAL_INDEX]: () => ''
    }

    await startTeamRun('Goal')
    await settled(() => $teamRun.get()?.status === 'done')

    expect($teamRun.get()!.final).toBe('The lead’s own answer.')
    expect($teamRun.get()!.log.some(e => e.code === 'finalFallback')).toBe(true)
    expect($teamMembers.get().find(m => m.role === 'final')?.status).toBe('idle')
  })

  it('Stop during the synthesis ends the run as stopped, with the Final seat interrupted', async () => {
    host.script = {
      0: () => teamBlock(['status: done', 'summary: done']),
      [TEAM_FINAL_INDEX]: () => null
    }

    await startTeamRun('Goal')
    await settled(() => finalPrompts().length === 1)
    expect($teamMembers.get().find(m => m.role === 'final')?.status).toBe('synthesizing')

    await stopTeamRun()

    expect($teamRun.get()!.status).toBe('stopped')
    expect($teamRun.get()!.final).toBeNull()
    expect(host.interrupted).toEqual([host.runtimeOf(TEAM_FINAL_INDEX)])
    expect(teamRunContextForTests()).toBeNull()
  })
})

describe('submitTeamPrompt', () => {
  /** A tile delegate over the real `$sessionStates`, recording submits. */
  function installDelegate(submit: (runtimeId: string, text: string) => Promise<void>) {
    const calls: Array<{ options?: { queued?: boolean }; runtimeId: string; text: string }> = []
    const noop = async () => undefined

    const delegate: SessionTileDelegate = {
      archiveSession: noop,
      branchSession: noop,
      deleteSession: noop,
      executeSlash: noop,
      interruptSession: noop,
      resumeTile: async () => 'rt',
      submitToSession: async (runtimeId, text, options) => {
        calls.push({ options, runtimeId, text })
        await submit(runtimeId, text)
      },
      updateSession: (runtimeId, updater, storedSessionId) => {
        const current = $sessionStates.get()[runtimeId] ?? createClientSessionState(storedSessionId ?? null)
        const next = updater(current)
        $sessionStates.set({ ...$sessionStates.get(), [runtimeId]: next })

        return next
      }
    }

    setSessionTileDelegate(delegate)

    return calls
  }

  afterEach(() => {
    $sessionStates.set({})
  })

  it('paints the message in an idle seat and starts its turn before the gateway answers', async () => {
    const calls = installDelegate(async () => undefined)
    $sessionStates.set({ 'rt-x': createClientSessionState('s-x') })

    await submitTeamPrompt('rt-x', 'hello there')

    const state = $sessionStates.get()['rt-x']
    expect(state.messages.map(m => [m.role, chatMessageText(m)])).toEqual([['user', 'hello there']])
    expect(state.busy).toBe(true)
    expect(state.awaitingResponse).toBe(true)
    expect(calls).toEqual([{ options: { queued: true }, runtimeId: 'rt-x', text: 'hello there' }])
  })

  it('only adds the bubble to a busy seat and leaves the live stream’s bookkeeping alone', async () => {
    installDelegate(async () => undefined)
    $sessionStates.set({
      'rt-x': {
        ...createClientSessionState('s-x'),
        busy: true,
        messages: [{ id: 'a-1', parts: [textPart('streaming…')], role: 'assistant' }],
        sawAssistantPayload: true,
        streamId: 'a-1'
      }
    })

    await submitTeamPrompt('rt-x', 'and also')

    const state = $sessionStates.get()['rt-x']
    expect(state.messages.map(m => [m.role, chatMessageText(m)])).toEqual([
      ['assistant', 'streaming…'],
      ['user', 'and also']
    ])
    expect(state.streamId).toBe('a-1')
    expect(state.sawAssistantPayload).toBe(true)
    expect(state.busy).toBe(true)
  })

  it('rolls the bubble back and rethrows when the gateway refuses', async () => {
    installDelegate(async () => {
      throw new Error('Robo is at the active session limit (2/2).')
    })
    $sessionStates.set({ 'rt-x': createClientSessionState('s-x') })

    await expect(submitTeamPrompt('rt-x', 'lost?')).rejects.toThrow('active session limit')

    const state = $sessionStates.get()['rt-x']
    expect(state.messages).toEqual([])
    expect(state.busy).toBe(false)
    expect(state.awaitingResponse).toBe(false)
  })
})

describe('completionFromEvent', () => {
  it('ignores a message.complete for another session', () => {
    expect(completionFromEvent({ payload: { text: 'hi' }, session_id: 'other', type: 'message.complete' }, 'rt-0')).toBeNull()
  })

  it('reads the final text, preferring text then rendered', () => {
    expect(completionFromEvent({ payload: { text: '  the answer  ' }, session_id: 'rt-0' }, 'rt-0')).toEqual({
      text: 'the answer'
    })
    expect(completionFromEvent({ payload: { rendered: 'rendered only' }, session_id: 'rt-0' }, 'rt-0')).toEqual({
      text: 'rendered only'
    })
  })

  it('surfaces a terminal error frame', () => {
    expect(completionFromEvent({ payload: { error: 'Provider down', status: 'error' }, session_id: 'rt-0' }, 'rt-0')).toEqual({
      error: 'Provider down',
      text: ''
    })
    // An error status with neither error nor text still reports a reason.
    expect(completionFromEvent({ payload: { status: 'error' }, session_id: 'rt-0' }, 'rt-0')).toEqual({
      error: 'Robo reported an error',
      text: ''
    })
  })

  it('a successful empty completion is text-only (no error)', () => {
    expect(completionFromEvent({ payload: {}, session_id: 'rt-0' }, 'rt-0')).toEqual({ text: '' })
  })
})
