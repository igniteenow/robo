import { atom } from 'nanostores'

// The main composer's hands-free voice conversation, mirrored app-wide so
// surfaces outside the composer (the full-screen voice view, the completion
// chime, the status face) can follow it without reaching into the composer.
// The composer hook publishes; everything else reads.

export type VoiceConversationStatus = 'idle' | 'listening' | 'speaking' | 'thinking' | 'transcribing'

export interface VoiceConversationView {
  active: boolean
  /** Mic input level 0..1 while listening. */
  level: number
  muted: boolean
  status: VoiceConversationStatus
}

export interface VoiceConversationControls {
  end: () => void
  /** Stop listening and send what was heard so far. */
  stopTurn: () => void
  toggleMute: () => void
}

const IDLE: VoiceConversationView = { active: false, level: 0, muted: false, status: 'idle' }

export const $voiceConversation = atom<VoiceConversationView>(IDLE)

let controls: VoiceConversationControls | null = null

export function setVoiceConversationView(next: VoiceConversationView): void {
  const current = $voiceConversation.get()

  if (
    current.active === next.active &&
    current.level === next.level &&
    current.muted === next.muted &&
    current.status === next.status
  ) {
    return
  }

  $voiceConversation.set(next)
}

export function registerVoiceConversationControls(next: VoiceConversationControls | null): void {
  controls = next
}

export function voiceConversationControls(): VoiceConversationControls | null {
  return controls
}

/** True while a hands-free voice chat owns the main chat. */
export function isVoiceConversationActive(): boolean {
  return $voiceConversation.get().active
}

export function resetVoiceConversation(): void {
  controls = null
  $voiceConversation.set(IDLE)
}
