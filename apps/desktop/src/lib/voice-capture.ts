/**
 * voice-capture.ts — the voice chat's ear: ONE microphone stream, open for
 * the whole conversation, cut into utterances as the user speaks.
 *
 * The loop it replaces opened a MediaRecorder per turn, re-armed it after
 * every reply, and opened a SECOND microphone stream to notice the user
 * talking over Robo. Each re-arm cost time and lost the first words said
 * during it; the second stream had to learn the room from scratch every turn.
 * Here the stream stays open, audio flows through the voice-activity detector
 * (lib/voice-activity) frame by frame, and a rolling history supplies the
 * moment before speech was confirmed, so an utterance is complete from its
 * first syllable. What the transcriber receives is exactly the speech — 16 kHz
 * WAV, a little lead-in, no minute of silence around it.
 *
 * The same stream hears the user while Robo talks. Chromium's echo canceller
 * removes the app's own playback from the microphone (echoCancellation), and
 * the detector's echo-aware trigger covers what it leaves behind.
 *
 * `VoiceCaptureCore` is the pure part (samples in, events out) and is
 * unit-tested directly; `openVoiceCapture` wires it to the microphone.
 */

import { encodeWav, levelDb, Resampler, SampleRing, SPEECH_SAMPLE_RATE } from './pcm-audio'
import { VAD_FRAME_MS, VoiceActivityDetector, type VoiceActivityOptions } from './voice-activity'

const FRAME_SAMPLES = (SPEECH_SAMPLE_RATE * VAD_FRAME_MS) / 1_000
/** Audio kept before the first voiced frame: soft onsets ("h", "s", "f"). */
const PRE_ROLL_MS = 400
/** Of the pause that ended an utterance, this much stays on its end. */
const TAIL_MS = 300
/** How far back "Send now" reaches when no speech was detected. */
const FORCED_MAX_MS = 8_000
/** High-pass for the level only (rumble and DC are not speech). */
const HIGH_PASS_HZ = 80

export interface CapturedUtterance {
  /** 16 kHz mono samples, lead-in included, trailing pause trimmed. */
  samples: Float32Array
  sampleRate: number
  /** Voiced time the detector heard, ms (0 for a forced send without speech). */
  speechMs: number
  /** The user started talking while Robo's reply was audible. */
  startedDuringPlayback: boolean
  /** Why it ended: the pause after it, the length cap, or "Send now". */
  endedBy: 'flush' | 'max' | 'silence'
}

export interface VoiceCaptureCallbacks {
  /** Speech confirmed — the user is talking (possibly over Robo). */
  onSpeechStart?: (info: { startedDuringPlayback: boolean }) => void
  /** An utterance is complete. */
  onUtterance: (utterance: CapturedUtterance) => void
  /** A sound that was not speech after all (a click, a cough, echo). */
  onBlip?: () => void
  /** Frame level, 0..1 (for meters). */
  onLevel?: (level: number) => void
}

export interface VoiceCaptureTuning {
  vad?: Partial<VoiceActivityOptions>
}

/** dBFS → 0..1 meter level: −60 dB is silence, −15 dB is full. */
export function meterLevel(db: number): number {
  return Math.min(1, Math.max(0, (db + 60) / 45))
}

/**
 * Samples in, utterances out. Feed 16 kHz mono audio in chunks of any size
 * with whether Robo is audible; callbacks fire synchronously.
 */
export class VoiceCaptureCore {
  private readonly callbacks: VoiceCaptureCallbacks
  private readonly detector: VoiceActivityDetector
  private readonly endSilenceMs: number
  private readonly history: SampleRing
  private readonly frame = new Float32Array(FRAME_SAMPLES)
  private readonly filtered = new Float32Array(FRAME_SAMPLES)
  private frameFill = 0
  /** Absolute sample index where the current utterance begins (lead-in included). */
  private utteranceStart: null | number = null
  /** Nothing before this index belongs to a future forced send. */
  private consumedUntil = 0
  private highPassIn = 0
  private highPassOut = 0
  private readonly highPassAlpha: number

  constructor(callbacks: VoiceCaptureCallbacks, tuning: VoiceCaptureTuning = {}) {
    this.callbacks = callbacks
    this.detector = new VoiceActivityDetector(tuning.vad)
    this.endSilenceMs = tuning.vad?.endSilenceMs ?? 650

    const maxMs = (tuning.vad?.maxUtteranceMs ?? 30_000) + PRE_ROLL_MS + 1_000

    this.history = new SampleRing(Math.ceil((Math.max(maxMs, FORCED_MAX_MS) * SPEECH_SAMPLE_RATE) / 1_000))

    const rc = 1 / (2 * Math.PI * HIGH_PASS_HZ)
    const dt = 1 / SPEECH_SAMPLE_RATE

    this.highPassAlpha = rc / (rc + dt)
  }

  /** An utterance (candidate or confirmed) is in progress. */
  get inUtterance(): boolean {
    return this.utteranceStart !== null
  }

