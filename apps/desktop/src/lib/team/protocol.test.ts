import { describe, expect, it } from 'vitest'

import {
  buildCompletionReviewPrompt,
  buildFinalSynthesisPrompt,
  buildLeadContinuePrompt,
  buildLeadKickoffPrompt,
  buildReviewPrompt,
  buildSideTaskPrompt,
  clampTeamRounds,
  clampTeamSize,
  clip,
  COMPLETION_CHECK_MARKER,
  COMPLETION_NOT_DONE,
  COMPLETION_OPTIONS,
  emptyTeamMemory,
  hasRoundCap,
  parseTeamResult,
  parseTeamVote,
  renderTeamMemory,
  shuffleOptionsFor,
  tallyBallots,
  TEAM_FINAL_INDEX,
  TEAM_MAX_MEMBERS,
  type TeamBallot,
  type TeamDecision,
  teamMemberName,
  type TeamOption,
  teamRole,
  unshuffleRanking
} from './protocol'

const options: TeamOption[] = [
  { label: 'A', text: 'Use SQLite' },
  { label: 'B', text: 'Use Postgres' },
  { label: 'C', text: 'Use flat files' }
]

const ballot = (memberIndex: number, ranking: string[], confidence = 0.5, valid = true): TeamBallot => ({
  confidence,
  guidance: '',
  memberIndex,
  ranking,
  reason: '',
  valid
})

describe('parseTeamResult', () => {
  it('reads the fenced block: status, summary, options and a side task', () => {
    const reply = [
      'I looked at the repo and the storage layer is the first fork.',
      '',
      '```team',
      'status: continue',
      'summary: Mapped the storage code; two viable designs.',
      'option A: Keep SQLite and add WAL mode',
      'option B: Move to Postgres',
      '  with a migration script',
      'side task: Benchmark the current read path',
      '```'
    ].join('\n')

    const result = parseTeamResult(reply)

    expect(result.found).toBe(true)
    expect(result.status).toBe('continue')
    expect(result.summary).toBe('Mapped the storage code; two viable designs.')
    expect(result.options).toEqual([
      { label: 'A', text: 'Keep SQLite and add WAL mode' },
      { label: 'B', text: 'Move to Postgres\nwith a migration script' }
    ])
    expect(result.sideTasks).toEqual(['Benchmark the current read path'])
  })

  it('uses the LAST block when a reply quotes an earlier one', () => {
    const reply = [
      'Earlier I said:',
      '```team',
      'status: continue',
      'option A: old',
      'option B: older',
      '```',
      'but now:',
      '```team',
      'status: done',
      'summary: Finished — the answer is 42.',
      '```'
    ].join('\n')

    const result = parseTeamResult(reply)
    expect(result.status).toBe('done')
    expect(result.summary).toBe('Finished — the answer is 42.')
    expect(result.options).toEqual([])
  })

  it('still finds bold / bulleted option lines without a fence', () => {
    const reply = [
      'Here is where we are.',
      '',
      '- **Option A:** ship as is',
      '- **Option B:** add tests first',
      '- **Option C:** refactor then ship',
      '',
      'Options: these are the three I see.'
    ].join('\n')

    const result = parseTeamResult(reply)

    expect(result.found).toBe(true)
    expect(result.status).toBe('continue')
    expect(result.options.map(o => o.label)).toEqual(['A', 'B', 'C'])
    expect(result.options[1].text).toBe('add tests first')
    // Loose prose after the list is prose, not part of option C.
    expect(result.options[2].text).toBe('refactor then ship')
  })

  it('treats a plain reply with no block as a finished answer', () => {
    const result = parseTeamResult('The capital of France is Paris.')

    expect(result.found).toBe(false)
    expect(result.status).toBe('done')
    expect(result.summary).toBe('The capital of France is Paris.')
    expect(result.options).toEqual([])
  })

  it('maps numbered options onto letters and caps the count', () => {
    const reply = ['```team', 'option 1: one', 'option 2: two', 'option 3: three', 'option 4: four', 'option 5: five', '```'].join(
      '\n'
    )

    const result = parseTeamResult(reply)
    expect(result.options.map(o => o.label)).toEqual(['A', 'B', 'C', 'D'])
  })

  it('reads status words loosely and ignores case', () => {
    expect(parseTeamResult('```team\nStatus: DONE\nSummary: ok\n```').status).toBe('done')
    expect(parseTeamResult('```team\nstatus: finished\nsummary: ok\n```').status).toBe('done')
    expect(parseTeamResult('```team\nstatus: continue\noption A: x\noption B: y\n```').status).toBe('continue')
  })

  it('falls back to the prose before the block as the summary', () => {
    const result = parseTeamResult('Did the thing.\n\n```team\nstatus: continue\noption A: x\noption B: y\n```')
    expect(result.summary).toBe('Did the thing.')
  })

  it('handles empty and whitespace replies', () => {
    const result = parseTeamResult('   ')
    expect(result.found).toBe(false)
    expect(result.status).toBe('done')
    expect(result.summary).toBe('')
  })
})

