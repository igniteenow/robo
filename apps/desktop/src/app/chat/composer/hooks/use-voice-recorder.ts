import { useEffect, useRef, useState } from 'react'

import { useI18n } from '@/i18n'
import { notify, notifyError } from '@/store/notifications'

import type { VoiceActivityState, VoiceStatus } from '../types'

import { useMicRecorder } from './use-mic-recorder'

// Live preview: while dictating, the recording so far is transcribed every
// PREVIEW_EVERY_MS (one request at a time, so a slow machine simply previews
// less often) and the words are shown in the recording pill. It starts once
// there is PREVIEW_FIRST_MS of audio and stops after PREVIEW_MAX_SECONDS —
// each preview re-reads the whole recording, so on long dictations it would
// only compete with the final transcription for the CPU. The text the
// dictation inserts is always the final transcription, never a preview.
const PREVIEW_EVERY_MS = 1500
const PREVIEW_FIRST_MS = 1200
const PREVIEW_MAX_SECONDS = 90

interface VoiceRecorderOptions {
  maxRecordingSeconds: number
  onTranscribeAudio?: (audio: Blob) => Promise<string>
  /** Live words of the recording so far; null = this machine cannot preview. */
  onPreviewAudio?: (audio: Blob) => Promise<string | null>
  focusInput: () => void
  onTranscript: (text: string) => void
}

export function useVoiceRecorder({
  maxRecordingSeconds,
  onTranscribeAudio,
  onPreviewAudio,
  focusInput,
  onTranscript
}: VoiceRecorderOptions) {
  const { t } = useI18n()
  const voiceCopy = t.notifications.voice
  const { handle, level, recording } = useMicRecorder(voiceCopy)
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus>('idle')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const startedAtRef = useRef(0)
  const intervalRef = useRef<number | null>(null)
  const timeoutRef = useRef<number | null>(null)
  const [liveText, setLiveText] = useState('')
  const previewTimerRef = useRef<number | null>(null)
  // Bumped on every start/stop: a preview answering for an earlier
  // recording (or after this one stopped) is dropped.
  const recordingIdRef = useRef(0)
  const previewInFlightRef = useRef<Promise<unknown> | null>(null)

  const clearTimers = () => {
    if (intervalRef.current) {
      window.clearInterval(intervalRef.current)
      intervalRef.current = null
    }

    if (timeoutRef.current) {
      window.clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }

    if (previewTimerRef.current) {
      window.clearInterval(previewTimerRef.current)
      previewTimerRef.current = null
    }
  }

  const startPreview = (recordingId: number) => {
    if (!onPreviewAudio) {
      return
    }

    let previewedBytes = 0

    previewTimerRef.current = window.setInterval(() => {
      const elapsedMs = Date.now() - startedAtRef.current

      if (recordingIdRef.current !== recordingId || previewInFlightRef.current || elapsedMs < PREVIEW_FIRST_MS) {
        return
      }

      if (elapsedMs > PREVIEW_MAX_SECONDS * 1000) {
        window.clearInterval(previewTimerRef.current ?? undefined)
        previewTimerRef.current = null

        return
      }

      const audio = handle.snapshot()

      // Nothing new since the last preview: nothing new to show.
      if (!audio || audio.size === previewedBytes) {
        return
      }

      previewedBytes = audio.size

      const request = onPreviewAudio(audio)
        .then(text => {
          if (recordingIdRef.current !== recordingId) {
            return
          }

          if (text === null) {
            // Not local (or turned off): stop asking for this recording.
            window.clearInterval(previewTimerRef.current ?? undefined)
            previewTimerRef.current = null

            return
          }

          setLiveText(text.trim())
        })
        .catch(() => {
          // A failed preview costs nothing: the final transcription still runs.
        })
        .finally(() => {
          if (previewInFlightRef.current === request) {
            previewInFlightRef.current = null
          }
        })

      previewInFlightRef.current = request
    }, PREVIEW_EVERY_MS)
  }

  useEffect(() => () => clearTimers(), [])

  const stop = async () => {
    clearTimers()
    recordingIdRef.current++
    const result = await handle.stop()
    // The final transcription goes after a preview still running, so the two
    // never run side by side on the same local model.
    await previewInFlightRef.current?.catch(() => undefined)
    previewInFlightRef.current = null

    if (!result) {
      setLiveText('')
      setVoiceStatus('idle')

      return
    }

    if (!onTranscribeAudio) {
      setLiveText('')
      setVoiceStatus('idle')

      return
    }

    setVoiceStatus('transcribing')

    try {
      const transcript = (await onTranscribeAudio(result.audio)).trim()

      if (!transcript) {
        notify({ kind: 'warning', title: voiceCopy.noSpeechDetected, message: voiceCopy.tryRecordingAgain })
      } else {
        onTranscript(transcript)
      }
    } catch (error) {
      notifyError(error, voiceCopy.transcriptionFailed)
    } finally {
      setLiveText('')
      setVoiceStatus('idle')
      focusInput()
    }
  }

  const start = async () => {
    if (!onTranscribeAudio) {
      notify({ kind: 'warning', title: voiceCopy.unavailable, message: voiceCopy.transcriptionUnavailable })

      return
    }

    try {
      await handle.start({ onError: error => notifyError(error, voiceCopy.recordingFailed) })
      startedAtRef.current = Date.now()
      const recordingId = ++recordingIdRef.current
      setLiveText('')
      setElapsedSeconds(0)
      setVoiceStatus('recording')
      startPreview(recordingId)
      intervalRef.current = window.setInterval(() => setElapsedSeconds((Date.now() - startedAtRef.current) / 1000), 250)
      const cap = Math.max(1, Math.min(Math.trunc(maxRecordingSeconds), 600))
      timeoutRef.current = window.setTimeout(() => void stop(), cap * 1000)
    } catch (error) {
      setVoiceStatus('idle')
      notifyError(error, voiceCopy.recordingFailed)
    }
  }

  const dictate = () => {
    if (recording) {
      void stop()
    } else if (voiceStatus === 'idle') {
      void start()
    }
  }

  const voiceActivityState: VoiceActivityState = {
    elapsedSeconds,
    level,
    liveText,
    status: voiceStatus
  }

  return { dictate, voiceActivityState, voiceStatus }
}
