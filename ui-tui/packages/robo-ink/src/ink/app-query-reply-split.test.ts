/**
 * A terminal's reply to one of our own queries (the mouse watchdog's DECRQM
 * + DA1, the startup probes) travels on stdin like keystrokes, and a link
 * can split it anywhere — SSH and conpty do, right after the ESC included.
 * The ESC on its own used to be flushed as the Escape key and the rest of
 * the reply typed into the input as `[?1000;2$y[?61;4;6;7;...;52c`.
 */
import { EventEmitter } from 'events'

import React, { useContext, useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import StdinContext from './components/StdinContext.js'
import Text from './components/Text.js'
import useInput from './hooks/use-input.js'
import Ink from './ink.js'
import instances from './instances.js'
import { parseMultipleKeypresses } from './parse-keypress.js'
import { csi } from './termio/csi.js'
import { DEC } from './termio/dec.js'

const DECRQM_1000 = csi(`?${DEC.MOUSE_NORMAL}$p`)
const DECRPM_1000_SET = csi(`?${DEC.MOUSE_NORMAL};1$y`)
// What Windows Terminal answers.
const DA1_REPLY = csi('?61;4;6;7;14;21;22;23;24;28;32;42;52c')
const TICK_MS = 10_000

class FakeStdout extends EventEmitter {
  chunks: string[] = []
  columns = 80
  rows = 24
  isTTY = true

  write(chunk: string | Uint8Array, cb?: (err?: Error | null) => void): boolean {
    this.chunks.push(typeof chunk === 'string' ? chunk : Buffer.from(chunk).toString('utf8'))
    cb?.()

    return true
  }
}

class FakeStdin extends EventEmitter {
  isTTY = true
  isRaw = false
  private buffer: string[] = []

  get readableLength(): number {
    return this.buffer.reduce((n, c) => n + c.length, 0)
  }

  ref(): void {}
  unref(): void {}
  setEncoding(): this {
    return this
  }
  setRawMode(mode: boolean): this {
    this.isRaw = mode

    return this
  }
  read(): string | null {
    return this.buffer.shift() ?? null
  }
  feed(data: string): void {
    this.buffer.push(data)
    this.emit('readable')
  }
}

const seen: Array<{ input: string; escape: boolean }> = []

function Consumer() {
  const { setRawMode, isRawModeSupported } = useContext(StdinContext)

  useEffect(() => {
    if (!isRawModeSupported) {
      return
    }

    setRawMode(true)

    return () => setRawMode(false)
  }, [isRawModeSupported, setRawMode])

  useInput((input, key) => {
    seen.push({ escape: key.escape, input })
  })

  return React.createElement(Text, null, 'x')
}

const settle = async () => {
  await new Promise<void>(resolve => setImmediate(resolve))
  await new Promise<void>(resolve => setImmediate(resolve))
}

// Real time: the incomplete-sequence flush is a real 50 ms timer.
const wait = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms))

async function mount() {
  const stdout = new FakeStdout()
  const stdin = new FakeStdin()

  const ink = new Ink({
    exitOnCtrlC: false,
    patchConsole: false,
    stderr: new FakeStdout() as unknown as NodeJS.WriteStream,
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream
  })

  instances.set(stdout as unknown as NodeJS.WriteStream, ink)
  ink.setAltScreenActive(true, 'all')
  ink.render(React.createElement(Consumer))
  ink.onRender()
  await settle()
  // Answer the startup probes' sentinel so nothing is pending.
  stdin.feed(DA1_REPLY)
  await settle()
  stdout.chunks = []
  seen.length = 0

  return { ink, stdin, stdout }
}

describe('a query reply split after its ESC', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('is held together while the reply is owed, then routed as a reply — no Escape, no digits', async () => {
    const h = await mount()

    // The watchdog asks; the terminal now owes two replies.
    await vi.advanceTimersByTimeAsync(TICK_MS)
    expect(h.stdout.chunks.join('')).toContain(DECRQM_1000)

    // The ESC of the first reply arrives alone and the 50 ms flush passes...
    h.stdin.feed('\x1b')
    await wait(80)
    await settle()
    expect(seen).toEqual([])

    // ...then the rest, and the second reply split the same way.
    h.stdin.feed(DECRPM_1000_SET.slice(1))
    await settle()
    h.stdin.feed('\x1b')
    await wait(80)
    await settle()
    h.stdin.feed(DA1_REPLY.slice(1))
    await settle()

    expect(seen).toEqual([])

    h.ink.unmount()
  })

  it('still delivers a real Escape press once nothing is owed', async () => {
    const h = await mount()

    h.stdin.feed('\x1b')
    await wait(80)
    await settle()

    expect(seen.map(k => k.escape)).toEqual([true])

    h.ink.unmount()
  })

  it('gives up holding when the terminal never answers, and only delays one Escape', async () => {
    const h = await mount()

    await vi.advanceTimersByTimeAsync(TICK_MS)
    h.stdin.feed('\x1b')
    await wait(80)
    await settle()
    // Held so far...
    expect(seen).toEqual([])
    // ...until the hold runs out (Date is faked: move it past the bound).
    vi.setSystemTime(Date.now() + 1500)
    await wait(80)
    await settle()
    expect(seen.map(k => k.escape)).toEqual([true])

    // Still owed, but the hold was spent: the next lone ESC is prompt.
    seen.length = 0
    h.stdin.feed('\x1b')
    await wait(80)
    await settle()
    expect(seen.map(k => k.escape)).toEqual([true])

    h.ink.unmount()
  })
})

describe('a reply tail that lost its ESC', () => {
  it('is parsed as the reply, never typed', () => {
    const tails = [DECRPM_1000_SET.slice(1), DA1_REPLY.slice(1), csi('>0;276;0c').slice(1), csi('?1u').slice(1)]

    for (const tail of tails) {
      const [keys] = parseMultipleKeypresses({ incomplete: '', mode: 'NORMAL', pasteBuffer: '' } as never, tail)

      expect(
        keys.map(k => k.kind),
        tail
      ).toEqual(['response'])
    }
  })

  it('leaves ordinary text alone', () => {
    for (const text of ['[?', '[hello]', '[1;2c', 'c', '$y']) {
      const [keys] = parseMultipleKeypresses({ incomplete: '', mode: 'NORMAL', pasteBuffer: '' } as never, text)

      expect(
        keys.every(k => k.kind === 'key'),
        text
      ).toBe(true)
    }
  })
})