describe('parseTeamVote', () => {
  const allowed = ['A', 'B', 'C']

  it('reads the fenced vote block', () => {
    const vote = parseTeamVote('I checked both.\n```vote\nranking: B > A > C\nconfidence: 0.8\nreason: B is tested.\n```', allowed)

    expect(vote.found).toBe(true)
    expect(vote.ranking).toEqual(['B', 'A', 'C'])
    expect(vote.confidence).toBeCloseTo(0.8)
    expect(vote.reason).toBe('B is tested.')
    expect(vote.guidance).toBe('')
  })

  it('reads the reviewer’s multi-line guidance for the lead, under any of its names', () => {
    const vote = parseTeamVote(
      [
        '```vote',
        'ranking: A > B > C',
        'confidence: 0.9',
        'reason: A passes the tests.',
        'guidance: The migration misses the index on user_id.',
        'Add it before the backfill, and run the suite with -x.',
        'I verified the API shape against the docs.',
        '```'
      ].join('\n'),
      allowed
    )

    expect(vote.ranking).toEqual(['A', 'B', 'C'])
    expect(vote.guidance).toBe(
      'The migration misses the index on user_id.\nAdd it before the backfill, and run the suite with -x.\nI verified the API shape against the docs.'
    )

    expect(parseTeamVote('```vote\nranking: B\nadvice: ship B\n```', allowed).guidance).toBe('ship B')
    expect(parseTeamVote('```vote\nranking: B\nnext steps: write the tests\n```', allowed).guidance).toBe('write the tests')
  })

  it('accepts commas, "option" prefixes, numbers and percentages', () => {
    const vote = parseTeamVote('Ranking: Option 2, option 1, OPTION 3\nConfidence: 70%', allowed)

    expect(vote.ranking).toEqual(['B', 'A', 'C'])
    expect(vote.confidence).toBeCloseTo(0.7)
  })

  it('treats a lone first choice as a partial ranking', () => {
    expect(parseTeamVote('Vote: C', allowed).ranking).toEqual(['C'])
    expect(parseTeamVote('After checking, I pick B.', allowed).ranking).toEqual(['B'])
  })

  it('drops labels that were not on the table and repeats', () => {
    expect(parseTeamVote('ranking: D > B > B > A', allowed).ranking).toEqual(['B', 'A'])
  })

  it('defaults confidence to 0.5 and reports nothing usable as not found', () => {
    const vote = parseTeamVote('I cannot decide between these.', allowed)

    expect(vote.found).toBe(false)
    expect(vote.ranking).toEqual([])
    expect(vote.confidence).toBe(0.5)
  })
})

