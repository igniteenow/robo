import { useCallback, useEffect, useRef, useState } from 'react'

import { useI18n } from '@/i18n'
import { startThinkingSound, stopThinkingSound } from '@/lib/thinking-sound'
import { type CapturedUtterance, openVoiceCapture, utteranceToWav, type VoiceCapture } from '@/lib/voice-capture'
import { isFillerOnly, isLikelyEcho } from '@/lib/voice-echo'
import {
  isVoicePlaybackAudible,
  markVoicePlaybackInterrupted,
  pauseVoicePlayback,
  playSpeechText,
  resumeVoicePlayback,
  type SpeechStreamSession,
  startSpeechStream,
  stopVoicePlayback
} from '@/lib/voice-playback'
import { isVoiceStopCommand } from '@/lib/voice-stop-word'
import { warmUpTranscription } from '@/robo'
import { notify, notifyError } from '@/store/notifications'
import { markVoiceTurn } from '@/store/voice-timing'

import { micError } from './use-mic-recorder'

export type ConversationStatus = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'speaking'

interface PendingVoiceResponse {
  id: string
  pending: boolean
  text: string
}

interface VoiceConversationOptions {
  busy: boolean
  enabled: boolean
  onFatalError?: () => void
  /** Interrupt the in-flight agent turn (the same seam as the Stop button).
   *  Fired when the user speaks while the model is still generating. */
  onInterrupt?: () => Promise<void> | void
  onStopWord?: () => void
  /** Send a spoken turn. Resolving `false` means the chat refused it (still
   *  busy) — the loop then asks the user to repeat instead of waiting for a
   *  reply to a question that was never sent. */
  onSubmit: (text: string) => Promise<boolean | void> | boolean | void
  onTranscribeAudio?: (audio: Blob) => Promise<string>
  pendingResponse: () => PendingVoiceResponse | null
  consumePendingResponse: () => void
  /** Awaited right before the mic is opened. Used to let the wake-word listener
   *  fully release the capture device first, so the two never contend. */
  beforeMicOpen?: () => Promise<void> | void
}

/** How long a spoken turn waits for the turn in flight to settle (an
 *  interrupt landing, a reply finishing) before it is handed to the chat. The
 *  old 5 s wait was shorter than an interrupt that has to stop a running tool,
 *  and the turn was then refused and silently lost. */
const BUSY_SETTLE_TIMEOUT_MS = 15_000

/** How often the reply's new text is pushed to the speech session. Text
 *  lands at token rate; this only bounds how long a sentence waits. */
const REPLY_FEED_MS = 60

/** A submitted turn that never made the chat busy and has no reply after
 *  this long produced nothing to say (a refused or instant turn). */
const NO_REPLY_GRACE_MS = 3_000

// The level is painted ~12 times a second in 2% steps: every paint re-renders
// the composer that owns the voice chat.
const LEVEL_PAINT_MS = 80
const LEVEL_STEP = 0.02

/** The reply to one submitted turn, from submit until it has been spoken. */
interface ReplySpeech {
  /** 'opening': the speech socket is connecting (opened at submit, so it is
   *  ready before the first word of the reply exists). 'stream': live.
   *  'fallback': no streaming backend — speak the whole reply once complete. */
  mode: 'fallback' | 'opening' | 'stream'
  session: null | SpeechStreamSession
  /** The reply has text (first assistant words have arrived). */
  hasText: boolean
  fedLength: number
  finished: boolean
  fallbackStarted: boolean
  submittedAt: number
  sawBusy: boolean
}

const joinTranscripts = (first: string, second: string) => [first, second].filter(Boolean).join(' ')

/** Status while the reply is on its way (or being spoken). */
const replyStatus = (reply: ReplySpeech): ConversationStatus => (reply.hasText ? 'speaking' : 'thinking')

/**
 * The hands-free voice chat: one microphone stream open for the whole
 * conversation (lib/voice-capture), cut into utterances by the voice-activity
 * detector, transcribed, sent, and the reply spoken as it streams in.
 *
 * - Listening never stops. Robo hears the user the moment its reply ends —
 *   and while it is still talking.
 * - Talking over Robo pauses the reply at once. The words are transcribed:
 *   real words stop the reply and the turn in flight and become the next
 *   turn; a cough, an "um" or Robo's own voice heard back resumes the reply
 *   where it paused.
 * - A pause mid-thought that ended the turn too early is healed: if the user
 *   carries on before their words were sent, both parts go as one turn.
 */
