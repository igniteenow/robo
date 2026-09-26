import { describe, expect, it } from 'vitest'

import { encodeWav, levelDb, Resampler, SampleRing } from './pcm-audio'

function sine(frequency: number, rate: number, seconds: number, amplitude = 0.5): Float32Array {
  const out = new Float32Array(Math.round(rate * seconds))

  for (let index = 0; index < out.length; index += 1) {
    out[index] = amplitude * Math.sin((2 * Math.PI * frequency * index) / rate)
  }

  return out
}

/** Upward zero crossings per second — the tone's frequency. */
function frequencyOf(samples: Float32Array, rate: number): number {
  let crossings = 0

  for (let index = 1; index < samples.length; index += 1) {
    if (samples[index - 1] < 0 && samples[index] >= 0) {
      crossings += 1
    }
  }

  return crossings / (samples.length / rate)
}

function resampleInChunks(resampler: Resampler, input: Float32Array, chunk: number): Float32Array {
  const parts: Float32Array[] = []

  for (let offset = 0; offset < input.length; offset += chunk) {
    parts.push(resampler.process(input.subarray(offset, offset + chunk)))
  }

  const out = new Float32Array(parts.reduce((sum, part) => sum + part.length, 0))
  let at = 0

  for (const part of parts) {
    out.set(part, at)
    at += part.length
  }

  return out
}

describe('levelDb', () => {
  it('measures RMS in dBFS, with a floor for digital silence', () => {
    expect(levelDb(new Float32Array(320))).toBe(-100)
    expect(levelDb(sine(440, 16_000, 0.1, 1))).toBeCloseTo(-3, 0)
    expect(levelDb(sine(440, 16_000, 0.1, 0.1))).toBeCloseTo(-23, 0)
  })
})

describe('Resampler', () => {
  it('48 kHz → 16 kHz keeps the pitch and a third of the samples', () => {
    const input = sine(440, 48_000, 1)
    const output = new Resampler(48_000).process(input)

    expect(Math.abs(output.length - 16_000)).toBeLessThanOrEqual(2)
    expect(frequencyOf(output, 16_000)).toBeCloseTo(440, -1)
  })

  it('is seamless across chunk boundaries of any size', () => {
    const input = sine(300, 44_100, 0.5)
    const whole = new Resampler(44_100).process(input)
    const chunked = resampleInChunks(new Resampler(44_100), input, 1_023)

    expect(Math.abs(chunked.length - whole.length)).toBeLessThanOrEqual(1)

    for (let index = 0; index < Math.min(whole.length, chunked.length); index += 97) {
      expect(chunked[index]).toBeCloseTo(whole[index], 5)
    }

    expect(frequencyOf(chunked, 16_000)).toBeCloseTo(300, -1)
  })

  it('upsamples a low-rate microphone', () => {
    const output = new Resampler(8_000).process(sine(200, 8_000, 1))

    expect(Math.abs(output.length - 16_000)).toBeLessThanOrEqual(2)
    expect(frequencyOf(output, 16_000)).toBeCloseTo(200, -1)
  })

  it('passes 16 kHz through untouched', () => {
    const input = sine(200, 16_000, 0.1)

    expect(new Resampler(16_000).process(input)).toEqual(input)
  })
})

describe('SampleRing', () => {
  it('reads back by absolute index across the wrap', () => {
    const ring = new SampleRing(10)

    ring.write(Float32Array.from([0, 1, 2, 3, 4, 5, 6, 7]))
    ring.write(Float32Array.from([8, 9, 10, 11, 12]))

    expect(ring.end).toBe(13)
    expect(ring.start).toBe(3)
    expect(Array.from(ring.read(5, 12))).toEqual([5, 6, 7, 8, 9, 10, 11])
    // Asking for what has already been overwritten returns what is left.
    expect(Array.from(ring.read(0, 5))).toEqual([3, 4])
  })

  it('keeps only the tail of a chunk larger than itself', () => {
    const ring = new SampleRing(4)

    ring.write(Float32Array.from([1, 2, 3, 4, 5, 6]))

    expect(ring.end).toBe(6)
    expect(Array.from(ring.read(0))).toEqual([3, 4, 5, 6])
  })
})

describe('encodeWav', () => {
  it('writes a 16-bit mono PCM WAV', () => {
    const bytes = encodeWav(Float32Array.from([0, 1, -1, 0.5]), 16_000)
    const view = new DataView(bytes)
    const tag = (offset: number) => String.fromCharCode(...new Uint8Array(bytes, offset, 4))

    expect(bytes.byteLength).toBe(44 + 8)
    expect(tag(0)).toBe('RIFF')
    expect(tag(8)).toBe('WAVE')
    expect(tag(36)).toBe('data')
    expect(view.getUint16(22, true)).toBe(1)
    expect(view.getUint32(24, true)).toBe(16_000)
    expect(view.getUint16(34, true)).toBe(16)
    expect(view.getInt16(44, true)).toBe(0)
    expect(view.getInt16(46, true)).toBe(32_767)
    expect(view.getInt16(48, true)).toBe(-32_768)
    expect(view.getInt16(50, true)).toBe(16_383)
  })
})
