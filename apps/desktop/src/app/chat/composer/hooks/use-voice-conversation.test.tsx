import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { type CapturedUtterance, openVoiceCapture, type VoiceCaptureOptions } from '@/lib/voice-capture'
import { notify, notifyError } from '@/store/notifications'

import { useVoiceConversation } from './use-voice-conversation'

// The hands-free voice chat. One microphone stream stays open for the whole
// conversation (lib/voice-capture, mocked here: the tests play the user's
// side by firing its callbacks). What is asserted is the turn-taking:
// listening never stops, the reply's speech is ready before its first word,
// talking over Robo pauses it at once, and only real words interrupt.

const ear = vi.hoisted(() => ({
  handle: { close: vi.fn(), flush: vi.fn(), reset: vi.fn() },
  options: null as null | VoiceCaptureOptions
}))

vi.mock('@/lib/voice-capture', () => ({
  openVoiceCapture: vi.fn(async (options: VoiceCaptureOptions) => {
    ear.options = options

    return ear.handle
  }),
  utteranceToWav: () => new Blob(['wav'], { type: 'audio/wav' })
}))

const speech = vi.hoisted(() => {
  const state = {
    available: true,
    sessions: [] as {
      append: ReturnType<typeof vi.fn>
      done: Promise<'done' | 'fallback'>
      end: (outcome: 'done' | 'fallback') => void
      finish: ReturnType<typeof vi.fn>
    }[]
  }

  return {
    state,
    isVoicePlaybackAudible: vi.fn(() => false),
    markVoicePlaybackInterrupted: vi.fn(),
    pauseVoicePlayback: vi.fn(),
    playSpeechText: vi.fn(async () => true),
    resumeVoicePlayback: vi.fn(),
    startSpeechStream: vi.fn(async () => {
      if (!state.available) {
        return null
      }

      let end: (outcome: 'done' | 'fallback') => void = () => undefined
      const done = new Promise<'done' | 'fallback'>(resolve => (end = resolve))
      const session = { append: vi.fn(), done, end, finish: vi.fn() }

      state.sessions.push(session)

      return session
    }),
    stopVoicePlayback: vi.fn()
  }
})

vi.mock('@/lib/voice-playback', () => ({
  isVoicePlaybackAudible: speech.isVoicePlaybackAudible,
  markVoicePlaybackInterrupted: speech.markVoicePlaybackInterrupted,
  pauseVoicePlayback: speech.pauseVoicePlayback,
  playSpeechText: speech.playSpeechText,
  resumeVoicePlayback: speech.resumeVoicePlayback,
  startSpeechStream: speech.startSpeechStream,
  stopVoicePlayback: speech.stopVoicePlayback
}))

vi.mock('@/lib/thinking-sound', () => ({
  startThinkingSound: vi.fn(),
  stopThinkingSound: vi.fn()
}))

vi.mock('@/robo', () => ({
  warmUpTranscription: vi.fn(async () => undefined)
}))

vi.mock('@/i18n', () => ({
  useI18n: () => ({
    t: {
      notifications: {
        voice: {
          configureSpeechToText: 'configure STT',
          couldNotStartSession: 'could not start',
          microphoneAccessDenied: 'denied',
          microphoneConstraintsUnsupported: 'constraints',
          microphoneFailed: 'mic failed',
          microphoneInUse: 'in use',
          microphonePermissionDenied: 'permission',
          microphoneStartFailed: 'start failed',
          microphoneUnsupported: 'unsupported',
          noMicrophone: 'no mic',
          playbackFailed: 'playback failed',
          transcriptionFailed: 'transcription failed',
          tryRecordingAgain: 'try again',
          unavailable: 'unavailable'
        }
      }
    }
  })
}))

vi.mock('@/store/notifications', () => ({
  notify: vi.fn(),
  notifyError: vi.fn()
}))

interface Reply {
  id: string
  pending: boolean
  text: string
}

