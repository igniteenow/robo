import { PassThrough } from 'stream'

import { renderSync } from '@robo/ink'
import React from 'react'
import { describe, expect, it } from 'vitest'

import { ToolTrail } from '../components/thinking.js'
import { buildToolTrailLine, stripAnsi } from '../lib/text.js'
import { DEFAULT_THEME } from '../theme.js'

// While Robo works, the collapsed live area must say what it is doing in
// plain words — "Running npm test (12s)" — and not a token tally. Token
// counts are detail for an opened panel.

const settle = async () => {
  await new Promise(resolve => setImmediate(resolve))
  await new Promise(resolve => setImmediate(resolve))
}

async function render(element: React.ReactElement, cols = 80): Promise<string> {
  const stdout = new PassThrough()
  const stdin = new PassThrough()
  const stderr = new PassThrough()
  let output = ''

  Object.assign(stdout, { columns: cols, isTTY: false, rows: 30 })
  Object.assign(stdin, { isTTY: false })
  Object.assign(stderr, { isTTY: false })
  stdout.on('data', chunk => {
    output += chunk.toString()
  })

  const instance = renderSync(element, {
    patchConsole: false,
    stderr: stderr as NodeJS.WriteStream,
    stdin: stdin as NodeJS.ReadStream,
    stdout: stdout as NodeJS.WriteStream
  })

  await settle()
  instance.unmount()
  instance.cleanup()

  return stripAnsi(output)
}

const line = (text: string) => (frame: string) => frame.split('\n').find(row => row.includes(text)) ?? ''

describe('ToolTrail — what Robo is doing, in plain words', () => {
  it('collapsed: the header says what is running right now, with no token count', async () => {
    const frame = await render(
      <ToolTrail
        t={DEFAULT_THEME}
        tools={[{ context: 'npm test', id: 't1', name: 'terminal', startedAt: Date.now() - 12_500 }]}
        toolTokens={1234}
      />
    )

    const header = line('Tool calls')(frame)

    expect(header).toContain('▸ Tool calls (1)')
    expect(header).toMatch(/Running npm test \(1[23]s\)/)
    expect(frame).not.toContain('Terminal("npm test")')
    expect(frame).not.toContain('tokens')
  })

  it('collapsed: a finished turn keeps its one-line header, still without tokens', async () => {
    const frame = await render(
      <ToolTrail
        reasoning="Looked at the failing test first."
        reasoningTokens={900}
        t={DEFAULT_THEME}
        toolTokens={1234}
        trail={[buildToolTrailLine('terminal', 'npm test', false, 'ok', 1.2)]}
      />
    )

    expect(line('Tool calls')(frame)).toContain('▸ Tool calls (1)')
    expect(line('Thinking')(frame)).toContain('▸ Thinking')
    expect(frame).not.toContain('tokens')
    expect(frame).not.toContain('total')
  })

  it('expanded: rows read as plain past-tense steps, and the token detail comes back', async () => {
    const frame = await render(
      <ToolTrail
        reasoning="Looked at the failing test first."
        reasoningTokens={900}
        sections={{ thinking: 'expanded', tools: 'expanded' }}
        t={DEFAULT_THEME}
        tools={[{ context: 'src/app.ts', id: 't2', name: 'read_file', startedAt: Date.now() }]}
        toolTokens={1234}
        trail={[
          buildToolTrailLine('terminal', 'npm test', false, 'ok', 1.2),
          buildToolTrailLine('web_search', 'vite 8 notes', true, 'network down', 0.4),
          buildToolTrailLine('mcp_filesystem_list_directory', '/tmp', false, '', 0.1)
        ]}
      />
    )

    expect(frame).toContain('Ran npm test')
    expect(frame).toContain('Searched the web for vite 8 notes')
    expect(frame).toContain('Reading src/app.ts')
    // No curated verb: the raw label stays, so nothing is mangled.
    expect(frame).toContain('Mcp Filesystem List Directory("/tmp")')
    expect(frame).not.toContain('Terminal("npm test")')
    expect(frame).toContain('~1.2k tokens')
    expect(frame).toContain('~900 tokens')
  })

  it('display.friendly_tool_labels: false brings the raw labels back', async () => {
    const frame = await render(
      <ToolTrail
        friendlyToolLabels={false}
        sections={{ tools: 'expanded' }}
        t={DEFAULT_THEME}
        tools={[{ context: 'npm test', id: 't1', name: 'terminal', startedAt: Date.now() }]}
        trail={[buildToolTrailLine('read_file', 'x', false, '', 0.9)]}
      />
    )

    expect(frame).toContain('Terminal("npm test")')
    expect(frame).toContain('Read File("x")')
    expect(frame).not.toContain('Running npm test')
  })
})
