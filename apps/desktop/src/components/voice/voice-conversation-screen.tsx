import { useStore } from '@nanostores/react'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { useI18n } from '@/i18n'
import { useKeybindHint } from '@/lib/keybinds/use-keybind-hint'
import { $voiceConversation, voiceConversationControls, type VoiceConversationStatus } from '@/store/voice-conversation'
import { $voicePlayback } from '@/store/voice-playback'
import { $voiceStopPhrase } from '@/store/voice-prefs'
import { $voiceTurnTiming, describeVoiceTiming } from '@/store/voice-timing'
import { isSecondaryWindow } from '@/store/windows'

import { ROBO_BRAND_GRADIENT, ROBO_BRAND_NAVY, VoiceFace, voiceFaceEmotion } from './voice-face'

/** The face's box in the voice view, px. */
export const VOICE_FACE_PX = 220

/**
 * Hands-free voice chat, full screen: while it is on, the chat zone shows
 * only Robo's face, what it is doing, and the controls — no transcript, no
 * composer. Everything Robo and the user say still lands in the conversation
 * underneath; ending the voice chat lifts this view and the whole exchange is
 * there to read. Covers exactly the chat zone (the layout tree publishes its
 * edges as --workspace-left/right) under the titlebar.
 */
export function VoiceConversationScreen() {
  const { t } = useI18n()
  const view = useStore($voiceConversation)
  const playback = useStore($voicePlayback)
  const stopPhrase = useStore($voiceStopPhrase)
  const timing = useStore($voiceTurnTiming)
  // The chord that ends the chat is whatever `composer.voice` is bound to on
  // this platform (⌃B on macOS, Alt+B elsewhere, or a user rebind) — never a
  // hard-coded label that may not exist here.
  const voiceKey = useKeybindHint('composer.voice')

  if (!view.active || isSecondaryWindow()) {
    return null
  }

  const copy = t.voiceScreen
  const timingLine = describeVoiceTiming(timing, copy.timing)
  // "Speaking…" only while sound is actually coming out. The loop's own
  // status turns to speaking when the first reply TEXT lands, seconds before
  // the first sentence is synthesized — that gap read as Robo "speaking" in
  // silence, forever when the audio never came.
  const audible = playback.status === 'speaking'
  const status: VoiceConversationStatus = view.status === 'speaking' && !audible ? 'thinking' : view.status
  const listening = status === 'listening' && !view.muted
  const caption = view.muted ? copy.muted : copy.status[status]
  const controls = voiceConversationControls()
  // The ring breathes with the mic: 0 → resting size, 1 → +18%; it pulses
  // slowly while Robo works and holds still while it talks.
  const level = listening ? Math.min(1, Math.max(0, view.level)) : 0
  const ringScale = listening ? 1 + level * 0.18 : 1

  const ringClass =
    listening || status === 'speaking' || view.muted ? 'transition-transform duration-100' : 'animate-pulse'

  return (
    <div
      aria-label={copy.title}
      className="fixed top-[var(--titlebar-height,34px)] right-[var(--workspace-right,0px)] bottom-0 left-[var(--workspace-left,0px)] z-45 flex flex-col items-center justify-center gap-6 select-none"
      data-voice-status={view.muted ? 'muted' : status}
      role="dialog"
      style={{ background: 'var(--ui-chat-surface-background, var(--dt-background))' }}
    >
      <div
        className="relative flex items-center justify-center"
        style={{ height: VOICE_FACE_PX + 56, width: VOICE_FACE_PX + 56 }}
      >
        <div
          aria-hidden="true"
          className={ringClass}
          data-testid="voice-ring"
          style={{
            border: `2px solid color-mix(in srgb, var(--dt-primary) ${listening ? 70 : 30}%, transparent)`,
            borderRadius: 999,
            height: VOICE_FACE_PX + 44,
            position: 'absolute',
            transform: `scale(${ringScale})`,
            width: VOICE_FACE_PX + 44
          }}
        />
        <div
          style={{
            background: ROBO_BRAND_GRADIENT,
            borderRadius: 52,
            boxShadow: '0 24px 70px rgba(10, 16, 48, .4)',
            padding: 4
          }}
        >
          <div
            style={{
              background: ROBO_BRAND_NAVY,
              borderRadius: 48,
              height: VOICE_FACE_PX,
              overflow: 'hidden',
              width: VOICE_FACE_PX
            }}
          >
            <VoiceFace className="size-full" emotion={voiceFaceEmotion({ muted: view.muted, status })} />
          </div>
        </div>
      </div>

      <div className="flex flex-col items-center gap-1.5 text-center">
        <div className="text-lg font-medium" style={{ color: 'var(--dt-foreground)' }}>
          {caption}
        </div>
        <div className="text-sm" style={{ color: 'var(--dt-muted-foreground)' }}>
          {copy.subtitle}
        </div>
        {timingLine && (
          <div
            className="font-mono text-[11px] tabular-nums"
            data-testid="voice-timing"
            style={{ color: 'var(--dt-muted-foreground)', opacity: 0.8 }}
          >
            {timingLine}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <Button
          aria-label={view.muted ? copy.unmute : copy.mute}
          aria-pressed={view.muted}
          onClick={() => controls?.toggleMute()}
          size="sm"
          type="button"
          variant="ghost"
        >
          <Codicon name={view.muted ? 'mic-off' : 'mic'} size="1rem" />
          <span>{view.muted ? copy.unmute : copy.mute}</span>
        </Button>
        {listening && (
          <Button
            aria-label={copy.sendNow}
            onClick={() => controls?.stopTurn()}
            size="sm"
            type="button"
            variant="ghost"
          >
            <Codicon name="send" size="1rem" />
            <span>{copy.sendNow}</span>
          </Button>
        )}
        <Button aria-label={copy.end} onClick={() => controls?.end()} size="sm" type="button">
          <Codicon name="close" size="1rem" />
          <span>{copy.end}</span>
        </Button>
      </div>

      <div className="text-xs" style={{ color: 'var(--dt-muted-foreground)' }}>
        {stopPhrase ? copy.hintWithPhrase(stopPhrase, voiceKey) : copy.hint(voiceKey)}
      </div>
    </div>
  )
}