interface ConversationSetup {
  refuseSubmit?: boolean
}

function utterance(overrides: Partial<CapturedUtterance> = {}): CapturedUtterance {
  return {
    endedBy: 'silence',
    sampleRate: 16_000,
    samples: new Float32Array(16_000),
    speechMs: 800,
    startedDuringPlayback: false,
    ...overrides
  }
}

function renderConversation(setup: ConversationSetup = {}) {
  let response: null | Reply = null
  const transcripts: string[] = []
  // Transcriptions resolve in order, each when its test says so (or at once).
  const held: ((text: string) => void)[] = []
  let holdTranscripts = false

  const onBusyChange: { current: (busy: boolean) => void } = { current: () => undefined }

  const onSubmit = vi.fn(async (_text: string) => {
    if (setup.refuseSubmit) {
      return false
    }

    onBusyChange.current(true)

    return true
  })

  const onTranscribeAudio = vi.fn(async () => {
    const text = transcripts.shift() ?? ''

    if (!holdTranscripts) {
      return text
    }

    return new Promise<string>(resolve => held.push(() => resolve(text)))
  })

  const onInterrupt = vi.fn()
  const onStopWord = vi.fn()
  const onFatalError = vi.fn()

  // Mirrors the composer: consuming marks everything so far as spoken.
  const consumePendingResponse = vi.fn(() => {
    response = null
  })

  const hook = renderHook(
    ({ busy, enabled }: { busy: boolean; enabled: boolean }) =>
      useVoiceConversation({
        busy,
        consumePendingResponse,
        enabled,
        onFatalError,
        onInterrupt,
        onStopWord,
        onSubmit,
        onTranscribeAudio,
        pendingResponse: () => response
      }),
    { initialProps: { busy: false, enabled: false } }
  )

  let busy = false
  let enabled = false

  onBusyChange.current = next => {
    busy = next
    hook.rerender({ busy, enabled })
  }

  return {
    consumePendingResponse,
    hook,
    onFatalError,
    onInterrupt,
    onStopWord,
    onSubmit,
    onTranscribeAudio,
    /** Resolve the oldest held transcription. */
    releaseTranscript: () => held.shift()?.(''),
    holdTranscripts: () => (holdTranscripts = true),
    setBusy: (next: boolean) => onBusyChange.current(next),
    setReply: (next: null | Reply) => (response = next),
    /** Queue what the transcriber will hear next. */
    hears: (...texts: string[]) => transcripts.push(...texts),
    async enable() {
      enabled = true
      hook.rerender({ busy, enabled })
      await waitFor(() => expect(hook.result.current.status).toBe('listening'))
    },
    disable() {
      enabled = false
      hook.rerender({ busy, enabled })
    }
  }
}

/** The user starts talking (the capture engine confirmed speech). */
function startTalking(startedDuringPlayback = false) {
  act(() => ear.options?.onSpeechStart?.({ startedDuringPlayback }))
}

/** The user stops talking: the utterance is complete. */
async function stopTalking(overrides: Partial<CapturedUtterance> = {}) {
  await act(async () => ear.options?.onUtterance(utterance(overrides)))
}

async function say(overrides: Partial<CapturedUtterance> = {}) {
  startTalking(overrides.startedDuringPlayback)
  await stopTalking(overrides)
}

beforeEach(() => {
  vi.clearAllMocks()
  ear.options = null
  speech.state.available = true
  speech.state.sessions = []
})

afterEach(cleanup)