  /** Speech is confirmed and not over. */
  get speaking(): boolean {
    return this.detector.speaking
  }

  push(samples: Float32Array, playing: boolean): void {
    let offset = 0

    while (offset < samples.length) {
      const count = Math.min(samples.length - offset, FRAME_SAMPLES - this.frameFill)

      this.frame.set(samples.subarray(offset, offset + count), this.frameFill)
      this.frameFill += count
      offset += count

      if (this.frameFill === FRAME_SAMPLES) {
        this.frameFill = 0
        this.processFrame(playing)
      }
    }
  }

  /**
   * "Send now": hand over what the user has said so far. With speech in
   * progress that is the utterance; with none detected it is the recent audio
   * since the last utterance (the detector may have missed a quiet voice),
   * marked with speechMs 0 so the caller can transcribe it regardless.
   */
  flush(): void {
    const end = this.history.end

    if (this.utteranceStart !== null) {
      const startedDuringPlayback = this.detector.startedDuringPlayback
      const speechMs = this.detector.speechMs

      this.emit(this.utteranceStart, end, { endedBy: 'flush', speechMs, startedDuringPlayback })
      this.detector.reset()

      return
    }

    const from = Math.max(this.consumedUntil, end - (FORCED_MAX_MS * SPEECH_SAMPLE_RATE) / 1_000)

    if (end > from) {
      this.emit(from, end, { endedBy: 'flush', speechMs: 0, startedDuringPlayback: false })
    }
  }

  /** Drop any utterance in progress (mute, end of conversation). */
  reset(): void {
    this.detector.reset()
    this.utteranceStart = null
    this.consumedUntil = this.history.end
  }

  private processFrame(playing: boolean): void {
    this.history.write(this.frame)

    // Level on a high-passed copy: fan rumble and DC offset are not speech.
    for (let index = 0; index < FRAME_SAMPLES; index += 1) {
      const input = this.frame[index]

      this.highPassOut = this.highPassAlpha * (this.highPassOut + input - this.highPassIn)
      this.highPassIn = input
      this.filtered[index] = this.highPassOut
    }

    const db = levelDb(this.filtered)

    this.callbacks.onLevel?.(meterLevel(db))

    const event = this.detector.feed(db, playing)

    switch (event) {
      case 'candidate':
        this.utteranceStart = Math.max(
          this.history.start,
          this.history.end - FRAME_SAMPLES - (PRE_ROLL_MS * SPEECH_SAMPLE_RATE) / 1_000
        )

        break

      case 'start':
        this.callbacks.onSpeechStart?.({ startedDuringPlayback: this.detector.startedDuringPlayback })

        break

      case 'blip':
        this.utteranceStart = null
        this.callbacks.onBlip?.()

        break

      case 'end':
      case 'max': {
        const start = this.utteranceStart ?? this.history.end
        const trimmed = event === 'end' ? ((this.endSilenceMs - TAIL_MS) * SPEECH_SAMPLE_RATE) / 1_000 : 0

        this.emit(start, Math.max(start, this.history.end - Math.max(0, trimmed)), {
          endedBy: event === 'end' ? 'silence' : 'max',
          speechMs: this.detector.speechMs,
          startedDuringPlayback: this.detector.startedDuringPlayback
        })

        break
      }

      default:
        break
    }
  }

  private emit(
    from: number,
    to: number,
    info: Pick<CapturedUtterance, 'endedBy' | 'speechMs' | 'startedDuringPlayback'>
  ): void {
    this.utteranceStart = null
    this.consumedUntil = this.history.end

    this.callbacks.onUtterance({
      ...info,
      sampleRate: SPEECH_SAMPLE_RATE,
      samples: this.history.read(from, to)
    })
  }
}

/** An utterance as the transcriber takes it. */
export function utteranceToWav(utterance: CapturedUtterance): Blob {
  return new Blob([encodeWav(utterance.samples, utterance.sampleRate)], { type: 'audio/wav' })
}

// ---------------------------------------------------------------------------
// Microphone wiring
// ---------------------------------------------------------------------------

export interface VoiceCaptureOptions extends VoiceCaptureCallbacks, VoiceCaptureTuning {
  /** Is Robo's reply audible right now? Read once per audio chunk. */
  isPlaying: () => boolean
  /** The microphone went away mid-conversation (unplugged, revoked). */
  onError?: (error: Error) => void
  /** Skip the AudioWorklet and use the ScriptProcessor path (tests). */
  forceScriptProcessor?: boolean
}

export interface VoiceCapture {
  /** "Send now" — see VoiceCaptureCore.flush. */
  flush: () => void
  /** Drop the utterance in progress, keep listening. */
  reset: () => void
  /** Release the microphone and the audio graph. Idempotent. */
  close: () => void
}

const WORKLET_NAME = 'robo-voice-capture'
/** Samples per message from the audio thread (~21 ms at 48 kHz). */
const WORKLET_CHUNK = 1_024

