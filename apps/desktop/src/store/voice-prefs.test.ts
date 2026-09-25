import { describe, expect, it, vi } from 'vitest'

vi.mock('@/robo', () => ({
  getRoboConfigRecord: vi.fn(async () => ({})),
  saveRoboConfig: vi.fn(async () => undefined)
}))

import {
  $thinkingSoundEnabled,
  $voiceStopPhrase,
  applyThinkingSoundFromConfig,
  applyVoiceStopPhraseFromConfig,
  thinkingSoundAmbientFromConfig
} from './voice-prefs'

describe('applyVoiceStopPhraseFromConfig', () => {
  it('defaults to "stop" when the key is absent (backend default applies)', () => {
    applyVoiceStopPhraseFromConfig({ voice: {} })
    expect($voiceStopPhrase.get()).toBe('stop')

    applyVoiceStopPhraseFromConfig(null)
    expect($voiceStopPhrase.get()).toBe('stop')
  })

  it('uses the first configured phrase so a custom phrase renders correctly', () => {
    applyVoiceStopPhraseFromConfig({ voice: { stop_phrases: ['goodbye robo', 'stop'] } })
    expect($voiceStopPhrase.get()).toBe('goodbye robo')
  })

  it('coerces a bare string like the backend does', () => {
    applyVoiceStopPhraseFromConfig({ voice: { stop_phrases: 'halt' } })
    expect($voiceStopPhrase.get()).toBe('halt')
  })

  it('null phrase when stop phrases are disabled — no notice is shown', () => {
    applyVoiceStopPhraseFromConfig({ voice: { stop_phrases: [] } })
    expect($voiceStopPhrase.get()).toBeNull()
  })

  it('malformed entries are skipped; all-blank list disables', () => {
    applyVoiceStopPhraseFromConfig({ voice: { stop_phrases: ['  ', ''] } })
    expect($voiceStopPhrase.get()).toBeNull()
  })
})

// The turn-long blips are an explicit opt-in, the same as the backend's
// voice.thinking_sound modes: a voice chat is silent while Robo works unless
// the user asked for "ambient". The old gate treated anything but `false` as
// on, so the default "cue" (blips only while transcribing, on the backend)
// also switched the desktop's turn-long loop on — the noise people reported.
describe('applyThinkingSoundFromConfig', () => {
  it('is off for the defaults and for the transcription-only cue', () => {
    for (const value of [undefined, true, false, 'cue', 'on', 'off', 'transcribing']) {
      applyThinkingSoundFromConfig({ voice: { thinking_sound: value } })
      expect($thinkingSoundEnabled.get()).toBe(false)
    }

    applyThinkingSoundFromConfig({})
    expect($thinkingSoundEnabled.get()).toBe(false)
    applyThinkingSoundFromConfig(null)
    expect($thinkingSoundEnabled.get()).toBe(false)
  })

  it('is on only for the explicit ambient opt-in', () => {
    for (const value of ['ambient', 'Always', ' turn ']) {
      applyThinkingSoundFromConfig({ voice: { thinking_sound: value } })
      expect($thinkingSoundEnabled.get()).toBe(true)
    }

    expect(thinkingSoundAmbientFromConfig('ambient')).toBe(true)
    expect(thinkingSoundAmbientFromConfig(true)).toBe(false)
  })
})