describe('useVoiceConversation — listening', () => {
  it('opens the microphone once and keeps it open across turns', async () => {
    const chat = renderConversation()

    await chat.enable()
    chat.hears('hello', 'and another thing')
    await say()
    await waitFor(() => expect(chat.onSubmit).toHaveBeenCalledWith('hello'))

    // The reply is spoken and done.
    chat.setReply({ id: 'reply-1', pending: false, text: 'Hi.' })
    chat.setBusy(false)
    await waitFor(() => expect(speech.state.sessions[0].finish).toHaveBeenCalled())
    await act(async () => speech.state.sessions[0].end('done'))
    await waitFor(() => expect(chat.hook.result.current.status).toBe('listening'))

    chat.setReply(null)
    await say()
    await waitFor(() => expect(chat.onSubmit).toHaveBeenCalledWith('and another thing'))

    expect(openVoiceCapture).toHaveBeenCalledTimes(1)
    expect(ear.handle.close).not.toHaveBeenCalled()
  })

  it('sends a spoken turn and opens the reply speech before the reply exists', async () => {
    const chat = renderConversation()

    await chat.enable()
    chat.hears('what time is it')
    await say()

    await waitFor(() => expect(chat.hook.result.current.status).toBe('thinking'))
    expect(chat.onSubmit).toHaveBeenCalledWith('what time is it')
    // The session is already open; no reply text exists yet.
    await waitFor(() => expect(speech.startSpeechStream).toHaveBeenCalledTimes(1))
    expect(speech.state.sessions[0].append).not.toHaveBeenCalled()
  })

  it('streams the reply into that session as it is written, then listens again', async () => {
    const chat = renderConversation()

    await chat.enable()
    chat.hears('tell me a joke')
    await say()
    await waitFor(() => expect(speech.state.sessions).toHaveLength(1))

    const session = speech.state.sessions[0]

    chat.setReply({ id: 'reply-1', pending: true, text: 'Why did the robot ' })
    await waitFor(() => expect(session.append).toHaveBeenCalledWith('Why did the robot '))
    expect(chat.hook.result.current.status).toBe('speaking')

    chat.setReply({ id: 'reply-1', pending: false, text: 'Why did the robot cross the road?' })
    chat.setBusy(false)
    await waitFor(() => expect(session.append).toHaveBeenLastCalledWith('cross the road?'))
    await waitFor(() => expect(session.finish).toHaveBeenCalledTimes(1))

    await act(async () => session.end('done'))
    await waitFor(() => expect(chat.hook.result.current.status).toBe('listening'))
  })

  it('a turn that ends with nothing to say goes straight back to listening', async () => {
    const chat = renderConversation()

    await chat.enable()
    chat.hears('run the backup')
    await say()
    await waitFor(() => expect(chat.hook.result.current.status).toBe('thinking'))

    chat.setBusy(false)
    await waitFor(() => expect(chat.hook.result.current.status).toBe('listening'))
    expect(speech.stopVoicePlayback).toHaveBeenCalled()
  })

  it('without a streaming backend, speaks the whole reply once it is complete', async () => {
    speech.state.available = false

    const chat = renderConversation()

    await chat.enable()
    chat.hears('hi')
    await say()
    chat.setReply({ id: 'reply-1', pending: true, text: 'Hello there' })
    await waitFor(() => expect(chat.hook.result.current.status).toBe('speaking'))
    expect(speech.playSpeechText).not.toHaveBeenCalled()

    chat.setReply({ id: 'reply-1', pending: false, text: 'Hello there.' })
    chat.setBusy(false)
    await waitFor(() =>
      expect(speech.playSpeechText).toHaveBeenCalledWith('Hello there.', { source: 'voice-conversation' })
    )
    await waitFor(() => expect(chat.hook.result.current.status).toBe('listening'))
  })

  it('carries on when the user keeps talking after a pause: both parts go as one turn', async () => {
    const chat = renderConversation()

    await chat.enable()
    chat.holdTranscripts()
    chat.hears('book a table', 'for two at eight')

    await say()
    expect(chat.hook.result.current.status).toBe('transcribing')

    // They carry on before the first part came back from the transcriber.
    startTalking()
    expect(chat.hook.result.current.status).toBe('listening')
    await act(async () => chat.releaseTranscript())

    await stopTalking()
    await act(async () => chat.releaseTranscript())

    await waitFor(() => expect(chat.onSubmit).toHaveBeenCalledTimes(1))
    expect(chat.onSubmit).toHaveBeenCalledWith('book a table for two at eight')
  })

  it('"Send now" hands over what was said without waiting for the pause', async () => {
    const chat = renderConversation()

    await chat.enable()
    act(() => chat.hook.result.current.stopTurn())

    expect(ear.handle.flush).toHaveBeenCalledTimes(1)
  })

  it('a spoken stop command ends the conversation instead of being sent', async () => {
    const chat = renderConversation()

    await chat.enable()
    chat.hears('stop')
    await say()

    await waitFor(() => expect(chat.onStopWord).toHaveBeenCalledTimes(1))
    expect(chat.onSubmit).not.toHaveBeenCalled()
  })

  it('silence or a hesitation is not a turn', async () => {
    const chat = renderConversation()

    await chat.enable()
    chat.hears('')
    await say()

    await waitFor(() => expect(chat.hook.result.current.status).toBe('listening'))
    expect(chat.onSubmit).not.toHaveBeenCalled()
  })

  it('a turn the chat refuses is not left "thinking": the user is told and listening resumes', async () => {
    const chat = renderConversation({ refuseSubmit: true })

    await chat.enable()
    chat.hears('hello')
    await say()

    await waitFor(() => expect(vi.mocked(notify)).toHaveBeenCalledWith({ kind: 'warning', message: 'try again' }))
    expect(chat.hook.result.current.status).toBe('listening')
  })
})

