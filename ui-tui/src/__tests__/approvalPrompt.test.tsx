import { PassThrough } from 'stream'

import { renderSync } from '@robo/ink'
import React from 'react'
import { describe, expect, it, vi } from 'vitest'

const inputHarness = vi.hoisted(() => ({
  handler: undefined as undefined | ((input: string, key: Record<string, boolean>) => void)
}))

// Stub useInput so the prompt doesn't try to enter raw mode under renderSync
// (PassThrough stdin doesn't support it). Box/Text pass through to real Ink.
vi.mock('@robo/ink', async importOriginal => {
  const mod = await importOriginal()

  return {
    ...mod,
    useInput: (handler: (input: string, key: Record<string, boolean>) => void) => {
      inputHarness.handler = handler
    }
  }
})

import { approvalHeading, ApprovalPrompt } from '../components/prompts.js'
import { stripAnsi } from '../lib/text.js'
import { DEFAULT_THEME } from '../theme.js'
import type { ApprovalReq } from '../types.js'

const t = DEFAULT_THEME

function render(req: ApprovalReq, onChoice: (choice: string) => void = () => {}): string {
  const stdout = new PassThrough()
  const stdin = new PassThrough()
  const stderr = new PassThrough()

  let output = ''

  Object.assign(stdout, { columns: 100, isTTY: false, rows: 40 })
  Object.assign(stdin, { isTTY: false })
  Object.assign(stderr, { isTTY: false })
  stdout.on('data', chunk => {
    output += chunk.toString()
  })

  inputHarness.handler = undefined

  const instance = renderSync(React.createElement(ApprovalPrompt, { cols: 100, onChoice, req, t }), {
    patchConsole: false,
    stderr: stderr as NodeJS.WriteStream,
    stdin: stdin as NodeJS.ReadStream,
    stdout: stdout as NodeJS.WriteStream
  })

  instance.unmount()
  instance.cleanup()

  return stripAnsi(output)
}

const COMMAND: ApprovalReq = {
  command: 'git push --force origin main',
  description: 'git force push (rewrites remote history)'
}

describe('approvalHeading — the question matches the request shape', () => {
  it('asks about a shell command by default', () => {
    expect(approvalHeading(COMMAND).title).toBe('Allow Robo to run this command?')
    expect(approvalHeading(COMMAND).labels.once).toBe('Allow once')
  })

  it('asks about a script for execute_code', () => {
    expect(approvalHeading({ ...COMMAND, command: "execute_code <<'PY'\nprint(1)\nPY" }).title).toBe(
      'Allow Robo to run this script?'
    )
  })

  it('names the tool for a plugin approval rule', () => {
    expect(approvalHeading({ ...COMMAND, command: '<write_file> (plugin approval rule)' }).title).toBe(
      'Allow Robo to use write_file?'
    )
  })

  it('uses correction words for a fact-check correction', () => {
    const heading = approvalHeading({ ...COMMAND, kind: 'correction' })

    expect(heading.title).toBe("Apply Robo's correction to the answer?")
    expect(heading.labels).toEqual({
      deny: 'Keep answer',
      once: 'Apply correction',
      session: 'Apply corrections this session'
    })
  })
})

describe('ApprovalPrompt — organized card', () => {
  it('shows the question, the reason, the command and the three numbered choices', () => {
    const out = render(COMMAND)

    expect(out).toContain('Allow Robo to run this command?')
    expect(out).toContain('git force push (rewrites remote history)')
    expect(out).toContain('git push --force origin main')
    expect(out).toMatch(/❯ 1\s+Allow once/)
    expect(out).toMatch(/2\s+Allow for this session/)
    expect(out).toMatch(/3\s+Deny/)
    expect(out).toContain('Esc deny')
    // No context rows when the gateway sent none.
    expect(out).not.toMatch(/│\s+Robo\s{2,}/)
    expect(out).not.toContain('Check')
    expect(out).not.toContain('Review')
  })

  it('renders the intent, review and check rows when the gateway sends them', () => {
    const out = render({
      ...COMMAND,
      check: 'Rewrites or discards git history — unpushed or shared work can be lost.',
      intent: 'Pushing the branch so the PR can be opened.',
      review: "Robo's reviewer could not clear this on its own: it rewrites main."
    })

    expect(out).toMatch(/Robo\s+Pushing the branch so the PR can be opened\./)
    expect(out).toMatch(/Review\s+Robo's reviewer could not clear this on its own: it rewrites main\./)
    expect(out).toMatch(/Check\s+Rewrites or discards git history/)
    // Order: what Robo said, then the reviewer, then what to check.
    expect(out.indexOf('Pushing the branch')).toBeLessThan(out.indexOf('reviewer could not'))
    expect(out.indexOf('reviewer could not')).toBeLessThan(out.indexOf('Rewrites or discards'))
  })

  it('keeps the long-command preview bounded and says how much is hidden', () => {
    const out = render({ ...COMMAND, command: Array.from({ length: 14 }, (_, i) => `line ${i + 1}`).join('\n') })

    expect(out).toContain('line 10')
    expect(out).not.toContain('line 11')
    expect(out).toContain('+4 more lines')
  })

  it('wraps a wide command instead of clipping its tail', () => {
    const out = render({ ...COMMAND, command: `rm -rf ${'/very/long/path'.repeat(12)}` })

    expect(out).toContain('/very/long/path')
    // The tail of the command is still on screen (it wrapped, not clipped).
    expect(out.replace(/[\s│]+/g, '')).toContain('/very/long/path'.repeat(12))
  })

  it('shows the correction wording and hides the command-oriented check row', () => {
    const out = render({
      check: 'Check the command and the paths it touches before allowing it.',
      command: 'Answer says: the port is 8080\nSource says: config.yaml sets 9090',
      description: "Correction proposed: Robo's research disagrees with 1 statement in the answer.",
      kind: 'correction'
    })

    expect(out).toContain("Apply Robo's correction to the answer?")
    expect(out).toContain('Answer says: the port is 8080')
    expect(out).toMatch(/1\s+Apply correction/)
    expect(out).toMatch(/3\s+Keep answer/)
    expect(out).toContain('Esc keep')
    expect(out).not.toContain('Check the command')
  })

  it('number keys and Esc still resolve the prompt the same way', () => {
    const chosen: string[] = []

    render(COMMAND, choice => chosen.push(choice))
    inputHarness.handler?.('2', {})
    inputHarness.handler?.('', { escape: true })

    expect(chosen).toEqual(['session', 'deny'])
  })
})
