import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/i18n'
import { resetBinding, setBinding } from '@/store/keybinds'
import {
  registerVoiceConversationControls,
  resetVoiceConversation,
  setVoiceConversationView,
  type VoiceConversationView
} from '@/store/voice-conversation'
import { $voicePlayback, setVoicePlaybackState } from '@/store/voice-playback'
import { $voiceStopPhrase } from '@/store/voice-prefs'
import { markVoiceTurn, resetVoiceTiming, setVoicePlaybackMode } from '@/store/voice-timing'

import { VoiceConversationScreen } from './voice-conversation-screen'
import { voiceFaceEmotion } from './voice-face'

// Hands-free voice chat takes over the chat zone: Robo's face in a ring that
// breathes with the mic + what Robo is doing + the controls, nothing else.
// The transcript keeps filling underneath and is back the moment the chat
// ends.

const view = (over: Partial<VoiceConversationView> = {}): VoiceConversationView => ({
  active: true,
  level: 0,
  muted: false,
  status: 'listening',
  ...over
})

/** Sound is (or is not) coming out of the speaker right now. */
const audible = (speaking: boolean) =>
  setVoicePlaybackState({
    audioElement: null,
    messageId: null,
    sequence: $voicePlayback.get().sequence,
    source: speaking ? 'voice-conversation' : null,
    status: speaking ? 'speaking' : 'idle'
  })

function renderScreen() {
  return render(
    <I18nProvider configClient={null} initialLocale="en">
      <VoiceConversationScreen />
    </I18nProvider>
  )
}

beforeEach(() => {
  resetVoiceConversation()
  resetVoiceTiming()
  $voiceStopPhrase.set('stop')
})

afterEach(() => {
  cleanup()
  resetVoiceConversation()
  resetVoiceTiming()
  audible(false)
})

describe('voiceFaceEmotion', () => {
  it('reads the moment of the conversation', () => {
    expect(voiceFaceEmotion({ muted: false, status: 'listening' })).toBe('neutral')
    expect(voiceFaceEmotion({ muted: false, status: 'transcribing' })).toBe('thinking')
    expect(voiceFaceEmotion({ muted: false, status: 'thinking' })).toBe('thinking')
    expect(voiceFaceEmotion({ muted: false, status: 'speaking' })).toBe('happy')
    expect(voiceFaceEmotion({ muted: true, status: 'speaking' })).toBe('sleepy')
  })
})

