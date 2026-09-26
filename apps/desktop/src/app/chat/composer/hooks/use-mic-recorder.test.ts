import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { micError, type MicRecorderErrorCopy, useMicRecorder } from './use-mic-recorder'

// Push-to-talk dictation: start → speak → stop hands back one recording, and
// the microphone is released as soon as the recording ends.

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
    // A steady tone-ish level: every sample 40 off centre.
    return { fftSize: 256, getByteTimeDomainData: (data: Uint8Array) => data.fill(168) }
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
  it('records until stop() and then releases the device', async () => {
    const { result } = renderHook(() => useMicRecorder(copy))

    await act(() => result.current.handle.start())
    expect(getUserMedia).toHaveBeenCalledTimes(1)
    expect(requestMicrophoneAccess).toHaveBeenCalledTimes(1)
    expect(result.current.recording).toBe(true)

    const stream = FakeRecorder.instances[0].stream
    const recording = await act(() => result.current.handle.stop())

    expect(recording?.audio).toBeInstanceOf(Blob)
    expect(stream.tracks[0].readyState).toBe('ended')
    expect(FakeAudioContext.instances[0].closed).toBe(true)
    expect(result.current.recording).toBe(false)
  })

  it('cancel() releases the device and delivers nothing', async () => {
    const { result } = renderHook(() => useMicRecorder(copy))

    await act(() => result.current.handle.start())

    const stream = FakeRecorder.instances[0].stream

    act(() => result.current.handle.cancel())
    expect(stream.tracks[0].readyState).toBe('ended')
    expect(result.current.recording).toBe(false)
  })

  it('meters the level from a timer while animation frames never come (window minimized)', async () => {
    const { result } = renderHook(() => useMicRecorder(copy))

    await act(() => result.current.handle.start())
    await waitFor(() => expect(result.current.level).toBeGreaterThan(0.9))

    act(() => result.current.handle.cancel())
  })

  it('refuses when the desktop says microphone access is denied', async () => {
    requestMicrophoneAccess.mockResolvedValueOnce(false)

    const { result } = renderHook(() => useMicRecorder(copy))

    await expect(result.current.handle.start()).rejects.toThrow('denied')
    expect(getUserMedia).not.toHaveBeenCalled()
  })
})

describe('micError', () => {
  it('names what went wrong with the microphone', () => {
    expect(micError(new DOMException('x', 'NotAllowedError'), copy).message).toBe('permission')
    expect(micError(new DOMException('x', 'NotFoundError'), copy).message).toBe('no mic')
    expect(micError(new DOMException('x', 'NotReadableError'), copy).message).toBe('in use')
    expect(micError(new DOMException('x', 'OverconstrainedError'), copy).message).toBe('constraints')
    expect(micError('???', copy).message).toBe('start failed')
  })
})
