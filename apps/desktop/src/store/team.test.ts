import { beforeEach, describe, expect, it } from 'vitest'

import { readJson } from '@/lib/storage'

import {
  $teamConfig,
  $teamRun,
  appendTeamLog,
  createTeamRun,
  defaultTeamConfig,
  normalizeTeamConfig,
  patchTeamRun,
  resetTeamConfig,
  setTeamMaxRounds,
  setTeamMemberModel,
  setTeamSize,
  teamRunActive
} from './team'

const CONFIG_KEY = 'robo.desktop.team.config.v1'

beforeEach(() => {
  resetTeamConfig()
  $teamRun.set(null)
})

describe('team config', () => {
  it('starts with three seats, the default round cap and no model picks', () => {
    expect($teamConfig.get()).toEqual(defaultTeamConfig())
    expect($teamConfig.get().members).toHaveLength(4)
    expect($teamConfig.get().members.every(m => m.model === '' && m.provider === '')).toBe(true)
  })

  it('clamps size and rounds, and persists every change', () => {
    setTeamSize(9)
    expect($teamConfig.get().size).toBe(4)
    setTeamSize(0)
    expect($teamConfig.get().size).toBe(2)
    setTeamMaxRounds(100)
    expect($teamConfig.get().maxRounds).toBe(99)
    // 0 (and anything below) is "no cap" — the default.
    setTeamMaxRounds(-3)
    expect($teamConfig.get().maxRounds).toBe(0)
    expect(defaultTeamConfig().maxRounds).toBe(0)

    expect(readJson<{ maxRounds: number; size: number }>(CONFIG_KEY)).toMatchObject({ maxRounds: 0, size: 2 })
  })

  it('keeps a seat’s model pick when the team shrinks and grows back', () => {
    setTeamMemberModel(3, { model: ' gpt-x ', provider: ' openai ' })
    setTeamSize(2)
    setTeamSize(4)

    expect($teamConfig.get().members[3]).toEqual({ model: 'gpt-x', provider: 'openai' })
  })

  it('ignores an out-of-range seat', () => {
    const before = $teamConfig.get()
    setTeamMemberModel(7, { model: 'x', provider: 'y' })
    expect($teamConfig.get()).toBe(before)
  })

  it('normalizes whatever was persisted (missing fields, bad numbers, junk)', () => {
    expect(normalizeTeamConfig(null)).toEqual(defaultTeamConfig())
    expect(normalizeTeamConfig('nope')).toEqual(defaultTeamConfig())

    const loaded = normalizeTeamConfig({ maxRounds: 'lots', members: [{ model: 'm' }, 'junk'], size: 3.7 })
    expect(loaded.size).toBe(4)
    expect(loaded.maxRounds).toBe(defaultTeamConfig().maxRounds)
    expect(loaded.members).toHaveLength(4)
    expect(loaded.members[0]).toEqual({ model: 'm', provider: '' })
    expect(loaded.members[1]).toEqual({ model: '', provider: '' })
  })
})

describe('team run', () => {
  it('patches and logs only the live run', () => {
    const run = createTeamRun('  Build it  ', 120)
    expect(run.goal).toBe('Build it')
    expect(run.maxRounds).toBe(99)
    expect(run.memory.goal).toBe('Build it')

    $teamRun.set(run)
    patchTeamRun(run.id, { round: 2, status: 'running' })
    appendTeamLog(run.id, { kind: 'round', round: 2, text: '' })
    expect($teamRun.get()).toMatchObject({ round: 2, status: 'running' })
    expect($teamRun.get()!.log).toHaveLength(1)
    expect($teamRun.get()!.log[0]).toMatchObject({ kind: 'round', round: 2 })

    // A stale run id (a continuation after Stop/restart) must not write.
    patchTeamRun('someone-else', { status: 'done' })
    appendTeamLog('someone-else', { kind: 'final', round: 2, text: 'x' })
    expect($teamRun.get()!.status).toBe('running')
    expect($teamRun.get()!.log).toHaveLength(1)
  })

  it('knows which statuses are still live', () => {
    expect(teamRunActive(null)).toBe(false)

    for (const status of ['starting', 'running', 'stopping'] as const) {
      expect(teamRunActive({ ...createTeamRun('g', 3), status })).toBe(true)
    }

    for (const status of ['done', 'failed', 'stopped'] as const) {
      expect(teamRunActive({ ...createTeamRun('g', 3), status })).toBe(false)
    }
  })
})
