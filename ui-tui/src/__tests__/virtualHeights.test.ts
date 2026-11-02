import { describe, expect, it } from 'vitest'

import { estimatedMsgHeight, messageHeightKey, wrappedLines } from '../lib/virtualHeights.js'
import type { Msg } from '../types.js'

describe('virtual height estimates', () => {
  it('uses stable content keys across resumed message objects', () => {
    const msg: Msg = { role: 'assistant', text: 'same text', tools: ['Search Files [long message]'] }

    expect(messageHeightKey(msg)).toBe(messageHeightKey({ ...msg }))
  })

  it('accounts for wrapping and preserved blank-block rhythm', () => {
    const msg: Msg = { role: 'assistant', text: `one\n\n${'x'.repeat(90)}` }

    expect(wrappedLines(msg.text, 30)).toBe(5)
    expect(estimatedMsgHeight(msg, 35, { compact: false, details: false })).toBeGreaterThan(5)
  })

  it('uses compound user prompt width when estimating user message wrapping', () => {
    // cols must clear the 20-col body-width floor for both prompts (gutter +
    // horizontalReserve=4) so the wider 'Ψ >' prompt actually narrows the
    // body enough to wrap an extra line vs the single-cell '❯' prompt.
    const msg: Msg = { role: 'user', text: 'x'.repeat(23) }

    expect(estimatedMsgHeight(msg, 30, { compact: false, details: false, userPrompt: '❯' })).toBe(3)
    expect(estimatedMsgHeight(msg, 30, { compact: false, details: false, userPrompt: 'Ψ >' })).toBe(4)
  })

  it('adds one row for a group-boundary lead gap', () => {
    const msg: Msg = { role: 'assistant', text: 'reply' }

    expect(estimatedMsgHeight(msg, 80, { compact: false, details: false, leadGap: true })).toBe(
      estimatedMsgHeight(msg, 80, { compact: false, details: false, leadGap: false }) + 1
    )
  })

  it('includes detail sections when visible', () => {
    const msg: Msg = { role: 'assistant', text: 'ok', thinking: 'line 1\nline 2', tools: ['Tool A', 'Tool B'] }

    expect(estimatedMsgHeight(msg, 80, { compact: false, details: true })).toBeGreaterThan(
      estimatedMsgHeight(msg, 80, { compact: false, details: false })
    )
  })

  it('accounts for the trail and its gap above the reply when assistant details are visible', () => {
    const msg: Msg = { role: 'assistant', text: 'ok', thinking: 'plan' }

    // one thinking row + the gap; the `$Robo` header row is counted either way
    expect(estimatedMsgHeight(msg, 80, { compact: false, details: true })).toBe(
      estimatedMsgHeight(msg, 80, { compact: false, details: false }) + 2
    )
  })

  it('counts the receipt row that closes a reply, with its gap outside compact mode', () => {
    const reply: Msg = { receipt: '7.6s · 1 search · 10:39 PM', role: 'assistant', text: 'ok' }

    expect(estimatedMsgHeight(reply, 80, { compact: false, details: false })).toBe(4)
    expect(estimatedMsgHeight(reply, 80, { compact: true, details: false })).toBe(3)
    expect(messageHeightKey(reply)).not.toBe(messageHeightKey({ role: 'assistant', text: 'ok' }))
  })

  it('counts the `$<name>` header row over the person’s message once a name is set', () => {
    const msg: Msg = { role: 'user', text: 'hi' }
    const base = estimatedMsgHeight(msg, 80, { compact: false, details: false })

    expect(estimatedMsgHeight(msg, 80, { compact: false, details: false, userName: 'Ahmi' })).toBe(base + 1)
    expect(estimatedMsgHeight(msg, 80, { compact: false, details: false, userName: '  ' })).toBe(base)
  })

  it('counts the `$Robo` header row that opens a reply', () => {
    expect(estimatedMsgHeight({ role: 'assistant', text: 'ok' }, 80, { compact: false, details: false })).toBe(2)
    expect(estimatedMsgHeight({ role: 'system', text: 'ok' }, 80, { compact: false, details: false })).toBe(1)
    expect(
      estimatedMsgHeight({ kind: 'slash', role: 'assistant', text: 'ok' }, 80, { compact: false, details: false })
    ).toBe(2)
  })

  it('does not account for a response separator without visible details', () => {
    const msg: Msg = { role: 'assistant', text: 'ok' }

    expect(estimatedMsgHeight(msg, 80, { compact: false, details: true })).toBe(
      estimatedMsgHeight(msg, 80, { compact: false, details: false })
    )
  })

  it('honors per-section visibility when estimating response separators', () => {
    const thinkingOnly: Msg = { role: 'assistant', text: 'ok', thinking: 'plan' }
    const toolsOnly: Msg = { role: 'assistant', text: 'ok', tools: ['Tool A'] }

    expect(
      estimatedMsgHeight(thinkingOnly, 80, {
        compact: false,
        details: true,
        thinkingVisible: false,
        toolsVisible: true
      })
    ).toBe(estimatedMsgHeight(thinkingOnly, 80, { compact: false, details: false }))

    expect(
      estimatedMsgHeight(toolsOnly, 80, {
        compact: false,
        details: true,
        thinkingVisible: true,
        toolsVisible: false
      })
    ).toBe(estimatedMsgHeight(toolsOnly, 80, { compact: false, details: false }))
  })

  it('reserves two extra rows for the inter-turn separator on non-first user messages', () => {
    const msg: Msg = { role: 'user', text: 'follow-up question' }
    const base = estimatedMsgHeight(msg, 80, { compact: false, details: false })
    const withSep = estimatedMsgHeight(msg, 80, { compact: false, details: false, withSeparator: true })

    expect(withSep).toBe(base + 2)
  })

  it('caps wrapped-line counting so giant assistant turns do not block offset rebuilds', () => {
    // wrappedLines is invoked once per uncached message during
    // useVirtualHistory's offset rebuild. Unbounded counting on a long
    // assistant response (10k+ chars × every row × every rebuild) blocks
    // the UI on cold mount. Cap is ~800 rows; post-mount Yoga
    // measurement converges to the true height regardless.
    const giant = 'x'.repeat(1_000_000)
    const t0 = performance.now()
    const rows = wrappedLines(giant, 80)
    const elapsed = performance.now() - t0

    expect(rows).toBeLessThanOrEqual(800)
    expect(elapsed).toBeLessThan(50)
  })
})