describe('shuffleOptionsFor / unshuffleRanking', () => {
  it('relabels from A, is a permutation, and is stable for the same inputs', () => {
    const first = shuffleOptionsFor(options, 1, 1)
    const again = shuffleOptionsFor(options, 1, 1)

    expect(first.presented.map(o => o.label)).toEqual(['A', 'B', 'C'])
    expect(first.presented.map(o => o.text).sort()).toEqual(options.map(o => o.text).sort())
    expect(again).toEqual(first)
    expect(Object.values(first.toLead).sort()).toEqual(['A', 'B', 'C'])
  })

  it('gives different reviewers different orders across a round (position bias)', () => {
    const orders = new Set<string>()

    for (let member = 1; member <= 3; member += 1) {
      orders.add(
        shuffleOptionsFor(options, 2, member)
          .presented.map(o => o.text)
          .join('|')
      )
    }

    expect(orders.size).toBeGreaterThan(1)
  })

  it('maps a presented ranking back into the lead label space', () => {
    const shuffled = shuffleOptionsFor(options, 3, 2)
    const presentedRanking = shuffled.presented.map(o => o.label)
    const leadRanking = unshuffleRanking(presentedRanking, shuffled.toLead)

    expect(leadRanking.map(label => options.find(o => o.label === label)!.text)).toEqual(
      shuffled.presented.map(o => o.text)
    )
    expect(unshuffleRanking(['Z', 'A', 'A'], shuffled.toLead)).toEqual([shuffled.toLead.A])
  })
})

describe('tallyBallots', () => {
  it('scores with Borda so broad second choices beat a narrow plurality', () => {
    // A gets two first places, but B is everyone's first or second.
    const tally = tallyBallots(options, [
      ballot(1, ['A', 'B', 'C']),
      ballot(2, ['A', 'B', 'C']),
      ballot(3, ['B', 'C', 'A']),
      ballot(4, ['B', 'A', 'C']),
      ballot(5, ['C', 'B', 'A'])
    ])

    expect(tally.points).toEqual({ A: 10, B: 12, C: 8 })
    expect(tally.firstChoices).toEqual({ A: 2, B: 2, C: 1 })
    expect(tally.winner).toBe('B')
    expect(tally.decidedBy).toBe('borda')
    expect(tally.validBallots).toBe(5)
  })

  it('breaks a Borda tie on first-choice confidence, then on the lead order', () => {
    const byConfidence = tallyBallots(options, [ballot(1, ['A'], 0.4), ballot(2, ['B'], 0.9)])
    expect(byConfidence.winner).toBe('B')
    expect(byConfidence.decidedBy).toBe('confidence')

    const byOrder = tallyBallots(options, [ballot(1, ['B'], 0.6), ballot(2, ['A'], 0.6)])
    expect(byOrder.winner).toBe('A')
    expect(byOrder.decidedBy).toBe('lead-order')
  })

  it('ignores invalid ballots and falls back to the lead’s first option with none', () => {
    const tally = tallyBallots(options, [ballot(1, [], 0.5, false), ballot(2, ['C'], 0.5, false)])

    expect(tally.winner).toBe('A')
    expect(tally.decidedBy).toBe('no-votes')
    expect(tally.validBallots).toBe(0)
  })

  it('scores a partial ranking only for the options it names', () => {
    const tally = tallyBallots(options, [ballot(1, ['C'])])
    expect(tally.points).toEqual({ A: 0, B: 0, C: 3 })
    expect(tally.winner).toBe('C')
  })
})

