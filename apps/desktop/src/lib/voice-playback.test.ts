import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $voicePlayback } from '@/store/voice-playback'

import {
  SPEECH_STREAM_OPEN_TIMEOUT_MS,
  SPEECH_STREAM_STALL_MS,
  startSpeechStream,
  stopVoicePlayback
} from './voice-playback'

// The live speech session: text in over one WebSocket, audio out. Two shapes
// of audio: raw PCM frames from a chunked provider, or — for Edge and every
// other provider with no PCM API — one complete audio file per sentence,
// decoded in order and queued back to back, so the first sentence plays
// while the model is still writing the next.

vi.mock('@robo/shared', () => ({
  resolveGatewayWsUrl: async () => 'ws://127.0.0.1:9119/api/ws'
}))

vi.mock('@/robo', () => ({
  getApiRequestProfile: () => null,
  speakText: vi.fn()
}))

class FakeSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static instances: FakeSocket[] = []
  binaryType = ''
  readyState = FakeSocket.CONNECTING
  sent: string[] = []
  closed = false
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: { data: ArrayBuffer | string }) => void) | null = null
  onopen: (() => void) | null = null

  constructor(readonly url: string) {
    FakeSocket.instances.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.closed = true
  }

  open() {
    this.readyState = FakeSocket.OPEN
    this.onopen?.()
  }

  json(frame: object) {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }

  bytes(length: number) {
    this.onmessage?.({ data: new ArrayBuffer(length) })
  }
}

class FakeContext {
  static instances: FakeContext[] = []
  currentTime = 0
  state = 'running'
  destination = {}
  decoded: ArrayBuffer[] = []
  starts: number[] = []
  created: number[] = []

  constructor() {
    FakeContext.instances.push(this)
  }

  async decodeAudioData(data: ArrayBuffer) {
    this.decoded.push(data)

    return { duration: 1.5 }
  }

  createBuffer(_channels: number, length: number, _rate: number) {
    this.created.push(length)

    return { duration: length / 24_000, getChannelData: () => new Float32Array(length) }
  }

  createBufferSource() {
    const context = this

    return {
      buffer: null as null | { duration: number },
      connect() {},
      start(at: number) {
        context.starts.push(at)
      }
    }
  }

  async close() {}
}

const flush = async () => {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve()
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeSocket.instances = []
  FakeContext.instances = []
  vi.stubGlobal('WebSocket', FakeSocket)
  vi.stubGlobal('AudioContext', FakeContext)
  Object.defineProperty(window, 'roboDesktop', {
    configurable: true,
    value: { getConnection: async () => ({}) }
  })
})

afterEach(() => {
  stopVoicePlayback()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

async function openSession() {
  const session = await startSpeechStream({ source: 'voice-conversation' })

  expect(session).not.toBeNull()

  const ws = FakeSocket.instances[0]

  ws.open()

  return { session: session!, ws }
}

describe('startSpeechStream', () => {
  it('asks the backend for per-sentence encoded audio', async () => {
    const { ws } = await openSession()

    expect(ws.url).toContain('/api/audio/speak-stream')
    expect(ws.url).toContain('encoded=1')
  })

  it('decodes one file per sentence, in order, back to back — and speaks from the first', async () => {
    const { session, ws } = await openSession()

    session.append('First sentence. ')
    session.append('Second one.')
    session.finish()
    expect(ws.sent.map(s => JSON.parse(s))).toEqual([
      { text: 'First sentence. ' },
      { text: 'Second one.' },
      { done: true }
    ])

    ws.json({ type: 'start', format: 'encoded' })

    const context = FakeContext.instances[0]

    ws.bytes(10)
    ws.bytes(20)
    await flush()

    expect(context.decoded.map(d => d.byteLength)).toEqual([10, 20])
    // Queued right after each other: the second starts when the first ends.
    expect(context.starts).toEqual([0.05, 1.55])
    expect(context.created).toEqual([])
    expect($voicePlayback.get().status).toBe('speaking')

    ws.json({ type: 'end' })
    await flush()
    // Drains: the last buffer ends at 3.05 s on a context clock still at 0.
    vi.advanceTimersByTime(3_200)
    await flush()
    expect(await session.done).toBe('done')
    expect(ws.closed).toBe(true)
  })

  it('keeps raw PCM frames on the PCM path', async () => {
    const { ws } = await openSession()

    ws.json({ type: 'start', sample_rate: 24_000, channels: 1 })

    const context = FakeContext.instances[0]

    ws.bytes(48_000)
    await flush()

    expect(context.decoded).toEqual([])
    expect(context.created).toEqual([24_000])
    expect(context.starts).toEqual([0.05])
  })

  it('treats a close after audio landed as the end of the reply, never a fallback', async () => {
    const { session, ws } = await openSession()

    ws.json({ type: 'start', format: 'encoded' })
    ws.bytes(10)
    // The socket closes before the first decode resolved.
    ws.onclose?.()
    await flush()
    vi.advanceTimersByTime(3_000)
    await flush()

    expect(await session.done).toBe('done')
  })

  it('falls back when the endpoint closes before any audio', async () => {
    const { session, ws } = await openSession()

    ws.json({ type: 'fallback' })
    expect(await session.done).toBe('fallback')
  })

  // The "Speaking… forever" guards. A provider that hangs on a sentence, or a
  // socket that dies without a close event, must end the turn on its own.

  it('ends the turn when the server goes quiet after the text is complete', async () => {
    const { session, ws } = await openSession()
    let outcome: null | string = null

    void session.done.then(value => (outcome = value))
    ws.json({ type: 'start', format: 'encoded' })
    session.append('One sentence.')
    session.finish()
    ws.bytes(10)
    await flush()

    // The reply is audible; the server owes `end` and never sends it.
    vi.advanceTimersByTime(SPEECH_STREAM_STALL_MS - 1_000)
    await flush()
    expect(outcome).toBeNull()

    vi.advanceTimersByTime(1_000)
    await flush()
    vi.advanceTimersByTime(3_000) // drain what was scheduled
    await flush()
    expect(outcome).toBe('done')
    expect(ws.closed).toBe(true)
  })

  it('has no deadline while the model is still writing — a tool can run for minutes', async () => {
    const { session, ws } = await openSession()
    let outcome: null | string = null

    void session.done.then(value => (outcome = value))
    ws.json({ type: 'start', format: 'encoded' })
    session.append('Let me check. ')
    ws.bytes(10)
    await flush()

    vi.advanceTimersByTime(SPEECH_STREAM_STALL_MS * 8)
    await flush()
    expect(outcome).toBeNull()
    expect(ws.closed).toBe(false)
  })

  it('falls back when the socket never opens', async () => {
    const session = await startSpeechStream({ source: 'voice-conversation' })
    let outcome: null | string = null

    void session!.done.then(value => (outcome = value))
    session!.append('Hello.')
    session!.finish()

    vi.advanceTimersByTime(SPEECH_STREAM_OPEN_TIMEOUT_MS + 10)
    await flush()
    expect(outcome).toBe('fallback')
  })
})
