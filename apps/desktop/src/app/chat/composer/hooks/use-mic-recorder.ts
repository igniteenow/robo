import { useCallback, useEffect, useRef, useState } from 'react'

import { SpeechEndpointer } from '@/lib/speech-endpointer'

type BrowserAudioContext = typeof AudioContext

export interface MicRecorderOptions {
  onLevel?: (level: number) => void
  onError?: (error: Error) => void
  onSilence?: () => void
  /** Absolute floor for the speech trigger; the room's own noise raises it
   *  from there (see lib/speech-endpointer). */
  silenceLevel?: number
  silenceMs?: number
  idleSilenceMs?: number
  /** End a turn this long after speech began even if it never goes quiet. */
  maxSpeechMs?: number
  /**
   * Keep the microphone (and the level meter's audio graph) open after
   * `stop()` so the next `start()` is instant. A voice chat listens again
   * after every reply; re-opening the device each time cost a visible pause
   * (permission check + getUserMedia + a new AudioContext, several hundred
   * ms on Windows) before "Listening…" — and a real one, since anything said
   * during it was lost. `cancel()` (mute, end, unmount) releases the device.
   */
  retainDevice?: boolean
}

export interface MicRecording {
  audio: Blob
  durationMs: number
  heardSpeech: boolean
}

export interface MicRecorderErrorCopy {
  microphoneAccessDenied: string
  microphoneConstraintsUnsupported: string
  microphoneInUse: string
  microphonePermissionDenied: string
  microphoneStartFailed: string
  microphoneUnsupported: string
  noMicrophone: string
}

interface MicRecorderHandle {
  start: (options?: MicRecorderOptions) => Promise<void>
  stop: () => Promise<MicRecording | null>
  cancel: () => void
}

function micError(error: unknown, copy: MicRecorderErrorCopy): Error {
  const name = error instanceof DOMException ? error.name : ''

  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return new Error(copy.microphonePermissionDenied)
  }

  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return new Error(copy.noMicrophone)
  }

  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return new Error(copy.microphoneInUse)
  }

  if (name === 'OverconstrainedError') {
    return new Error(copy.microphoneConstraintsUnsupported)
  }

  if (error instanceof Error) {
    return error
  }

  return new Error(copy.microphoneStartFailed)
}