describe('memory and prompts', () => {
  const decision: TeamDecision = {
    ballots: [ballot(1, ['B', 'A'], 0.7), { ...ballot(2, ['A', 'B'], 0.6), reason: 'A is simpler.' }],
    chosen: options[1],
    options,
    round: 1,
    summary: 'Compared the storage designs.',
    tally: tallyBallots(options, [ballot(1, ['B', 'A'], 0.7), ballot(2, ['A', 'B'], 0.6)])
  }

  it('renders decisions and side results, newest last, trimming the oldest only when given a budget', () => {
    const memory = emptyTeamMemory('Build the thing')
    memory.decisions.push(decision, { ...decision, round: 2, chosen: options[0] })
    memory.sideResults.push({ memberIndex: 2, summary: 'Reads are 3ms.', task: 'Benchmark reads' })

    const full = renderTeamMemory(memory)
    expect(full).toContain('Round 1: chose B')
    expect(full).toContain('Round 2: chose A')
    expect(full).toContain('Reviewer 3 side task "Benchmark reads": Reads are 3ms.')
    // Plain notes carry the decisions, not the reviewers' prose.
    expect(full).not.toContain('A is simpler.')

    const trimmed = renderTeamMemory(memory, 120)
    expect(trimmed.startsWith('… (older notes trimmed)')).toBe(true)
    expect(trimmed).toContain('Benchmark reads')
    expect(trimmed).not.toContain('Round 1')
  })

  it('never trims by default: a long run keeps every decision in every prompt', () => {
    const memory = emptyTeamMemory('Long haul')

    for (let round = 1; round <= 60; round += 1) {
      memory.decisions.push({ ...decision, round, summary: `round ${round} of a very long run`.repeat(4) })
    }

    const notes = renderTeamMemory(memory)
    expect(notes).not.toContain('older notes trimmed')
    expect(notes).toContain('Round 1: chose B')
    expect(notes).toContain('Round 60: chose B')
  })

  it('detail notes add every reviewer’s reason and guidance under its round', () => {
    const memory = emptyTeamMemory('Goal')
    memory.decisions.push({
      ...decision,
      ballots: [{ ...ballot(1, ['B', 'A'], 0.7), guidance: 'Add the index first.', reason: 'B scales.' }]
    })

    const notes = renderTeamMemory(memory, Number.POSITIVE_INFINITY, true)
    expect(notes).toContain('Round 1: chose B')
    expect(notes).toContain('Reviewer 2 (B > A): B scales.')
    expect(notes).toContain('Guidance: Add the index first.')
  })

  it('an empty memory renders nothing', () => {
    expect(renderTeamMemory(emptyTeamMemory('x'))).toBe('')
  })

  it('kickoff names the roster, carries the goal and the block contract', () => {
    const prompt = buildLeadKickoffPrompt('Ship the release', {
      members: [
        { model: 'gpt-x', name: 'Lead' },
        { model: 'model-y', name: 'Reviewer 2' }
      ]
    })

    expect(prompt).toContain('team of 2: Lead (gpt-x), Reviewer 2 (model-y)')
    expect(prompt).toContain('GOAL:\nShip the release')
    expect(prompt).toContain('```team')
    expect(prompt).toContain('status: continue | done')
  })

  it('review prompt lists the presented options and demands the vote block', () => {
    const shuffled = shuffleOptionsFor(options, 1, 1)
    const prompt = buildReviewPrompt('Goal', 'Lead did X', shuffled.presented, emptyTeamMemory('Goal'), 'Reviewer 2')

    for (const option of shuffled.presented) {
      expect(prompt).toContain(`option ${option.label}: ${option.text}`)
    }

    expect(prompt).toContain('```vote')
    expect(prompt).toContain('INDEPENDENTLY')
    expect(prompt).not.toContain('Team notes so far')
    // The reviewer is the lead's partner: the contract asks for guidance.
    expect(prompt).toContain('guidance:')
    expect(prompt).toContain('senior partner')
  })

  it('completion check: the lead’s result, the accept / send-back options, the pushbacks left', () => {
    const shuffled = shuffleOptionsFor(COMPLETION_OPTIONS, 3, 2)
    const prompt = buildCompletionReviewPrompt('Ship it', 'Here is the whole thing.', shuffled.presented, emptyTeamMemory('Ship it'), 'Reviewer 3', 2)

    expect(prompt.startsWith(COMPLETION_CHECK_MARKER)).toBe(true)
    expect(prompt).toContain('The lead reports the goal is DONE. Its result:\nHere is the whole thing.')
    expect(prompt).toContain('Done — the result meets the goal')
    expect(prompt).toContain('Not done — something is missing')
    expect(prompt).toContain('send the lead back 2 more times')
    expect(prompt).toContain('```vote')
    expect(COMPLETION_OPTIONS.find(o => o.label === COMPLETION_NOT_DONE)!.text).toContain('Not done')

    const last = buildCompletionReviewPrompt('Ship it', 'Result', shuffled.presented, emptyTeamMemory('Ship it'), 'Reviewer 3', 0)
    expect(last).toContain('This is the last check')
  })

  it('continue prompt states the decision, the votes with reasons and side results', () => {
    const memory = emptyTeamMemory('Goal')
    memory.decisions.push(decision)

    const prompt = buildLeadContinuePrompt(decision, memory, [
      { chosen: options[2], memberIndex: 2, summary: 'Bench done', task: 'Benchmark' }
    ])

    expect(prompt).toContain('Team decision for round 1: option B — Use Postgres')
    expect(prompt).toContain('Reviewer 3: A > B — A is simpler.')
    expect(prompt).toContain('Reviewer 3 finished "Benchmark": Bench done')
    expect(prompt).toContain('Team chose: C — Use flat files')
    expect(prompt).toContain('```team')
    // The decision heads the prompt; the notes do not repeat it.
    expect(prompt).not.toContain('Round 1: chose B')
    // No reviewer gave guidance: the section is absent, not empty.
    expect(prompt).not.toContain('Reviewer guidance')
  })

  it('continue prompt carries every reviewer’s guidance and tells the lead to act on it', () => {
    const guided: TeamDecision = {
      ...decision,
      ballots: [
        { ...ballot(1, ['B', 'A'], 0.7), guidance: 'Index user_id before the backfill.\nRun the suite with -x.' },
        { ...ballot(2, ['A', 'B'], 0.6), guidance: 'The API shape matches the docs; the retry path is untested.' }
      ]
    }

    const prompt = buildLeadContinuePrompt(guided, emptyTeamMemory('Goal'), [])
    expect(prompt).toContain('Reviewer guidance')
    expect(prompt).toContain('Reviewer 2:\nIndex user_id before the backfill.\nRun the suite with -x.')
    expect(prompt).toContain('Reviewer 3:\nThe API shape matches the docs; the retry path is untested.')
    expect(prompt).toContain('Act on the reviewers’ guidance')
  })

  it('side-task prompt carries the task and the result contract', () => {
    const prompt = buildSideTaskPrompt('Goal', 'Benchmark reads', emptyTeamMemory('Goal'), 'Reviewer 3')
    expect(prompt).toContain('side task to do in parallel:\nBenchmark reads')
    expect(prompt).toContain('```team')
  })
})