describe('useVoiceConversation — talking over Robo', () => {
  async function speaking(chat: ReturnType<typeof renderConversation>) {
    await chat.enable()
    chat.hears('tell me about Lahore')
    await say()
    await waitFor(() => expect(speech.state.sessions).toHaveLength(1))

    chat.setReply({
      id: 'reply-1',
      pending: true,
      text: 'The weather in Lahore is sunny and warm today, with a light breeze in the evening.'
    })
    await waitFor(() => expect(chat.hook.result.current.status).toBe('speaking'))
  }

  it('pauses the reply the moment the user starts talking', async () => {
    const chat = renderConversation()

    await speaking(chat)
    startTalking(true)

    expect(speech.pauseVoicePlayback).toHaveBeenCalledTimes(1)
    expect(chat.hook.result.current.status).toBe('listening')
    expect(chat.onInterrupt).not.toHaveBeenCalled()
    expect(speech.stopVoicePlayback).not.toHaveBeenCalled()
  })

  it('a cough or an "um" resumes the reply where it paused', async () => {
    const chat = renderConversation()

    await speaking(chat)
    chat.hears('Um.')
    await say({ startedDuringPlayback: true })

    await waitFor(() => expect(speech.resumeVoicePlayback).toHaveBeenCalledTimes(1))
    expect(chat.hook.result.current.status).toBe('speaking')
    expect(chat.onInterrupt).not.toHaveBeenCalled()
    expect(chat.onSubmit).toHaveBeenCalledTimes(1)
  })

  it("Robo's own voice heard back through the speakers resumes the reply too", async () => {
    const chat = renderConversation()

    await speaking(chat)
    chat.hears('sunny and warm today with a light breeze')
    await say({ startedDuringPlayback: true })

    await waitFor(() => expect(speech.resumeVoicePlayback).toHaveBeenCalledTimes(1))
    expect(speech.stopVoicePlayback).not.toHaveBeenCalled()
    expect(chat.onSubmit).toHaveBeenCalledTimes(1)
  })

  it('real words stop the reply and the turn in flight, and become the next turn', async () => {
    const chat = renderConversation()

    await speaking(chat)
    chat.hears('no, what about Karachi')
    await say({ startedDuringPlayback: true })

    await waitFor(() => expect(chat.onInterrupt).toHaveBeenCalledTimes(1))
    expect(speech.markVoicePlaybackInterrupted).toHaveBeenCalled()
    expect(speech.stopVoicePlayback).toHaveBeenCalled()

    // The interrupt lands → the turn ends → the words go.
    chat.setBusy(false)
    await waitFor(() => expect(chat.onSubmit).toHaveBeenLastCalledWith('no, what about Karachi'))
    await waitFor(() => expect(chat.hook.result.current.status).toBe('thinking'))
  })

  it('can interrupt while the model is still thinking, before any reply exists', async () => {
    const chat = renderConversation()

    await chat.enable()
    chat.hears('start the build', 'actually, wait')
    await say()
    await waitFor(() => expect(chat.hook.result.current.status).toBe('thinking'))

    await say()

    await waitFor(() => expect(chat.onInterrupt).toHaveBeenCalledTimes(1))
    chat.setBusy(false)
    await waitFor(() => expect(chat.onSubmit).toHaveBeenLastCalledWith('actually, wait'))
  })

  it('a stop command over the reply ends everything', async () => {
    const chat = renderConversation()

    await speaking(chat)
    chat.hears('stop')
    await say({ startedDuringPlayback: true })

    await waitFor(() => expect(chat.onStopWord).toHaveBeenCalledTimes(1))
    expect(speech.stopVoicePlayback).toHaveBeenCalled()
    expect(chat.onInterrupt).toHaveBeenCalledTimes(1)
    expect(chat.onSubmit).toHaveBeenCalledTimes(1)
  })

  it('a failed check counts as noise: the reply resumes', async () => {
    const chat = renderConversation()

    await speaking(chat)
    chat.onTranscribeAudio.mockRejectedValueOnce(new Error('offline'))
    await say({ startedDuringPlayback: true })

    await waitFor(() => expect(speech.resumeVoicePlayback).toHaveBeenCalledTimes(1))
    expect(chat.onInterrupt).not.toHaveBeenCalled()
    expect(vi.mocked(notifyError)).not.toHaveBeenCalled()
  })

  it('a Stop pressed while Robo talks ends the reply and the chat keeps listening', async () => {
    const chat = renderConversation()

    await speaking(chat)
    await act(async () => speech.state.sessions[0].end('done'))

    await waitFor(() => expect(chat.hook.result.current.status).toBe('listening'))
    expect(chat.consumePendingResponse).toHaveBeenCalled()
  })
})

