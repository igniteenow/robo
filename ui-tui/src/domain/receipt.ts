// The receipt that closes each of Robo's replies: how long the turn took,
// what Robo did to get there, and when it finished.
//
//   ✓ 7.6s · 1 search · 10:39 PM
//   ✓ 48s · 3 commands · 2 edits · 1 file read · 10:41 PM
//
// It is the one line that says "Robo is done" — the transcript no longer
// ends on prose that could still be streaming. The counts come from the
// turn's own tool calls (turnController), grouped into plain nouns; tools
// with no curated noun (plugins, MCP servers) count as tool calls.

import { fmtDuration } from './messages.js'

type Noun = readonly [singular: string, plural: string]

const BROWSER: Noun = ['browser step', 'browser steps']
const COMMAND: Noun = ['command', 'commands']
const IMAGE: Noun = ['image', 'images']
const SEARCH: Noun = ['search', 'searches']
const OTHER_NOUN: Noun = ['tool call', 'tool calls']

// Mirrors the verbs of lib/toolPhrase.ts, as the nouns a person would use
// when asked "what did it do?". Tools that share a noun share the object,
// so they count as one group.
const TOOL_NOUNS: Record<string, Noun> = {
  browser_click: BROWSER,
  browser_navigate: BROWSER,
  browser_type: BROWSER,
  clarify: ['question', 'questions'],
  delegate_task: ['subagent', 'subagents'],
  execute_code: COMMAND,
  image_generate: IMAGE,
  memory: ['memory update', 'memory updates'],
  patch: ['edit', 'edits'],
  read_file: ['file read', 'files read'],
  search_files: SEARCH,
  session_search: SEARCH,
  skill_view: ['skill read', 'skills read'],
  terminal: COMMAND,
  todo: ['plan update', 'plan updates'],
  vision_analyze: IMAGE,
  web_extract: ['page read', 'pages read'],
  web_search: SEARCH,
  write_file: ['file written', 'files written']
}

// At most this many groups are spelled out; the rest fold into "+N more".
const MAX_GROUPS = 3

// Under ten seconds a turn is quick enough that tenths matter ("3.6s");
// beyond that the status rule's clock format ("59m 59s") reads better.
export const fmtTurnDuration = (ms: number): string => {
  const clamped = Math.max(0, ms)

  return clamped < 10_000 ? `${(clamped / 1000).toFixed(1)}s` : fmtDuration(clamped)
}

// "10:39 PM" in the person's locale; the receipt is a timestamp, not a
// stopwatch, so it uses wall-clock time.
export const fmtClock = (at: number): string =>
  new Date(at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })

export const summarizeTools = (toolNames: readonly string[]): string[] => {
  const counts = new Map<Noun, number>()

  for (const name of toolNames) {
    const noun = TOOL_NOUNS[name] ?? OTHER_NOUN
    counts.set(noun, (counts.get(noun) ?? 0) + 1)
  }

  const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0][0].localeCompare(b[0][0]))
  const groups = ranked.map(([noun, n]) => `${n} ${n === 1 ? noun[0] : noun[1]}`)

  if (groups.length <= MAX_GROUPS) {
    return groups
  }

  // Calls in the groups that were not spelled out.
  const rest = ranked.slice(MAX_GROUPS).reduce((sum, [, n]) => sum + n, 0)

  return [...groups.slice(0, MAX_GROUPS), `+${rest} more`]
}

export interface TurnReceiptInput {
  endedAt: number
  // What the end-of-turn check found ("checked 3 statements against 2
  // sources: confirmed"); it explains the time between the answer and the
  // receipt.
  note?: string
  startedAt?: null | number
  toolNames: readonly string[]
}

export const turnReceipt = ({ endedAt, note = '', startedAt, toolNames }: TurnReceiptInput): string =>
  [
    startedAt != null ? fmtTurnDuration(endedAt - startedAt) : '',
    ...summarizeTools(toolNames),
    note.trim(),
    fmtClock(endedAt)
  ]
    .filter(Boolean)
    .join(' · ')