// Runs on the audio rendering thread: copy the microphone's samples out in
// small chunks. Messages queue on the main thread, so a busy renderer (a long
// reply streaming in) delays them but never drops them.
const WORKLET_SOURCE = `
registerProcessor('${WORKLET_NAME}', class extends AudioWorkletProcessor {
  constructor() {
    super()
    this.chunk = new Float32Array(${WORKLET_CHUNK})
    this.filled = 0
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]

    if (channel) {
      let offset = 0

      while (offset < channel.length) {
        const count = Math.min(channel.length - offset, this.chunk.length - this.filled)

        this.chunk.set(channel.subarray(offset, offset + count), this.filled)
        this.filled += count
        offset += count

        if (this.filled === this.chunk.length) {
          this.port.postMessage(this.chunk, [this.chunk.buffer])
          this.chunk = new Float32Array(${WORKLET_CHUNK})
          this.filled = 0
        }
      }
    }

    return true
  }
})
`

type BrowserAudioContext = typeof AudioContext

/** Stops the processor's callbacks and unplugs it. */
type Detach = () => void

async function connectWorklet(
  context: AudioContext,
  source: AudioNode,
  sink: AudioNode,
  onSamples: (samples: Float32Array) => void
): Promise<Detach | null> {
  if (!context.audioWorklet || typeof AudioWorkletNode === 'undefined') {
    return null
  }

  // A data: URL, not a blob: one: the packaged app runs from file://, where
  // Chromium refuses to load a worklet module from a blob: URL.
  try {
    await context.audioWorklet.addModule(`data:text/javascript;charset=utf-8,${encodeURIComponent(WORKLET_SOURCE)}`)
  } catch {
    return null
  }

  const node = new AudioWorkletNode(context, WORKLET_NAME, {
    channelCount: 1,
    channelCountMode: 'explicit',
    numberOfInputs: 1,
    numberOfOutputs: 1
  })

  node.port.onmessage = event => onSamples(event.data as Float32Array)
  source.connect(node)
  node.connect(sink)

  return () => {
    node.port.onmessage = null
    node.disconnect()
  }
}

// The fallback where AudioWorklet is unavailable. Deprecated but universal;
// its callbacks run on the main thread, so a long stall can drop a chunk.
function connectScriptProcessor(
  context: AudioContext,
  source: AudioNode,
  sink: AudioNode,
  onSamples: (samples: Float32Array) => void
): Detach {
  const node = context.createScriptProcessor(2_048, 1, 1)

  node.onaudioprocess = event => onSamples(event.inputBuffer.getChannelData(0).slice())
  source.connect(node)
  node.connect(sink)

  return () => {
    node.onaudioprocess = null
    node.disconnect()
  }
}

/**
 * Open the microphone and start listening. Resolves once audio is flowing;
 * rejects when the microphone cannot be opened (the caller maps the DOMException).
 */
export async function openVoiceCapture(options: VoiceCaptureOptions): Promise<VoiceCapture> {
  const audioWindow = window as Window & { webkitAudioContext?: BrowserAudioContext }
  const AudioContextCtor = window.AudioContext || audioWindow.webkitAudioContext

  if (!AudioContextCtor || !navigator.mediaDevices?.getUserMedia) {
    throw new Error('Audio capture is not available')
  }

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { autoGainControl: true, channelCount: 1, echoCancellation: true, noiseSuppression: true }
  })

  let closed = false
  let context: AudioContext | null = null
  let detach: Detach | null = null

  const core = new VoiceCaptureCore(options, options)

  const close = () => {
    if (closed) {
      return
    }

    closed = true
    detach?.()
    detach = null
    stream.getTracks().forEach(track => track.stop())
    void context?.close().catch(() => undefined)
    context = null
  }

  try {
    context = new AudioContextCtor()

    const resampler = new Resampler(context.sampleRate, SPEECH_SAMPLE_RATE)
    const source = context.createMediaStreamSource(stream)
    // The processor must reach the destination to be pulled; silently.
    const sink = context.createGain()

    sink.gain.value = 0
    sink.connect(context.destination)

    const onSamples = (samples: Float32Array) => {
      if (!closed) {
        core.push(resampler.process(samples), options.isPlaying())
      }
    }

    detach =
      (options.forceScriptProcessor ? null : await connectWorklet(context, source, sink, onSamples)) ??
      connectScriptProcessor(context, source, sink, onSamples)

    if (context.state === 'suspended') {
      await context.resume().catch(() => undefined)
    }
  } catch (error) {
    close()
    throw error
  }

  for (const track of stream.getAudioTracks()) {
    track.addEventListener('ended', () => {
      if (!closed) {
        close()
        options.onError?.(new Error('The microphone stopped'))
      }
    })
  }

  return {
    close,
    flush: () => {
      if (!closed) {
        core.flush()
      }
    },
    reset: () => core.reset()
  }
}
