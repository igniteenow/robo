import { OverlayView } from './overlay-view'

interface OverlayLoadingProps {
  onClose: () => void
}

/**
 * Suspense fallback for the lazy overlay views (settings, command center,
 * agents, …): the same card the view will fill, up at once. With a `null`
 * fallback a click on Settings showed nothing at all until the view's chunk
 * had loaded and evaluated — a dead click of a second or more on a slow
 * machine. Esc and the close button work on it just like on the real view.
 */
export function OverlayLoading({ onClose }: OverlayLoadingProps) {
  return (
    <OverlayView onClose={onClose}>
      <div aria-busy="true" className="flex-1" />
    </OverlayView>
  )
}