describe('useVoiceConversation — mute and end', () => {
  it('mute lets the microphone go; unmute opens it again', async () => {
    const chat = renderConversation()

    await chat.enable()
    act(() => chat.hook.result.current.toggleMute())

    expect(ear.handle.close).toHaveBeenCalledTimes(1)
    expect(chat.hook.result.current.muted).toBe(true)
    expect(chat.hook.result.current.status).toBe('idle')

    act(() => chat.hook.result.current.toggleMute())
    await waitFor(() => expect(chat.hook.result.current.status).toBe('listening'))
    expect(openVoiceCapture).toHaveBeenCalledTimes(2)
  })

  it('ending the conversation closes the microphone and silences Robo', async () => {
    const chat = renderConversation()

    await chat.enable()
    chat.disable()

    await waitFor(() => expect(chat.hook.result.current.status).toBe('idle'))
    expect(ear.handle.close).toHaveBeenCalled()
    expect(speech.stopVoicePlayback).toHaveBeenCalled()
  })

  it('a microphone that cannot open ends the chat with a reason', async () => {
    vi.mocked(openVoiceCapture).mockRejectedValueOnce(new DOMException('busy', 'NotReadableError'))

    const chat = renderConversation()

    chat.hook.rerender({ busy: false, enabled: true })

    await waitFor(() => expect(chat.onFatalError).toHaveBeenCalledTimes(1))
    expect(vi.mocked(notifyError)).toHaveBeenCalledWith(expect.objectContaining({ message: 'in use' }), 'could not start')
  })
})