describe('small helpers', () => {
  it('clip cuts on a word boundary and marks the cut', () => {
    expect(clip('short', 10)).toBe('short')
    expect(clip('one two three four five', 15)).toBe('one two three…')
    expect(clip('   padded   ', 20)).toBe('padded')
  })

  it('clamps team size and rounds to their bounds', () => {
    expect(clampTeamSize(1)).toBe(2)
    expect(clampTeamSize(9)).toBe(4)
    expect(clampTeamSize(Number.NaN)).toBe(2)
    // 0 is "no cap" (the default); a cap is 1..99.
    expect(clampTeamRounds(0)).toBe(0)
    expect(clampTeamRounds(-1)).toBe(0)
    expect(clampTeamRounds(0.4)).toBe(0)
    expect(clampTeamRounds(1)).toBe(1)
    expect(clampTeamRounds(120)).toBe(99)
    expect(clampTeamRounds(Number.NaN)).toBe(0)
    expect(hasRoundCap(0)).toBe(false)
    expect(hasRoundCap(6)).toBe(true)
  })

  it('names roles by seat', () => {
    expect(teamRole(0)).toBe('lead')
    expect(teamRole(3)).toBe('reviewer')
    expect(teamMemberName(0)).toBe('Lead')
    expect(teamMemberName(2)).toBe('Reviewer 3')
  })

  it('treats the final-outcome seat as its own role, off the reviewer range', () => {
    expect(teamRole(TEAM_FINAL_INDEX)).toBe('final')
    expect(teamMemberName(TEAM_FINAL_INDEX)).toBe('Final')
    // It must never collide with a working seat (0..3).
    expect(TEAM_FINAL_INDEX).toBeGreaterThan(TEAM_MAX_MEMBERS)
  })
})

