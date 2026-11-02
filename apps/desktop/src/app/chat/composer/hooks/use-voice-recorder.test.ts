import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Live dictation preview: while recording, the audio so far is transcribed
// every couple of seconds and shown; the text inserted at the end is the
// final transcription, never a preview.

const mic = vi.hoisted(() => ({
  chunks: [] as string[],
  recording: false,
  stopResult: null as { audio: Blob; durationMs: number } | null
}))

vi.mock('./use-mic-recorder', () => ({
  useMicRecorder: () => ({
    handle: {
      cancel: () => {
        mic.recording = false
      },
      snapshot: () => (mic.recording && mic.chunks.length ? new Blob(mic.chunks, { type: 'audio/webm' }) : null),
      start: async () => {
        mic.recording = true
      },
      stop: async () => {
        mic.recording = false

        return mic.stopResult
      }
    },
    level: 0,
    recording: mic.recording
  })
}))

vi.mock('@/store/notifications', () => ({ notify: vi.fn(), notifyError: vi.fn() }))

import { useVoiceRecorder } from './use-voice-recorder'

const flush = async () => {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

const tick = async (ms: number) => {
  await act(async () => {
    vi.advanceTimersByTime(ms)
  })
  await flush()
}

function setup(preview: (audio: Blob) => Promise<string | null>) {
  const transcribe = vi.fn(async () => 'the final words')
  const onTranscript = vi.fn()
  const onPreviewAudio = vi.fn(preview)

  const view = renderHook(() =>
    useVoiceRecorder({
      focusInput: () => undefined,
      maxRecordingSeconds: 120,
      onPreviewAudio,
      onTranscribeAudio: transcribe,
      onTranscript
    })
  )

  return { onPreviewAudio, onTranscript, transcribe, view }
}

beforeEach(() => {
  vi.useFakeTimers()
  mic.chunks = []
  mic.recording = false
  mic.stopResult = { audio: new Blob(['all of it'], { type: 'audio/webm' }), durationMs: 4000 }
})

afterEach(() => {
  vi.useRealTimers()
})

describe('dictation live preview', () => {
  it('shows the words while recording and inserts only the final transcription', async () => {
    const { onPreviewAudio, onTranscript, transcribe, view } = setup(
      async audio => `heard ${(await audio.text()).length}`
    )

    await act(() => view.result.current.dictate())
    expect(view.result.current.voiceStatus).toBe('recording')

    mic.chunks.push('hello')
    await tick(1600)
    expect(onPreviewAudio).toHaveBeenCalledTimes(1)
    expect(view.result.current.voiceActivityState.liveText).toBe('heard 5')

    // Nothing new recorded: no new request.
    await tick(1600)
    expect(onPreviewAudio).toHaveBeenCalledTimes(1)

    mic.chunks.push(' world')
    await tick(1600)
    expect(onPreviewAudio).toHaveBeenCalledTimes(2)
    expect(view.result.current.voiceActivityState.liveText).toBe('heard 11')

    await act(() => view.result.current.dictate())
    await flush()

    expect(transcribe).toHaveBeenCalledTimes(1)
    expect(onTranscript).toHaveBeenCalledWith('the final words')
    expect(view.result.current.voiceActivityState.liveText).toBe('')
    expect(view.result.current.voiceStatus).toBe('idle')
  })

  it('stops asking when this machine cannot preview (cloud speech-to-text)', async () => {
    const { onPreviewAudio, view } = setup(async () => null)

    await act(() => view.result.current.dictate())
    mic.chunks.push('a')
    await tick(1600)
    mic.chunks.push('b')
    await tick(1600)
    await tick(1600)

    expect(onPreviewAudio).toHaveBeenCalledTimes(1)
    expect(view.result.current.voiceActivityState.liveText).toBe('')
  })

  it('never runs two previews at once, and the final waits for a running one', async () => {
    let release: (text: string) => void = () => undefined
    const { onPreviewAudio, transcribe, view } = setup(() => new Promise(resolve => (release = resolve)))

    await act(() => view.result.current.dictate())
    mic.chunks.push('a')
    await tick(1600)
    mic.chunks.push('b')
    await tick(1600)
    expect(onPreviewAudio).toHaveBeenCalledTimes(1)

    const stopping = act(() => view.result.current.dictate())
    await flush()
    expect(transcribe).not.toHaveBeenCalled()

    release('late words')
    await stopping
    await flush()

    expect(transcribe).toHaveBeenCalledTimes(1)
    // The late preview answered after the stop: not shown.
    expect(view.result.current.voiceActivityState.liveText).toBe('')
  })

  it('a failing preview does not affect the dictation', async () => {
    const { onTranscript, view } = setup(async () => {
      throw new Error('preview broke')
    })

    await act(() => view.result.current.dictate())
    mic.chunks.push('a')
    await tick(1600)
    await act(() => view.result.current.dictate())
    await flush()

    expect(onTranscript).toHaveBeenCalledWith('the final words')
  })
})
