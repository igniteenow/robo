import { describe, expect, it } from 'vitest'

import { fmtClock, fmtTurnDuration, summarizeTools, turnReceipt } from '../domain/receipt.js'

describe('turn receipt', () => {
  it('times quick turns to the tenth and long ones on the status clock', () => {
    expect(fmtTurnDuration(3_640)).toBe('3.6s')
    expect(fmtTurnDuration(0)).toBe('0.0s')
    expect(fmtTurnDuration(-5)).toBe('0.0s')
    expect(fmtTurnDuration(48_200)).toBe('48s')
    expect(fmtTurnDuration(61 * 60_000)).toBe('1h 1m')
  })

  it('counts what Robo did in plain nouns, biggest group first', () => {
    expect(summarizeTools([])).toEqual([])
    expect(summarizeTools(['web_search'])).toEqual(['1 search'])
    expect(
      summarizeTools(['terminal', 'patch', 'terminal', 'read_file', 'execute_code', 'patch', 'search_files'])
    ).toEqual(['3 commands', '2 edits', '1 file read', '+1 more'])
    // Plugins and MCP servers have no curated noun; they are still counted.
    expect(summarizeTools(['mcp_github_list_prs', 'mcp_github_list_prs'])).toEqual(['2 tool calls'])
  })

  it('reads duration · tools · clock, and skips the duration when the start is unknown', () => {
    const endedAt = Date.UTC(2026, 9, 31, 22, 39, 0)
    const clock = fmtClock(endedAt)

    expect(clock).toMatch(/\d/)
    expect(turnReceipt({ endedAt, startedAt: endedAt - 7_600, toolNames: ['web_search'] })).toBe(
      `7.6s · 1 search · ${clock}`
    )
    expect(turnReceipt({ endedAt, startedAt: endedAt - 3_600, toolNames: [] })).toBe(`3.6s · ${clock}`)
    expect(turnReceipt({ endedAt, startedAt: null, toolNames: ['terminal'] })).toBe(`1 command · ${clock}`)
  })
})
