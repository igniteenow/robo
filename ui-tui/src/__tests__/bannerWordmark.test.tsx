import { PassThrough } from 'stream'

import { renderSync } from '@robo/ink'
import React from 'react'
import { describe, expect, it } from 'vitest'

import { Banner, FLAME, WORDMARK, WORDMARK_SHORT } from '../components/branding.js'
import { stripAnsi } from '../lib/text.js'
import { DEFAULT_THEME } from '../theme.js'

const settle = async () => {
  for (let i = 0; i < 4; i++) {
    await new Promise(resolve => setImmediate(resolve))
  }
}

async function banner(cols: number): Promise<string> {
  const stdout = new PassThrough()
  const stdin = new PassThrough()
  const stderr = new PassThrough()
  let output = ''

  Object.assign(stdout, { columns: cols, isTTY: false, rows: 40 })
  Object.assign(stdin, { isTTY: false })
  Object.assign(stderr, { isTTY: false })
  stdout.on('data', chunk => {
    const text = stripAnsi(chunk.toString())

    if (text.trim()) {
      output = text
    }
  })

  // The banner reads the real terminal's width (process.stdout), then caps it
  // at maxWidth.
  const realColumns = process.stdout.columns

  Object.defineProperty(process.stdout, 'columns', { configurable: true, value: cols, writable: true })

  const instance = renderSync(<Banner maxWidth={cols} t={DEFAULT_THEME} />, {
    patchConsole: false,
    stderr: stderr as unknown as NodeJS.WriteStream,
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream
  })

  await settle()
  instance.unmount()
  instance.cleanup()
  Object.defineProperty(process.stdout, 'columns', { configurable: true, value: realColumns, writable: true })

  return output
}

describe('the banner wordmark', () => {
  it('has one shade per row, and both wordmarks are rectangular', () => {
    expect(WORDMARK).toHaveLength(FLAME.length)
    expect(WORDMARK_SHORT).toHaveLength(FLAME.length)
    expect(new Set(WORDMARK.map(row => row.length)).size).toBe(1)
    expect(WORDMARK[0]!.length).toBeGreaterThan(WORDMARK_SHORT[1]!.length)
  })

  it('draws ROBO-AGENT when the window is wide enough', async () => {
    const out = await banner(120)

    expect(out).toContain(WORDMARK[1]!.trimEnd())
    expect(out).toContain('autonomous engineering agent')
  })

  it('falls back to the short ROBO wordmark on a narrower window', async () => {
    const out = await banner(60)

    expect(out).toContain(WORDMARK_SHORT[1]!)
    expect(out).not.toContain(WORDMARK[1]!.trimEnd())
  })

  it('falls back to one line when even the short wordmark does not fit', async () => {
    const out = await banner(30)

    expect(out).toContain('ROBO')
    expect(out).not.toContain(WORDMARK_SHORT[1]!)
  })
})
