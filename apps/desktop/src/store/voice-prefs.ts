import { atom } from 'nanostores'

import { getRoboConfigRecord, saveRoboConfig } from '@/robo'

// "Read replies aloud" — mirrors the canonical `voice.auto_tts` config key (also
// in Settings → Voice, honored by the messaging gateway) so the composer toggle
// and the Settings switch are one source of truth, not two that can disagree.
export const $autoSpeakReplies = atom<boolean>(false)

/** Seed the atom from a loaded config payload (mount / refresh). */
export function applyAutoSpeakFromConfig(config: { voice?: { auto_tts?: unknown } | null } | null | undefined) {
  $autoSpeakReplies.set(Boolean(config?.voice?.auto_tts))
}

// First configured `voice.stop_phrases` entry — drives the "Say "stop" to end
// the voice chat" notice shown when a voice conversation starts. `null` means
// the user disabled stop phrases (`stop_phrases: []`), so no notice is shown.
// Defaults to "stop" (the backend default) before config loads.
export const $voiceStopPhrase = atom<string | null>('stop')

/** Seed the stop-phrase atom from a loaded config payload (mount / refresh). */
export function applyVoiceStopPhraseFromConfig(
  config: { voice?: { stop_phrases?: unknown } | null } | null | undefined
) {
  const raw = config?.voice?.stop_phrases

  if (raw === undefined) {
    // Key absent — backend default applies.
    $voiceStopPhrase.set('stop')

    return
  }

  const list = Array.isArray(raw) ? raw : typeof raw === 'string' ? [raw] : []
  const first = list.map(entry => String(entry).trim()).find(entry => entry.length > 0)

  $voiceStopPhrase.set(first ?? null)
}

// `voice.thinking_sound` — the turn-long bubble blips while the agent works
// during a voice conversation. Same meaning as the backend's mode: only the
// explicit "ambient" opt-in (also "always" / "turn") turns the loop on. The
// default (true / "cue") keeps a voice chat silent while Robo works — nothing
// but Robo talking; the short transcription cue is the backend's, not ours.
export const $thinkingSoundEnabled = atom<boolean>(false)

const AMBIENT_MODES = new Set(['ambient', 'always', 'turn'])

/** True only for the explicit turn-long opt-in. */
export function thinkingSoundAmbientFromConfig(value: unknown): boolean {
  return typeof value === 'string' && AMBIENT_MODES.has(value.trim().toLowerCase())
}

/** Seed the thinking-sound gate from a loaded config payload. */
export function applyThinkingSoundFromConfig(
  config: { voice?: { thinking_sound?: unknown } | null } | null | undefined
) {
  $thinkingSoundEnabled.set(thinkingSoundAmbientFromConfig(config?.voice?.thinking_sound))
}

/**
 * Flip the preference and persist it. Optimistic — the atom updates instantly and
 * reverts if the config write fails. Read-modify-writes the whole record (the
 * same path the Settings page uses; there's no partial-update endpoint).
 */
export async function setAutoSpeakReplies(enabled: boolean): Promise<void> {
  const previous = $autoSpeakReplies.get()

  if (previous === enabled) {
    return
  }

  $autoSpeakReplies.set(enabled)

  try {
    const record = await getRoboConfigRecord()
    const voice = record.voice && typeof record.voice === 'object' ? (record.voice as Record<string, unknown>) : {}

    await saveRoboConfig({ ...record, voice: { ...voice, auto_tts: enabled } })
  } catch (error) {
    $autoSpeakReplies.set(previous)
    throw error
  }
}