export function useVoiceConversation({
  busy,
  enabled,
  onFatalError,
  onInterrupt,
  onStopWord,
  onSubmit,
  onTranscribeAudio,
  pendingResponse,
  consumePendingResponse,
  beforeMicOpen
}: VoiceConversationOptions) {
  const { t } = useI18n()
  const voiceCopy = t.notifications.voice
  const [status, setStatus] = useState<ConversationStatus>('idle')
  const [muted, setMuted] = useState(false)
  const [level, setLevel] = useState(0)

  const captureRef = useRef<null | VoiceCapture>(null)
  const openingRef = useRef<null | Promise<void>>(null)
  const enabledRef = useRef(enabled)
  const mutedRef = useRef(muted)
  const busyRef = useRef(busy)
  const statusRef = useRef<ConversationStatus>('idle')
  const wasEnabledRef = useRef(enabled)
  /** A turn was sent and its reply is expected (or being spoken). */
  const replyRef = useRef<null | ReplySpeech>(null)
  /** The user is talking over the reply (it is paused until we know more). */
  const bargeRef = useRef(false)
  /** The user started talking again while their last words were transcribing. */
  const continuationRef = useRef(false)
  /** Words held back for that continuation. */
  const heldTranscriptRef = useRef('')
  /** Utterances whose words are still being transcribed. */
  const pendingWordsRef = useRef(0)
  /** Transcripts are handled in the order they were spoken. */
  const transcriptChainRef = useRef<Promise<void>>(Promise.resolve())
  /** Speech sessions open one after another (each stops the previous). */
  const speechOpenChainRef = useRef<Promise<void>>(Promise.resolve())
  /** The reply Robo is speaking — what its voice sounds like when it leaks
   *  back into the microphone (lib/voice-echo). */
  const spokenTextRef = useRef('')
  const paintedLevelRef = useRef({ at: 0, level: -1 })

  const onFatalErrorRef = useRef(onFatalError)
  const onInterruptRef = useRef(onInterrupt)
  const onStopWordRef = useRef(onStopWord)
  const onSubmitRef = useRef(onSubmit)
  const onTranscribeAudioRef = useRef(onTranscribeAudio)
  const pendingResponseRef = useRef(pendingResponse)
  const consumePendingResponseRef = useRef(consumePendingResponse)
  const beforeMicOpenRef = useRef(beforeMicOpen)

  // The capture engine lives for the whole conversation and reports seconds
  // after any render: its callbacks must reach the CURRENT props.
  // eslint-disable-next-line no-restricted-syntax -- prop mirrors for long-lived audio callbacks, not atoms
  useEffect(() => {
    onFatalErrorRef.current = onFatalError
    onInterruptRef.current = onInterrupt
    onStopWordRef.current = onStopWord
    onSubmitRef.current = onSubmit
    onTranscribeAudioRef.current = onTranscribeAudio
    pendingResponseRef.current = pendingResponse
    consumePendingResponseRef.current = consumePendingResponse
    beforeMicOpenRef.current = beforeMicOpen
  })

  // eslint-disable-next-line no-restricted-syntax -- legitimate non-atom ref write (see eslint rule comment)
  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  // eslint-disable-next-line no-restricted-syntax -- legitimate non-atom ref write (see eslint rule comment)
  useEffect(() => {
    mutedRef.current = muted
  }, [muted])

  // eslint-disable-next-line no-restricted-syntax -- legitimate non-atom ref write (see eslint rule comment)
  useEffect(() => {
    busyRef.current = busy

    if (busy && replyRef.current) {
      replyRef.current.sawBusy = true
    }
  }, [busy])

  const updateStatus = useCallback((next: ConversationStatus) => {
    statusRef.current = next
    setStatus(next)
  }, [])

  const paintLevel = useCallback((next: number) => {
    const shown = Math.round(next / LEVEL_STEP) * LEVEL_STEP
    const now = Date.now()
    const painted = paintedLevelRef.current

    if (shown !== painted.level && now - painted.at >= LEVEL_PAINT_MS) {
      paintedLevelRef.current = { at: now, level: shown }
      setLevel(shown)
    }
  }, [])

  const closeMic = useCallback(() => {
    captureRef.current?.close()
    captureRef.current = null
    paintedLevelRef.current = { at: 0, level: -1 }
    setLevel(0)
  }, [])

  /** Drop the reply to the last turn — its sound and whatever is still coming. */
  const dropReply = useCallback(() => {
    replyRef.current = null
    bargeRef.current = false
    spokenTextRef.current = ''
    stopVoicePlayback()
  }, [])

  /** The reply is over (spoken, stopped or empty): listen for the next turn. */
  const finishReply = useCallback(
    (reply: ReplySpeech) => {
      if (replyRef.current !== reply) {
        return
      }

      replyRef.current = null
      consumePendingResponseRef.current()
      markVoiceTurn('done')

      if (!bargeRef.current && enabledRef.current) {
        updateStatus(mutedRef.current ? 'idle' : 'listening')
      }
    },
    [updateStatus]
  )

  /**
   * Open the reply's speech session the moment the turn is sent, so the
   * socket, the provider and the audio output are ready before the first word
   * of the reply exists — instead of starting all that after it.
   */
  const prepareReply = useCallback(() => {
    const reply: ReplySpeech = {
      fallbackStarted: false,
      fedLength: 0,
      finished: false,
      hasText: false,
      mode: 'opening',
      sawBusy: busyRef.current,
      session: null,
      submittedAt: Date.now()
    }

    replyRef.current = reply

    const opened = speechOpenChainRef.current.then(() => startSpeechStream({ source: 'voice-conversation' }))

    speechOpenChainRef.current = opened.then(
      () => undefined,
      () => undefined
    )

    void opened
      .catch(() => null)
      .then(session => {
        if (replyRef.current !== reply) {
          if (session) {
            stopVoicePlayback() // opened for a turn that is already over
          }

          return
        }

        if (!session) {
          reply.mode = 'fallback' // no streaming backend: speak it whole

          return
        }

        reply.session = session
        reply.mode = 'stream'

        if (bargeRef.current) {
          pauseVoicePlayback() // the user is already talking over it
        }

        void session.done.then(outcome => {
          if (replyRef.current !== reply) {
            return
          }

          if (outcome === 'fallback') {
            reply.mode = 'fallback'
            reply.session = null

            return
          }

          finishReply(reply)
        })
      })
  }, [finishReply])

  /** Whole-text fallback: speak the complete reply in one go. */
  const speakWholeReply = useCallback(
    async (reply: ReplySpeech, text: string) => {
      reply.fallbackStarted = true
      spokenTextRef.current = text

      try {
        await playSpeechText(text, { source: 'voice-conversation' })
      } catch (error) {
        notifyError(error, voiceCopy.playbackFailed)
      }

      finishReply(reply)
    },
    [finishReply, voiceCopy.playbackFailed]
  )

  /** Push the reply's new text to the speech session; end the turn when done. */
  const feedReply = useCallback(() => {
    const reply = replyRef.current

    if (!reply) {
      return
    }

    const response = pendingResponseRef.current()

    if (!response) {
      const settled = !busyRef.current && (reply.sawBusy || Date.now() - reply.submittedAt >= NO_REPLY_GRACE_MS)

      if (settled && !reply.hasText) {
        // The turn ended with nothing to say (tool-only, an error): close
        // the speech session that was opened for it.
        finishReply(reply)
        stopVoicePlayback()
      }

      return
    }

    if (!reply.hasText) {
      reply.hasText = true
      markVoiceTurn('firstText')

      if (!bargeRef.current) {
        updateStatus('speaking')
      }
    }

    spokenTextRef.current = response.text

    const complete = !response.pending && !busyRef.current

    if (reply.mode === 'stream' && reply.session) {
      if (response.text.length > reply.fedLength) {
        reply.session.append(response.text.slice(reply.fedLength))
        reply.fedLength = response.text.length
      }

      if (complete && !reply.finished) {
        reply.finished = true
        reply.session.finish()
      }
    } else if (reply.mode === 'fallback' && complete && !reply.fallbackStarted && !bargeRef.current) {
      void speakWholeReply(reply, response.text)
    }
  }, [finishReply, speakWholeReply, updateStatus])

  /**
   * Hand a spoken turn to the chat. Waits for the turn in flight to settle
   * first (an interrupt takes a moment to land), then reports whether the chat
   * accepted it — a refused submit must not leave the loop "Thinking…" about a
   * question that was never sent.
   */
  const submitTranscript = useCallback(
    async (transcript: string): Promise<boolean> => {
      const deadline = Date.now() + BUSY_SETTLE_TIMEOUT_MS

      while (busyRef.current && enabledRef.current && Date.now() < deadline) {
        await new Promise(resolve => window.setTimeout(resolve, 100))
      }

      if (!enabledRef.current) {
        return false
      }

      spokenTextRef.current = ''
      consumePendingResponseRef.current()

      const accepted = (await onSubmitRef.current(transcript)) !== false

      if (!accepted || !enabledRef.current) {
        return false
      }

      markVoiceTurn('submitted')
      prepareReply()
      updateStatus('thinking')

      return true
    },
    [prepareReply, updateStatus]
  )

  /** A spoken turn could not be sent: say so and listen again. */
  const recoverFromRefusedTurn = useCallback(() => {
    if (!enabledRef.current) {
      updateStatus('idle')

      return
    }

    notify({ kind: 'warning', message: voiceCopy.tryRecordingAgain })
    updateStatus(mutedRef.current ? 'idle' : 'listening')
  }, [updateStatus, voiceCopy.tryRecordingAgain])

  /** A spoken stop command: the reply, the turn in flight and the chat end. */
  const stopForStopWord = useCallback(() => {
    const interrupting = Boolean(replyRef.current) && busyRef.current

    dropReply()

    if (interrupting) {
      void onInterruptRef.current?.()
    }

    updateStatus('idle')
    onStopWordRef.current?.()
  }, [dropReply, updateStatus])

  /** Words said while nothing was in flight: the next turn. */
  const handleTurnWords = useCallback(
    async (full: string) => {
      if (!full) {
        updateStatus(mutedRef.current ? 'idle' : 'listening')

        return
      }

      // A spoken "stop" (or "never mind", "goodbye", …) ends the
      // conversation instead of being submitted as a turn. Only whole-
      // utterance stop commands match, so "stop the container" still goes
      // through as a real request.
      if (isVoiceStopCommand(full)) {
        stopForStopWord()

        return
      }

      if (!(await submitTranscript(full))) {
        recoverFromRefusedTurn()
      }
    },
    [recoverFromRefusedTurn, stopForStopWord, submitTranscript, updateStatus]
  )

  /**
   * Words said over the reply (or while it was being prepared): was it the
   * user? A stop command ends the chat; nothing intelligible, a hesitation,
   * or Robo's own voice heard back (lib/voice-echo) resumes the reply where it
   * paused; real words stop the reply and the turn in flight and become the
   * next turn — complete from their first syllable.
   */
  const handleBargeWords = useCallback(
    async (transcript: string, utterance: CapturedUtterance, heardAt: number) => {
      if (transcript && isVoiceStopCommand(transcript)) {
        stopForStopWord()

        return
      }

      const echo = utterance.startedDuringPlayback && isLikelyEcho(transcript, spokenTextRef.current)

      if (isFillerOnly(transcript) || echo) {
        bargeRef.current = false

        const reply = replyRef.current

        if (reply) {
          resumeVoicePlayback()
          updateStatus(replyStatus(reply))
        } else {
          updateStatus(mutedRef.current ? 'idle' : 'listening')
        }

        return
      }

      markVoiceTurn('heard', heardAt)
      markVoiceTurn('transcribed')
      markVoicePlaybackInterrupted()

      const interrupting = Boolean(replyRef.current) && busyRef.current

      // The interrupted reply must never be spoken now — not even the part
      // that lands while the interrupt settles.
      dropReply()

      if (interrupting) {
        void onInterruptRef.current?.()
      }

      updateStatus('transcribing')

      if (!(await submitTranscript(transcript))) {
        recoverFromRefusedTurn()
      }
    },
    [dropReply, recoverFromRefusedTurn, stopForStopWord, submitTranscript, updateStatus]
  )

  const handleUtterance = useCallback(
    (utterance: CapturedUtterance) => {
      if (!enabledRef.current || mutedRef.current) {
        return
      }

      const barge = bargeRef.current
      const heardAt = Date.now()
      const transcribe = onTranscribeAudioRef.current

      if (!barge) {
        markVoiceTurn('heard', heardAt)
        updateStatus('transcribing')
      }

      // Start transcribing now; handle the words in the order they were said.
      const words = transcribe
        ? transcribe(utteranceToWav(utterance)).then(
            text => ({ error: null, text: text.trim() }),
            (error: unknown) => ({ error, text: '' })
          )
        : Promise.resolve({ error: null, text: '' })

      pendingWordsRef.current += 1

      transcriptChainRef.current = transcriptChainRef.current.then(async () => {
        const { error, text } = await words

        pendingWordsRef.current = Math.max(0, pendingWordsRef.current - 1)

        if (!enabledRef.current) {
          return
        }

        if (error && !barge) {
          notifyError(error, voiceCopy.transcriptionFailed)
        }

        if (continuationRef.current) {
          // They kept talking: hold these words for the rest of the thought.
          continuationRef.current = false
          heldTranscriptRef.current = joinTranscripts(heldTranscriptRef.current, text)

          return
        }

        const full = joinTranscripts(heldTranscriptRef.current, text)

        heldTranscriptRef.current = ''

        if (barge) {
          await handleBargeWords(full, utterance, heardAt)
        } else {
          markVoiceTurn('transcribed')
          await handleTurnWords(full)
        }
      })
    },
    [handleBargeWords, handleTurnWords, updateStatus, voiceCopy.transcriptionFailed]
  )

  const handleSpeechStart = useCallback(() => {
    if (!enabledRef.current || mutedRef.current) {
      return
    }

    // Still transcribing what they said last: this is the rest of it.
    if (pendingWordsRef.current > 0) {
      continuationRef.current = true
    }

    if (replyRef.current) {
      // Talking over Robo (or over the reply being prepared): pause it now.
      bargeRef.current = true
      pauseVoicePlayback()
    }

    updateStatus('listening')
  }, [updateStatus])

  // The capture engine is opened once and keeps these; route them to the
  // current callbacks.
  const handlersRef = useRef({ handleSpeechStart, handleUtterance })

  // eslint-disable-next-line no-restricted-syntax -- routes long-lived capture callbacks to the current handlers
  useEffect(() => {
    handlersRef.current = { handleSpeechStart, handleUtterance }
  }, [handleSpeechStart, handleUtterance])

  /** Open the microphone for the conversation (once; kept until mute or end). */
  const openMic = useCallback(async (): Promise<boolean> => {
    if (captureRef.current) {
      return true
    }

    if (!openingRef.current) {
      openingRef.current = (async () => {
        try {
          await beforeMicOpenRef.current?.()
        } catch {
          // A pause failure shouldn't block the user's explicit start.
        }

        if (!enabledRef.current || mutedRef.current) {
          return
        }

        if ((await window.roboDesktop?.requestMicrophoneAccess?.()) === false) {
          throw new Error(voiceCopy.microphoneAccessDenied)
        }

        let capture: VoiceCapture

        try {
          capture = await openVoiceCapture({
            isPlaying: isVoicePlaybackAudible,
            onError: error => {
              closeMic()
              notifyError(error, voiceCopy.microphoneFailed)
              onFatalErrorRef.current?.()
            },
            onLevel: paintLevel,
            onSpeechStart: () => handlersRef.current.handleSpeechStart(),
            onUtterance: utterance => handlersRef.current.handleUtterance(utterance)
          })
        } catch (error) {
          throw micError(error, voiceCopy)
        }

        if (!enabledRef.current || mutedRef.current) {
          capture.close()

          return
        }

        captureRef.current = capture
      })()
    }

    const opening = openingRef.current

    try {
      await opening
    } finally {
      if (openingRef.current === opening) {
        openingRef.current = null
      }
    }

    return captureRef.current !== null
  }, [closeMic, paintLevel, voiceCopy])

  /** Open the mic and listen, or report why not. */
  const listen = useCallback(async () => {
    try {
      if (!(await openMic())) {
        return
      }
    } catch (error) {
      notifyError(error, voiceCopy.couldNotStartSession)
      updateStatus('idle')
      onFatalErrorRef.current?.()

      return
    }

    markVoiceTurn('listening')

    if (!replyRef.current && statusRef.current !== 'transcribing') {
      updateStatus('listening')
    }
  }, [openMic, updateStatus, voiceCopy.couldNotStartSession])

  const resetTurnState = useCallback(() => {
    continuationRef.current = false
    heldTranscriptRef.current = ''
    pendingWordsRef.current = 0
    transcriptChainRef.current = Promise.resolve()
  }, [])

  const start = useCallback(async () => {
    if (!onTranscribeAudioRef.current) {
      notify({
        kind: 'warning',
        title: voiceCopy.unavailable,
        message: voiceCopy.configureSpeechToText
      })
      onFatalErrorRef.current?.()

      return
    }

    setMuted(false)
    mutedRef.current = false
    replyRef.current = null
    bargeRef.current = false
    resetTurnState()
    consumePendingResponseRef.current()
    await listen()
  }, [listen, resetTurnState, voiceCopy.configureSpeechToText, voiceCopy.unavailable])

  const end = useCallback(async () => {
    closeMic()
    dropReply()
    resetTurnState()
    consumePendingResponseRef.current()
    setMuted(false)
    mutedRef.current = false
    updateStatus('idle')
  }, [closeMic, dropReply, resetTurnState, updateStatus])

  /** "Send now": the words so far are the turn, without waiting for the pause. */
  const stopTurn = useCallback(() => {
    if (statusRef.current === 'listening' && !mutedRef.current) {
      captureRef.current?.flush()
    }
  }, [])

  const toggleMute = useCallback(() => {
    const next = !mutedRef.current

    mutedRef.current = next
    setMuted(next)

    if (next) {
      closeMic()
      resetTurnState()

      if (bargeRef.current) {
        bargeRef.current = false
        resumeVoicePlayback()
      }

      const reply = replyRef.current

      updateStatus(reply ? replyStatus(reply) : 'idle')
    } else if (enabledRef.current) {
      void listen()
    }
  }, [closeMic, listen, resetTurnState, updateStatus])

  useEffect(() => {
    if (!enabled) {
      return
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code !== 'Space' || event.repeat || event.metaKey || event.ctrlKey || event.altKey) {
        return
      }

      if (statusRef.current !== 'listening') {
        return
      }

      event.preventDefault()
      stopTurn()
    }

    window.addEventListener('keydown', onKeyDown, { capture: true })

    return () => window.removeEventListener('keydown', onKeyDown, { capture: true })
  }, [enabled, stopTurn])

  // The reply's text flows into its speech session on a timer, independent of
  // React's render cadence.
  useEffect(() => {
    if (!enabled) {
      return
    }

    const timer = window.setInterval(feedReply, REPLY_FEED_MS)

    return () => window.clearInterval(timer)
  }, [enabled, feedReply])

  // The first spoken turn used to pay the local STT model load as a silent
  // pause between "I stopped talking" and "Robo has my words". Warm the model
  // the moment the conversation starts, off the request path; a backend
  // without the endpoint (or a remote provider) just says no.
  useEffect(() => {
    if (!enabled) {
      return
    }

    try {
      void warmUpTranscription().catch(() => undefined)
    } catch {
      // No desktop bridge (a bare renderer / tests): nothing to warm.
    }
  }, [enabled])

  // Turn-long "thinking" blips while the agent works (status 'thinking'):
  // OFF unless voice.thinking_sound is the explicit "ambient" opt-in (see
  // store/voice-prefs). A voice chat is otherwise silent while Robo works —
  // nothing plays but Robo talking. When on, the blips stop the INSTANT
  // speech starts, the user talks, or the conversation ends.
  useEffect(() => {
    if (enabled && !muted && status === 'thinking') {
      startThinkingSound()

      return stopThinkingSound
    }

    stopThinkingSound()

    return undefined
  }, [enabled, muted, status])

  // Unmount: let the microphone go.
  useEffect(() => () => closeMic(), [closeMic])

  // eslint-disable-next-line no-restricted-syntax -- legitimate non-atom ref write (see eslint rule comment)
  useEffect(() => {
    if (enabled && !wasEnabledRef.current) {
      void start()
    }

    if (!enabled && wasEnabledRef.current) {
      void end()
    }

    wasEnabledRef.current = enabled
  }, [enabled, end, start])

  return { end, level, muted, start, status, stopTurn, toggleMute }
}