describe('VoiceConversationScreen', () => {
  it('stays out of the way until a voice chat is on', () => {
    renderScreen()
    expect(screen.queryByRole('dialog')).toBeNull()

    act(() => setVoiceConversationView(view()))
    expect(screen.getByRole('dialog')).not.toBeNull()

    act(() => setVoiceConversationView(view({ active: false, status: 'idle' })))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('covers the chat zone and says what Robo is doing, in words', () => {
    act(() => setVoiceConversationView(view()))
    renderScreen()

    const dialog = screen.getByRole('dialog')

    expect(dialog.className).toContain('fixed')
    expect(dialog.className).toContain('--workspace-left')
    expect(dialog.className).toContain('--workspace-right')
    expect(dialog.className).toContain('--titlebar-height')
    expect(dialog.textContent).toContain('Listening…')

    act(() => setVoiceConversationView(view({ status: 'transcribing' })))
    expect(dialog.textContent).toContain('Got it…')

    act(() => setVoiceConversationView(view({ status: 'thinking' })))
    expect(dialog.textContent).toContain('Thinking…')

    // The loop says "speaking" from the first reply text; the screen says it
    // only once sound is actually playing.
    act(() => setVoiceConversationView(view({ status: 'speaking' })))
    expect(dialog.textContent).toContain('Thinking…')
    expect(dialog.getAttribute('data-voice-status')).toBe('thinking')

    act(() => audible(true))
    expect(dialog.textContent).toContain('Speaking…')
    expect(dialog.getAttribute('data-voice-status')).toBe('speaking')

    act(() => audible(false))
    act(() => setVoiceConversationView(view({ muted: true })))
    expect(dialog.textContent).toContain('Mic muted')
    expect(dialog.textContent).toContain('Say “stop” to end the voice chat')
  })

  it('names the live end-chat chord in the hint, and no chord when unbound', () => {
    act(() => setVoiceConversationView(view()))
    const { unmount } = renderScreen()
    const dialog = screen.getByRole('dialog')

    // jsdom is not macOS, so the shipped default is Alt+B (⌃B folds into the
    // ⌘B/Ctrl+B sidebar chord there). A rebind shows up live; unbound drops
    // the chord instead of advertising one that does nothing.
    expect(dialog.textContent).toContain('Say “stop” to end the voice chat · Alt+B')

    act(() => setBinding('composer.voice', ['mod+shift+v']))
    expect(dialog.textContent).toContain('· Ctrl+Shift+V')

    act(() => setBinding('composer.voice', []))
    expect(dialog.textContent).toContain('Say “stop” to end the voice chat')
    expect(dialog.textContent).not.toContain('·')

    act(() => $voiceStopPhrase.set(''))
    expect(dialog.textContent).toContain('End voice chat stops it')

    unmount()
    resetBinding('composer.voice')
  })

  it('shows the 3D face in a ring that breathes with the mic', () => {
    act(() => setVoiceConversationView(view({ level: 0.5 })))
    renderScreen()

    const face = screen.getByTestId('voice-face') as HTMLIFrameElement
    const ring = screen.getByTestId('voice-ring')

    expect(face.src).toContain('robo-face/cute-face.html')
    expect(face.src).toContain('accent=ef8a22')
    expect(face.getAttribute('data-emotion')).toBe('neutral')
    expect(face.style.pointerEvents).toBe('none')
    expect(ring.style.transform).toBe('scale(1.09)')

    act(() => {
      setVoiceConversationView(view({ level: 0.5, status: 'speaking' }))
      audible(true)
    })
    expect(face.getAttribute('data-emotion')).toBe('happy')
    act(() => {
      audible(false)
      setVoiceConversationView(view({ level: 0.5 }))
    })

    act(() => setVoiceConversationView(view({ level: 1 })))
    expect(ring.style.transform).toBe('scale(1.18)')

    // While Robo works the ring pulses on its own; the mic level is ignored.
    act(() => setVoiceConversationView(view({ level: 1, status: 'thinking' })))
    expect(ring.style.transform).toBe('scale(1)')
    expect(ring.className).toContain('animate-pulse')
  })

  it('shows where the time went in the last turn', () => {
    act(() => setVoiceConversationView(view({ status: 'speaking' })))
    renderScreen()
    expect(screen.queryByTestId('voice-timing')).toBeNull()

    act(() => {
      markVoiceTurn('heard', 0)
      markVoiceTurn('transcribed', 1_100)
      markVoiceTurn('firstText', 3_000)
      setVoicePlaybackMode('sentence')
      markVoiceTurn('firstAudio', 3_600)
    })
    expect(screen.getByTestId('voice-timing').textContent).toBe(
      'words 1.1 s · first word 1.9 s · voice 0.6 s · total 3.6 s · sentence by sentence'
    )
  })

  it('drives the composer’s conversation through the registered controls', () => {
    const controls = { end: vi.fn(), stopTurn: vi.fn(), toggleMute: vi.fn() }

    registerVoiceConversationControls(controls)
    act(() => setVoiceConversationView(view()))
    renderScreen()

    fireEvent.click(screen.getByRole('button', { name: 'Send now' }))
    expect(controls.stopTurn).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Mute mic' }))
    expect(controls.toggleMute).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'End voice chat' }))
    expect(controls.end).toHaveBeenCalledTimes(1)

    // "Send now" only makes sense while the mic is open.
    act(() => setVoiceConversationView(view({ status: 'thinking' })))
    expect(screen.queryByRole('button', { name: 'Send now' })).toBeNull()
  })
})