describe('team etiquette and the final synthesis', () => {
  it('every work prompt carries the shared-state etiquette so members stop colliding', () => {
    const roster = { members: [{ model: 'm', name: 'Lead' }, { model: 'n', name: 'Reviewer 2' }] }
    const shuffled = shuffleOptionsFor(options, 1, 1)

    const prompts = [
      buildLeadKickoffPrompt('Goal', roster),
      buildReviewPrompt('Goal', 'did X', shuffled.presented, emptyTeamMemory('Goal'), 'Reviewer 2'),
      buildSideTaskPrompt('Goal', 'task', emptyTeamMemory('Goal'), 'Reviewer 2')
    ]

    for (const prompt of prompts) {
      expect(prompt).toContain('TEAM RULES')
      expect(prompt).toContain('shared state is read-only')
      expect(prompt).toContain('self-improvement')
      // The lead must still be able to do the work.
      expect(prompt).toContain('the LEAD edits whatever the goal requires')
    }
  })

  it('keeps the whole answer unclipped for the Final while the summary stays within budget', () => {
    const long = 'word '.repeat(1000).trim()
    const withBlock = parseTeamResult(`\`\`\`team\nstatus: done\nsummary: ${long}\n\`\`\``)
    expect(withBlock.answer).toBe(long)
    expect(withBlock.summary.length).toBeLessThanOrEqual(1601)
    expect(withBlock.summary.endsWith('…')).toBe(true)

    const prose = parseTeamResult(long)
    expect(prose.answer).toBe(long)
    expect(prose.summary.length).toBeLessThanOrEqual(1601)

    const short = parseTeamResult('```team\nstatus: done\nsummary: Paris.\n```')
    expect(short.answer).toBe('Paris.')
    expect(short.summary).toBe('Paris.')

    // The usual done shape: the work in prose, a short summary in the block —
    // the answer is both, the summary is the block's line.
    const both = parseTeamResult('Here is the full design.\n\nSection 1…\n\n```team\nstatus: done\nsummary: Chose A.\n```')
    expect(both.answer).toBe('Here is the full design.\n\nSection 1…\n\nChose A.')
    expect(both.summary).toBe('Chose A.')

    // A loose "summary:" line in prose is already part of the answer: no repeat.
    const loose = parseTeamResult('Did it.\nSummary: Done well.')
    expect(loose.answer).toBe('Did it.\nSummary: Done well.')
    expect(loose.summary).toBe('Done well.')
  })

  it('final synthesis carries the goal, the lead answer, the notes and asks for plain prose', () => {
    const memory = emptyTeamMemory('Build the thing')
    memory.decisions.push({
      ballots: [ballot(1, ['B', 'A'], 0.7)],
      chosen: options[1],
      options,
      round: 1,
      summary: 'Compared designs.',
      tally: tallyBallots(options, [ballot(1, ['B', 'A'], 0.7)])
    })

    const prompt = buildFinalSynthesisPrompt('Build the thing', memory, 'The lead says use Postgres with WAL.')

    expect(prompt).toContain('FINAL member')
    expect(prompt).toContain('GOAL:\nBuild the thing')
    expect(prompt).toContain('The lead says use Postgres with WAL.')
    expect(prompt).toContain('Round 1: chose B')
    expect(prompt).toContain('no team block is needed')
    expect(prompt).toContain('TEAM RULES')
  })
})
