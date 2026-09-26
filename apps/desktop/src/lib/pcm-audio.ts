/**
 * pcm-audio.ts — the small signal-processing pieces behind the voice chat's
 * capture engine (lib/voice-capture): resample the microphone to 16 kHz,
 * measure a frame's level, keep recent audio in a ring, and wrap an
 * utterance as a WAV file for the transcriber.
 *
 * 16 kHz mono is what Whisper-family models consume, so the backend decodes a
 * third of the samples a 48 kHz recording would carry and nothing is lost.
 * Pure, allocation-light and DOM-free, so it is unit-tested directly.
 */

export const SPEECH_SAMPLE_RATE = 16_000

/** Level of `samples` as RMS dBFS (−100 for digital silence). */
export function levelDb(samples: Float32Array): number {
  if (!samples.length) {
    return -100
  }

  let sum = 0

  for (const value of samples) {
    sum += value * value
  }

  const rms = Math.sqrt(sum / samples.length)

  return rms > 1e-5 ? 20 * Math.log10(rms) : -100
}

/**
 * Streaming resampler to `outRate`. Downsampling averages each output
 * sample's span of input (a box filter — enough anti-aliasing for speech
 * recognition); upsampling interpolates linearly. Chunks may be any length;
 * state carries across them, so the output is gap-free.
 */
export class Resampler {
  private pending = new Float32Array(0)
  /** Absolute input index of `pending[0]`. */
  private pendingStart = 0
  /** Absolute index of the next output sample. */
  private next = 0

  constructor(
    readonly inRate: number,
    readonly outRate: number = SPEECH_SAMPLE_RATE
  ) {}

  process(input: Float32Array): Float32Array {
    if (this.inRate === this.outRate) {
      return input.slice()
    }

    const joined = new Float32Array(this.pending.length + input.length)
    joined.set(this.pending)
    joined.set(input, this.pending.length)

    const available = this.pendingStart + joined.length
    const output: number[] = []

    // Integer bookkeeping (k·in/out), so the result does not depend on how
    // the stream was chunked.
    if (this.inRate > this.outRate) {
      // Output k averages input [k·in/out, (k+1)·in/out).
      for (;;) {
        const from = Math.floor((this.next * this.inRate) / this.outRate)
        const to = Math.floor(((this.next + 1) * this.inRate) / this.outRate)

        if (to > available) {
          break
        }

        let sum = 0

        for (let index = from; index < to; index += 1) {
          sum += joined[index - this.pendingStart]
        }

        output.push(sum / Math.max(1, to - from))
        this.next += 1
      }
    } else {
      // Output k interpolates between the two input samples around k·in/out.
      for (;;) {
        const scaled = this.next * this.inRate
        const base = Math.floor(scaled / this.outRate)

        if (base + 1 >= available) {
          break
        }

        const fraction = (scaled % this.outRate) / this.outRate
        const at = base - this.pendingStart

        output.push(joined[at] * (1 - fraction) + joined[at + 1] * fraction)
        this.next += 1
      }
    }

    // Keep only what the next output still needs.
    const needed = Math.floor((this.next * this.inRate) / this.outRate)
    const keepFrom = Math.min(joined.length, Math.max(0, needed - this.pendingStart))

    this.pending = joined.slice(keepFrom)
    this.pendingStart += keepFrom

    return Float32Array.from(output)
  }
}

/**
 * A ring of the most recent samples, addressed by absolute sample index
 * (samples ever written), so a caller can remember "the utterance started at
 * sample N" and read it back later.
 */
export class SampleRing {
  private readonly data: Float32Array
  private written = 0

  constructor(capacity: number) {
    this.data = new Float32Array(capacity)
  }

  /** Absolute index one past the newest sample. */
  get end(): number {
    return this.written
  }

  /** Oldest absolute index still held. */
  get start(): number {
    return Math.max(0, this.written - this.data.length)
  }

  write(samples: Float32Array): void {
    let offset = 0

    // A chunk larger than the ring keeps only its tail.
    if (samples.length > this.data.length) {
      offset = samples.length - this.data.length
      this.written += offset
    }

    while (offset < samples.length) {
      const at = this.written % this.data.length
      const count = Math.min(samples.length - offset, this.data.length - at)

      this.data.set(samples.subarray(offset, offset + count), at)
      offset += count
      this.written += count
    }
  }

  /** Samples in [from, to), clamped to what the ring still holds. */
  read(from: number, to: number = this.written): Float32Array {
    const first = Math.max(this.start, Math.min(from, this.written))
    const last = Math.max(first, Math.min(to, this.written))
    const out = new Float32Array(last - first)
    let offset = 0

    for (let index = first; index < last; ) {
      const at = index % this.data.length
      const count = Math.min(last - index, this.data.length - at)

      out.set(this.data.subarray(at, at + count), offset)
      offset += count
      index += count
    }

    return out
  }
}

/** 16-bit PCM mono WAV bytes for `samples` (−1..1). */
export function encodeWav(samples: Float32Array, sampleRate: number = SPEECH_SAMPLE_RATE): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)

  const ascii = (offset: number, text: string) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index))
    }
  }

  ascii(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  ascii(8, 'WAVE')
  ascii(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt chunk size
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // byte rate
  view.setUint16(32, 2, true) // block align
  view.setUint16(34, 16, true) // bits per sample
  ascii(36, 'data')
  view.setUint32(40, samples.length * 2, true)

  for (let index = 0; index < samples.length; index += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[index]))

    view.setInt16(44 + index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
  }

  return buffer
}
