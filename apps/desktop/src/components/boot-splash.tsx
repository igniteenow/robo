import { useLayoutEffect } from 'react'

import { removeBootSplash } from '@/lib/boot-splash'

/**
 * Takes the index.html boot splash down inside the app's first commit — a
 * layout effect runs before that frame paints, so the hand-off from splash to
 * real UI is a single frame with no overlap, however slow the machine.
 */
export function BootSplashRemover() {
  useLayoutEffect(() => {
    removeBootSplash(document)
  }, [])

  return null
}
