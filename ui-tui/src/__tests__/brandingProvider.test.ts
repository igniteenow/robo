import { PassThrough } from 'stream'

import { renderSync } from '@robo/ink'
import React from 'react'
import { describe, expect, it } from 'vitest'

import { bannerProvider, SessionPanel } from '../components/branding.js'
import { DEFAULT_THEME } from '../theme.js'
import type { SessionInfo } from '../types.js'

// Invariant under test: the banner's "provider" cell names the provider the
// session runs on.
//
// Regression: the cell was read off the model slug's `vendor/` prefix only, so
// a model without one (`deepseek-v4-pro` on a custom messages-API-compatible
// endpoint) showed an empty "provider —" even though the gateway reports the
// session's provider.

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const makeStreams = (columns = 100) => {
  const stdout = new PassThrough()
  const stdin = new PassThrough()
  const stderr = new PassThrough()

  Object.assign(stdout, { columns, isTTY: false, rows: 40 })
  Object.assign(stdin, { isTTY: false })
  Object.assign(stderr, { isTTY: false })

  let captured = ''
  stdout.on('data', chunk => {
    captured += chunk.toString()
  })

  return { capture: () => captured, stderr, stdin, stdout }
}

const baseInfo = (over: Partial<SessionInfo>): SessionInfo => ({
  model: 'deepseek-v4-pro',
  skills: { core: ['a', 'b'] },
  tools: { file: ['read_file', 'write_file'] },
  ...over
})

async function renderBanner(info: SessionInfo): Promise<string> {
  const streams = makeStreams()

  const instance = renderSync(React.createElement(SessionPanel, { info, sid: 'test', t: DEFAULT_THEME }), {
    patchConsole: false,
    stderr: streams.stderr as NodeJS.WriteStream,
    stdin: streams.stdin as NodeJS.ReadStream,
    stdout: streams.stdout as NodeJS.WriteStream
  })

  try {
    await delay(20)

    // Strip ANSI so we can assert on the rendered text content.
    // eslint-disable-next-line no-control-regex
    return streams.capture().replace(/\u001b\[[0-9;]*m/g, '')
  } finally {
    instance.unmount()
    instance.cleanup()
  }
}

describe('banner provider cell', () => {
  it('keeps reading the vendor off a vendor/model slug', () => {
    expect(bannerProvider({ model: 'moonshotai/kimi-k2.5', provider: 'openrouter' })).toBe('moonshotai')
  })

  it('uses the session provider when the model has no vendor prefix', () => {
    expect(bannerProvider({ model: 'deepseek-v4-pro', provider: 'my-proxy' })).toBe('my-proxy')
    expect(bannerProvider({ model: 'deepseek-v4-pro', provider: '  my-proxy  ' })).toBe('my-proxy')
  })

  it('is empty when neither is known, so the cell falls back as before', () => {
    expect(bannerProvider({ model: 'deepseek-v4-pro' })).toBe('')
    expect(bannerProvider({ model: 'deepseek-v4-pro', provider: '   ' })).toBe('')
  })

  it('renders the session provider in the banner', async () => {
    const frame = await renderBanner(baseInfo({ provider: 'my-proxy' }))

    expect(frame).toContain('my-proxy')
  })
})
