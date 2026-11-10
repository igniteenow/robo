import { PassThrough } from 'stream'

import { renderSync } from '@robo/ink'
import React from 'react'
import { describe, expect, it } from 'vitest'

import { fmtElapsed, LIVE_STEPS_MAX, ToolTrail } from '../components/thinking.js'
import { ANALYZING_TRAIL_LINE, buildToolTrailLine, stripAnsi, tailPreview } from '../lib/text.js'
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
  // Each write is one full frame (spinners repaint while the test settles,
  // and unmount paints a blank one); the newest frame with content counts.
  let output = ''

  Object.assign(stdout, { columns: cols, isTTY: false, rows: 30 })
  Object.assign(stdin, { isTTY: false })
  Object.assign(stderr, { isTTY: false })
  stdout.on('data', chunk => {
    const frame = stripAnsi(chunk.toString())

    if (frame.trim()) {
      output = frame
    }
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

  return output
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

// While the turn runs with the tools section collapsed (the default), the
// steps of the working phase draw as a live list — every call with its ✓/✗
// and how long it took, the running one with a clock, then what Robo is
// doing between calls — so a person following a twenty-minute task sees
// each command as it happens, not a "Tool calls (7)" row that only counts.

const rowsOf = (frame: string) =>
  frame
    .split('\n')
    .map(row => row.trim())
    .filter(Boolean)

describe('ToolTrail — the live list of steps', () => {
  const steps = [
    buildToolTrailLine('search_files', 'PORT', false, '', 0.4),
    buildToolTrailLine('read_file', 'config.yaml', false, '', 0.1),
    buildToolTrailLine('terminal', 'npm test', true, 'exit 1', 14.2),
    buildToolTrailLine('patch', 'src/app.ts', false, '', 0.3)
  ]

  it('lists every step so far with its result, and the running one with its clock', async () => {
    const frame = await render(
      <ToolTrail
        live
        t={DEFAULT_THEME}
        tools={[{ context: 'npm test', id: 't5', name: 'terminal', startedAt: Date.now() - 12_500 }]}
        trail={steps}
      />
    )

    const rows = rowsOf(frame)

    expect(rows[0]).toContain('▾ Working  5 steps')
    expect(rows[1]).toMatch(/✓ Searched files for PORT \(0\.4s\)$/)
    expect(rows[2]).toMatch(/✓ Read config\.yaml \(0\.1s\)$/)
    expect(rows[3]).toMatch(/✗ Ran npm test \(14s\) — exit 1$/)
    expect(rows[4]).toMatch(/✓ Edited src\/app\.ts \(0\.3s\)$/)
    expect(rows[5]).toMatch(/Running npm test \(1[23]s\)$/)
    expect(frame).not.toContain('Tool calls')
    expect(frame).not.toContain('tokens')
  })

  it('says what Robo is doing between calls, and while it drafts the next one', async () => {
    const thinking = await render(<ToolTrail live phase="thinking…" t={DEFAULT_THEME} trail={steps} />)

    expect(rowsOf(thinking).at(-1)).toMatch(/thinking…$/)

    const analyzing = await render(<ToolTrail live phase={ANALYZING_TRAIL_LINE} t={DEFAULT_THEME} trail={steps} />)

    expect(rowsOf(analyzing).at(-1)).toMatch(/analyzing tool output…$/)

    const drafting = await render(
      <ToolTrail live phase="thinking…" t={DEFAULT_THEME} trail={[...steps, 'drafting terminal…']} />
    )

    const rows = rowsOf(drafting)

    expect(rows.at(-1)).toMatch(/Running…$/)
    expect(drafting).not.toContain('thinking…')
    expect(rows[0]).toContain('5 steps')
  })

  it('folds older steps into one row so a long task stays a short block', async () => {
    const many = Array.from({ length: LIVE_STEPS_MAX + 4 }, (_, i) =>
      buildToolTrailLine('read_file', `file-${i}.ts`, false, '', 0.2)
    )

    const frame = await render(<ToolTrail live t={DEFAULT_THEME} trail={many} />)
    const rows = rowsOf(frame)

    expect(rows[0]).toContain(`${many.length} steps`)
    expect(rows[1]).toContain('… 4 earlier steps')
    expect(rows).toHaveLength(2 + LIVE_STEPS_MAX)
    expect(frame).not.toContain('file-3.ts')
    expect(frame).toContain('file-4.ts')
    expect(frame).toContain(`file-${many.length - 1}.ts`)
  })

  it('reads a long command the way the clock does', async () => {
    const frame = await render(
      <ToolTrail live t={DEFAULT_THEME} trail={[buildToolTrailLine('terminal', 'npm run build', false, '', 70.2)]} />
    )

    expect(frame).toContain('Ran npm run build (1m 10s)')
    expect(fmtElapsed(70_200)).toBe('1m 10s')
    expect(fmtElapsed(120_000)).toBe('2m')
    expect(fmtElapsed(9_400)).toBe('9.4s')
  })

  it('keeps the folded row when the section is expanded, hidden, or the turn is over', async () => {
    const settled = await render(<ToolTrail t={DEFAULT_THEME} trail={steps} />)

    expect(settled).toContain('▸ Tool calls (4)')
    expect(settled).not.toContain('Working')

    const expanded = await render(<ToolTrail live sections={{ tools: 'expanded' }} t={DEFAULT_THEME} trail={steps} />)

    expect(expanded).toContain('▾ Tool calls (4)')
    expect(expanded).toContain('Ran npm test')
    expect(expanded).not.toContain('Working')

    const hidden = await render(<ToolTrail live sections={{ tools: 'hidden' }} t={DEFAULT_THEME} trail={steps} />)

    expect(hidden).not.toContain('Working')
    expect(hidden).not.toContain('Tool calls')
  })

  it('collapsed Thinking shows the tail of the reasoning while the model writes it', async () => {
    const reasoning =
      'The user wants the port. Let me look at the config files first, then grep for PORT and read config.yaml.'

    const live = await render(<ToolTrail reasoning={reasoning} reasoningActive t={DEFAULT_THEME} />, 120)

    expect(line('Thinking')(live)).toMatch(
      /▸ Thinking\s+\S …at the config files first, then grep for PORT and read config\.yaml\.$/
    )

    const settled = await render(<ToolTrail reasoning={reasoning} t={DEFAULT_THEME} />, 120)

    expect(line('Thinking')(settled).trim()).toMatch(/▸ Thinking$/)
    expect(tailPreview('one two three', 20)).toBe('one two three')
    expect(tailPreview('alpha beta gamma delta epsilon', 12)).toBe('…epsilon')
  })
})
