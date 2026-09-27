import { PassThrough } from 'stream'

import { renderSync } from '@robo/ink'
import React from 'react'
import { describe, expect, it } from 'vitest'

import { PRODUCT_NAME } from '../brand.js'
import { SessionPanel, updateNotice } from '../components/branding.js'
import { DEFAULT_THEME } from '../theme.js'
import type { SessionInfo } from '../types.js'

// Invariant under test: the session panel tells the user an update exists
// whenever the backend says so. The backend reports -1 for "behind by an
// amount I can't count", which is the normal answer for the shallow clones
// the install scripts make. The panel used to show the line only for counts
// above zero, so those users were never told.

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

const info = (update_behind: number | null | undefined): SessionInfo => ({
  model: 'test-model',
  skills: { core: ['a'] },
  tools: { file: ['read_file'] },
  update_behind,
  update_command: 'robo update'
})

async function renderPanel(panelInfo: SessionInfo): Promise<string> {
  const streams = makeStreams()

  const instance = renderSync(React.createElement(SessionPanel, { info: panelInfo, sid: 'test', t: DEFAULT_THEME }), {
    patchConsole: false,
    stderr: streams.stderr as NodeJS.WriteStream,
    stdin: streams.stdin as NodeJS.ReadStream,
    stdout: streams.stdout as NodeJS.WriteStream
  })

  try {
    await delay(20)

    // eslint-disable-next-line no-control-regex
    return streams.capture().replace(/\u001b\[[0-9;]*m/g, '')
  } finally {
    instance.unmount()
    instance.cleanup()
  }
}

describe('updateNotice', () => {
  it('counts known updates', () => {
    expect(updateNotice(1)).toBe('↑ 1 update behind')
    expect(updateNotice(4)).toBe('↑ 4 updates behind')
  })

  it('still announces an update the backend could not count', () => {
    expect(updateNotice(-1)).toBe(`↑ A newer ${PRODUCT_NAME} is available`)
  })

  it('says nothing when current or unknown', () => {
    expect(updateNotice(0)).toBeNull()
    expect(updateNotice(null)).toBeNull()
    expect(updateNotice(undefined)).toBeNull()
    expect(updateNotice(Number.NaN)).toBeNull()
  })
})

describe('session panel update line', () => {
  it('shows the update line and the command for an uncountable update', async () => {
    const frame = await renderPanel(info(-1))

    expect(frame).toContain(`A newer ${PRODUCT_NAME} is available`)
    expect(frame).toContain('robo update')
  })

  it('shows the count when the backend has one', async () => {
    expect(await renderPanel(info(2))).toContain('2 updates behind')
  })

  it('shows nothing when up to date', async () => {
    const frame = await renderPanel(info(0))

    expect(frame).not.toContain('behind')
    expect(frame).not.toContain('is available')
  })
})
