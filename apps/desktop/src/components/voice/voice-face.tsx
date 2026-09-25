import { useCallback, useEffect, useRef } from 'react'

import type { VoiceConversationView } from '@/store/voice-conversation'

/** Expressions the 3D face (public/robo-face/cute-face.html) can hold. */
export type VoiceFaceEmotion = 'happy' | 'neutral' | 'sleepy' | 'thinking'

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

/** The brand (assets/brand/BRAND.md): flame-orange for the eyes and mouth,
 * the signature gradient as the frame, on the navy the logo tile uses. */
export const ROBO_BRAND_ACCENT_HEX = 'ef8a22'
export const ROBO_BRAND_GRADIENT = 'linear-gradient(135deg, #d52734, #df5a30, #ef8a22)'
export const ROBO_BRAND_NAVY = '#0a1030'

/** What the face shows for each moment of the voice chat. */
export function voiceFaceEmotion(view: Pick<VoiceConversationView, 'muted' | 'status'>): VoiceFaceEmotion {
  if (view.muted) {
    return 'sleepy'
  }

  switch (view.status) {
    case 'transcribing':

    case 'thinking':
      return 'thinking'

    case 'speaking':
      return 'happy'

    default:
      return 'neutral'
  }
}

interface VoiceFaceProps {
  className?: string
  emotion: VoiceFaceEmotion
  fps?: number
}

/**
 * Robo's animated 3D face — voice chat only. The page is loaded once with the
 * first expression; later changes are messages, so it never reloads.
 * Pointer-transparent and decorative (the caption says what is happening).
 */
export function VoiceFace({ className, emotion, fps = 30 }: VoiceFaceProps) {
  const frameRef = useRef<HTMLIFrameElement | null>(null)
  const initial = useRef({ emotion, fps })

  const syncEmotion = useCallback(() => {
    frameRef.current?.contentWindow?.postMessage({ emotion }, '*')
  }, [emotion])

  useEffect(syncEmotion, [syncEmotion])

  const { emotion: e0, fps: fps0 } = initial.current

  return (
    <iframe
      aria-hidden="true"
      className={className}
      data-emotion={emotion}
      data-testid="voice-face"
      onLoad={syncEmotion}
      ref={frameRef}
      src={`${assetPath('robo-face/cute-face.html')}?ui=0&fps=${fps0}&emotion=${e0}&accent=${ROBO_BRAND_ACCENT_HEX}`}
      style={{
        background: 'transparent',
        border: 0,
        display: 'block',
        pointerEvents: 'none'
      }}
      tabIndex={-1}
      title="Robo"
    />
  )
}