export function useMicRecorder(copy: MicRecorderErrorCopy): {
  handle: MicRecorderHandle
  level: number
  recording: boolean
} {
  const [level, setLevel] = useState(0)
  const [recording, setRecording] = useState(false)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const audioContextRef = useRef<AudioContext | null>(null)
  const animationRef = useRef<number | null>(null)
  const startedAtRef = useRef(0)
  const heardSpeechRef = useRef(false)
  const silenceTriggeredRef = useRef(false)
  const stopResolverRef = useRef<((recording: MicRecording | null) => void) | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const retainRef = useRef(false)

  /** Let go of the device and the audio graph. */
  const releaseDevice = useCallback(() => {
    void audioContextRef.current?.close()
    audioContextRef.current = null
    analyserRef.current = null
    streamRef.current?.getTracks().forEach(track => track.stop())
    streamRef.current = null
    retainRef.current = false
  }, [])

  const cleanup = useCallback(
    (release = true) => {
      if (animationRef.current) {
        window.cancelAnimationFrame(animationRef.current)
        animationRef.current = null
      }

      if (release) {
        releaseDevice()
      }

      recorderRef.current = null
      setLevel(0)
      setRecording(false)
      silenceTriggeredRef.current = false
    },
    [releaseDevice]
  )

  // Unmount: always let the device go, retained or not.
  useEffect(() => () => cleanup(), [cleanup])

  const liveStream = (): MediaStream | null => {
    const stream = streamRef.current

    if (!stream || !stream.getTracks().some(track => track.readyState === 'live')) {
      return null
    }

    return stream
  }

  const startMeter = (stream: MediaStream, options: MicRecorderOptions) => {
    const audioWindow = window as Window & { webkitAudioContext?: BrowserAudioContext }
    const AudioContextCtor = window.AudioContext || audioWindow.webkitAudioContext

    if (!AudioContextCtor) {
      return
    }

    try {
      // A retained device keeps its analyser; a fresh one builds the graph.
      let analyser = audioContextRef.current && analyserRef.current

      if (!analyser) {
        const audioContext = new AudioContextCtor()
        const source = audioContext.createMediaStreamSource(stream)

        analyser = audioContext.createAnalyser()
        analyser.fftSize = 256
        source.connect(analyser)
        audioContextRef.current = audioContext
        analyserRef.current = analyser
      }

      const data = new Uint8Array(analyser.fftSize)
      const meter = analyser
      const speechThreshold = options.silenceLevel ?? 0

      // Turn boundaries come from the endpointer, which learns the room's
      // noise instead of trusting one fixed threshold (a fan or a boosted mic
      // used to keep a turn "listening" forever).
      const endpointer =
        speechThreshold > 0 && options.onSilence
          ? new SpeechEndpointer(
              {
                idleSilenceMs: options.idleSilenceMs ?? 0,
                maxSpeechMs: options.maxSpeechMs ?? 0,
                minLevel: speechThreshold,
                silenceMs: options.silenceMs ?? 0
              },
              startedAtRef.current
            )
          : null

      const tick = () => {
        meter.getByteTimeDomainData(data)

        let sum = 0

        for (const value of data) {
          const centered = value - 128
          sum += centered * centered
        }

        const rms = Math.sqrt(sum / data.length)
        const normalized = Math.min(1, rms / 42)

        setLevel(normalized)
        options.onLevel?.(normalized)

        if (endpointer && !silenceTriggeredRef.current) {
          const event = endpointer.feed(normalized, Date.now())
          heardSpeechRef.current = endpointer.heardSpeech

          if (event) {
            silenceTriggeredRef.current = true
            options.onSilence?.()

            return
          }
        }

        animationRef.current = window.requestAnimationFrame(tick)
      }

      tick()
    } catch {
      setLevel(0)
    }
  }

  const start: MicRecorderHandle['start'] = async (options = {}) => {
    if (recorderRef.current) {
      return
    }

    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      throw new Error(copy.microphoneUnsupported)
    }

    let stream = liveStream()

    if (!stream) {
      releaseDevice()

      const permitted = await window.roboDesktop?.requestMicrophoneAccess?.()

      if (permitted === false) {
        throw new Error(copy.microphoneAccessDenied)
      }

      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true }
        })
      } catch (error) {
        throw micError(error, copy)
      }
    }

    retainRef.current = Boolean(options.retainDevice)

    const mimeType =
      ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/ogg', 'audio/wav'].find(
        type => MediaRecorder.isTypeSupported(type)
      ) ?? ''

    let recorder: MediaRecorder

    try {
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    } catch (error) {
      releaseDevice()
      throw micError(error, copy)
    }

    chunksRef.current = []
    streamRef.current = stream
    recorderRef.current = recorder
    heardSpeechRef.current = false
    silenceTriggeredRef.current = false
    startedAtRef.current = Date.now()

    recorder.ondataavailable = event => {
      if (event.data.size > 0) {
        chunksRef.current.push(event.data)
      }
    }

    recorder.onstop = () => {
      const chunks = chunksRef.current
      const recordingType = recorder.mimeType || mimeType || 'audio/webm'
      const durationMs = Date.now() - startedAtRef.current
      const heardSpeech = heardSpeechRef.current

      chunksRef.current = []
      cleanup(!retainRef.current)

      const resolver = stopResolverRef.current
      stopResolverRef.current = null

      if (!chunks.length) {
        resolver?.(null)

        return
      }

      resolver?.({
        audio: new Blob(chunks, { type: recordingType }),
        durationMs,
        heardSpeech
      })
    }

    recorder.onerror = event => {
      const error = micError((event as Event & { error?: unknown }).error, copy)
      const resolver = stopResolverRef.current
      stopResolverRef.current = null
      cleanup()
      options.onError?.(error)
      resolver?.(null)
    }

    recorder.start()
    setRecording(true)
    startMeter(stream, options)
  }

  const stop: MicRecorderHandle['stop'] = () =>
    new Promise<MicRecording | null>(resolve => {
      const recorder = recorderRef.current

      if (!recorder || recorder.state === 'inactive') {
        cleanup()
        resolve(null)

        return
      }

      stopResolverRef.current = resolve
      recorder.stop()
    })

  const cancel: MicRecorderHandle['cancel'] = () => {
    const recorder = recorderRef.current
    const resolver = stopResolverRef.current
    stopResolverRef.current = null

    if (recorder && recorder.state !== 'inactive') {
      recorder.ondataavailable = null
      recorder.onerror = null
      recorder.onstop = null
      recorder.stop()
    }

    cleanup()
    resolver?.(null)
  }

  const handle: MicRecorderHandle = { start, stop, cancel }

  return { handle, level, recording }
}
