import { describe, expect, it } from 'vitest'

import { padVerb, VERB_PAD_LEN } from '../components/appChrome.js'
import { buildToolTrailLine, formatToolCall, parseToolTrailResultLine } from '../lib/text.js'
import {
  describeToolCall,
  friendlyToolCall,
  liveActivityVerb,
  PHASE_VERBS,
  STATUS_VERB_MAX,
  TOOL_PHRASES
} from '../lib/toolPhrase.js'

// Tool rows and the status bar say what Robo is doing in plain words
// ("Running npm test", "running…") instead of the protocol's tool names and
// token counts. The stored trail lines keep their `Label("preview")` form,
// so this is a render-time translation that must round-trip them exactly.

describe('describeToolCall', () => {
  it('phrases a built-in tool in the present tense while it runs, past tense once done', () => {
    expect(describeToolCall('terminal', 'npm test')).toBe('Running npm test')
    expect(describeToolCall('terminal', 'npm test', true)).toBe('Ran npm test')
    expect(describeToolCall('read_file', 'src/app.ts')).toBe('Reading src/app.ts')
    expect(describeToolCall('write_file', 'README.md', true)).toBe('Wrote README.md')
    expect(describeToolCall('patch', 'src/app.ts')).toBe('Editing src/app.ts')
  })

  it('uses "for" with the searches and no preview where it adds nothing', () => {
    expect(describeToolCall('web_search', 'vite 8 release notes')).toBe('Searching the web for vite 8 release notes')
    expect(describeToolCall('search_files', 'TODO', true)).toBe('Searched files for TODO')
    expect(describeToolCall('execute_code', 'import os\nprint(1)')).toBe('Running code')
    expect(describeToolCall('todo', '{"todos": []}', true)).toBe('Updated the plan')
    expect(describeToolCall('clarify', 'Which one?')).toBe('Asking you')
  })

  it('keeps the raw label for tools without a curated verb, exactly as the trail does', () => {
    expect(describeToolCall('mcp_filesystem_list_directory', '/tmp')).toBe(
      formatToolCall('mcp_filesystem_list_directory', '/tmp')
    )
    expect(describeToolCall('my_plugin_tool', '')).toBe('My Plugin Tool')
  })

  it('falls back to the raw label everywhere when friendly labels are off', () => {
    expect(describeToolCall('terminal', 'npm test', false, false)).toBe('Terminal("npm test")')
    expect(describeToolCall('terminal', '', true, false)).toBe('Terminal')
  })

  it('shortens a long argument the same way the raw label does', () => {
    const long = 'x'.repeat(200)
    const phrased = describeToolCall('read_file', long)

    expect(phrased.startsWith('Reading ')).toBe(true)
    expect(phrased.length).toBeLessThan(90)
    expect(phrased).toContain('…')
  })
})

describe('friendlyToolCall (stored trail lines)', () => {
  it('re-phrases the call part of a finished trail line and keeps its duration', () => {
    const line = buildToolTrailLine('terminal', 'npm test', false, 'ok', 1.26)
    const parsed = parseToolTrailResultLine(line)!

    expect(parsed.call).toBe('Terminal("npm test") (1.3s)')
    expect(friendlyToolCall(parsed.call)).toBe('Ran npm test (1.3s)')
    expect(friendlyToolCall('Read File("x")')).toBe('Read x')
    expect(friendlyToolCall('Web Search("robo tui") (0.5s)')).toBe('Searched the web for robo tui (0.5s)')
    expect(friendlyToolCall('Skills List')).toBe('Listed skills')
  })

  it('leaves unknown tools, legacy lines and odd shapes untouched', () => {
    expect(friendlyToolCall('Mcp Filesystem Read File("/etc/hosts") (0.1s)')).toBe(
      'Mcp Filesystem Read File("/etc/hosts") (0.1s)'
    )
    expect(friendlyToolCall('terminal: npm test')).toBe('terminal: npm test')
    expect(friendlyToolCall('')).toBe('')
    expect(friendlyToolCall('Terminal("npm test")', true, false)).toBe('Terminal("npm test")')
  })

  it('survives quotes and parentheses inside the argument', () => {
    const call = formatToolCall('terminal', 'echo "hi (there)"')

    expect(friendlyToolCall(call, false)).toBe('Running echo "hi (there)"')
  })

  it('agrees with describeToolCall for every curated tool', () => {
    for (const name of Object.keys(TOOL_PHRASES)) {
      expect(friendlyToolCall(formatToolCall(name, 'arg'), true)).toBe(describeToolCall(name, 'arg', true))
      expect(friendlyToolCall(formatToolCall(name, ''), false)).toBe(describeToolCall(name, '', false))
    }
  })
})

describe('liveActivityVerb (status bar)', () => {
  it('names the running tool, then the answer, then thinking', () => {
    expect(liveActivityVerb({ tools: [{ name: 'terminal' }] })).toBe('running')
    expect(liveActivityVerb({ tools: [{ name: 'read_file' }, { name: 'web_search' }] })).toBe('searching')
    expect(liveActivityVerb({ tools: [{ name: 'some_mcp_tool' }] })).toBe(PHASE_VERBS.tool)
    expect(liveActivityVerb({ streaming: 'The fix is' })).toBe(PHASE_VERBS.answering)
    expect(liveActivityVerb({})).toBe(PHASE_VERBS.thinking)
    expect(liveActivityVerb({ streaming: '' })).toBe(PHASE_VERBS.thinking)
  })

  it('every verb fits the fixed status-bar slot', () => {
    const verbs = [...Object.values(TOOL_PHRASES).map(p => p.verb), ...Object.values(PHASE_VERBS)]

    for (const verb of verbs) {
      expect(verb.length).toBeLessThanOrEqual(STATUS_VERB_MAX)
      expect(padVerb(verb)).toHaveLength(VERB_PAD_LEN)
      expect(padVerb(verb).startsWith(`${verb}…`)).toBe(true)
    }
  })
})
