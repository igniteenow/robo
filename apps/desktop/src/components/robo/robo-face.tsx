import { useStore } from '@nanostores/react'
import { useCallback, useEffect, useRef } from 'react'

import { $petState, type PetState } from '@/store/pet'

export type RoboEmotion = 'confused' | 'happy' | 'neutral' | 'sad' | 'surprised'

export function emotionForPetState(state: PetState): RoboEmotion {
  switch (state) {
    case 'failed':
      return 'sad'
    case 'review':
    case 'waiting':
      return 'confused'
    case 'run':
      return 'surprised'
    case 'jump':
    case 'wave':
      return 'happy'
    default:
      return 'neutral'
  }
}

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

interface RoboFaceProps {
  className?: string
  emotion: RoboEmotion
  fps?: number
}

export function RoboFace({ className, emotion, fps = 30 }: RoboFaceProps) {
  const frameRef = useRef<HTMLIFrameElement | null>(null)

  const syncEmotion = useCallback(() => {
    frameRef.current?.contentWindow?.postMessage({ emotion }, '*')
  }, [emotion])

  useEffect(syncEmotion, [syncEmotion])

  return (
    <iframe
      aria-hidden="true"
      className={className}
      onLoad={syncEmotion}
      ref={frameRef}
      src={`${assetPath('robo-face/cute-face.html')}?ui=0&fps=${fps}&emotion=${emotion}`}
      style={{
        background: 'transparent',
        border: 0,
        display: 'block',
        pointerEvents: 'none'
      }}
      title="Robo"
    />
  )
}

export function RoboLiveFace({ className, fps = 30 }: Omit<RoboFaceProps, 'emotion'>) {
  const state = useStore($petState)

  return <RoboFace className={className} emotion={emotionForPetState(state)} fps={fps} />
}
