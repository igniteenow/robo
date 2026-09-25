import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { type MicRecorderErrorCopy, useMicRecorder } from './use-mic-recorder'

// A voice chat listens again after every reply. With `retainDevice` the
// microphone stays open across stop() → start(), so the next turn begins the
// instant Robo finishes talking instead of after a device re-open; cancel()
// (mute, end, unmount) lets the device go.

const copy: MicRecorderErrorCopy = {
  microphoneAccessDenied: 'denied',
  microphoneConstraintsUnsupported: 'constraints',
  microphoneInUse: 'in use',
  microphonePermissionDenied: 'permission',
  microphoneStartFailed: 'start failed',
  microphoneUnsupported: 'unsupported',
  noMicrophone: 'no mic'
}

class FakeTrack {
  readyState: 'ended' | 'live' = 'live'

  stop() {
    this.readyState = 'ended'
  }
}

class FakeStream {
  tracks = [new FakeTrack()]

  getTracks() {
    return this.tracks
  }
}

class FakeRecorder {
  static instances: FakeRecorder[] = []
  state: 'inactive' | 'recording' = 'inactive'
  mimeType = 'audio/webm'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onstop: (() => void) | null = null

  constructor(readonly stream: FakeStream) {
    FakeRecorder.instances.push(this)
  }

  static isTypeSupported() {
    return true
  }

  start() {
    this.state = 'recording'
  }

  stop() {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob(['x'], { type: 'audio/webm' }) })
    this.onstop?.()
  }
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = []
  closed = false

  constructor() {
    FakeAudioContext.instances.push(this)
  }

  createAnalyser() {
    return { fftSize: 256, getByteTimeDomainData: (data: Uint8Array) => data.fill(128) }
  }

  createMediaStreamSource() {
    return { connect() {} }
  }

  async close() {
    this.closed = true
  }
}

const getUserMedia = vi.fn(async () => new FakeStream() as unknown as MediaStream)
const requestMicrophoneAccess = vi.fn(async () => true)

beforeEach(() => {
  FakeRecorder.instances = []
  FakeAudioContext.instances = []
  getUserMedia.mockClear()
  requestMicrophoneAccess.mockClear()
  vi.stubGlobal('MediaRecorder', FakeRecorder)
  vi.stubGlobal('AudioContext', FakeAudioContext)
  vi.stubGlobal('requestAnimationFrame', () => 1)
  vi.stubGlobal('cancelAnimationFrame', () => undefined)
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
  Object.defineProperty(window, 'roboDesktop', { configurable: true, value: { requestMicrophoneAccess } })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useMicRecorder', () => {
  it('opens the device once and keeps it across turns when asked to', async () => {
    const { result } = renderHook(() => useMicRecorder(copy))

    await act(() => result.current.handle.start({ retainDevice: true }))
    expect(getUserMedia).toHaveBeenCalledTimes(1)
    expect(requestMicrophoneAccess).toHaveBeenCalledTimes(1)

    const stream = FakeRecorder.instances[0].stream

    const first = await act(() => result.current.handle.stop())
    expect(first?.audio).toBeInstanceOf(Blob)
    // Still live: nothing was stopped, the audio graph is intact.
    expect(stream.tracks[0].readyState).toBe('live')
    expect(FakeAudioContext.instances[0].closed).toBe(false)

    await act(() => result.current.handle.start({ retainDevice: true }))
    // No second permission check, no second getUserMedia, no second graph.
    expect(getUserMedia).toHaveBeenCalledTimes(1)
    expect(requestMicrophoneAccess).toHaveBeenCalledTimes(1)
    expect(FakeAudioContext.instances).toHaveLength(1)
    expect(FakeRecorder.instances[1].stream).toBe(stream)

    act(() => result.current.handle.cancel())
    expect(stream.tracks[0].readyState).toBe('ended')
    expect(FakeAudioContext.instances[0].closed).toBe(true)
  })

  it('releases the device after stop() by default', async () => {
    const { result } = renderHook(() => useMicRecorder(copy))

    await act(() => result.current.handle.start())

    const stream = FakeRecorder.instances[0].stream

    await act(() => result.current.handle.stop())
    expect(stream.tracks[0].readyState).toBe('ended')

    await act(() => result.current.handle.start())
    expect(getUserMedia).toHaveBeenCalledTimes(2)
  })

  it('re-opens a retained device whose track has ended (unplugged, revoked)', async () => {
    const { result } = renderHook(() => useMicRecorder(copy))

    await act(() => result.current.handle.start({ retainDevice: true }))
    await act(() => result.current.handle.stop())
    FakeRecorder.instances[0].stream.tracks[0].readyState = 'ended'

    await act(() => result.current.handle.start({ retainDevice: true }))
    expect(getUserMedia).toHaveBeenCalledTimes(2)
  })
})
