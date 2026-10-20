/**
 * What the renderer needs to know about how its frames reach the screen.
 *
 * Chromium composites on the GPU when it can. Over a remote display we switch
 * that off ourselves (see detectRemoteDisplay), and inside a VM or on a machine
 * whose driver is blocklisted Chromium falls back to software compositing on
 * its own. Either way, every effect that samples the pixels under an element
 * (`backdrop-filter`) is paid for on the CPU, per frame, for the whole area it
 * covers — the single biggest reason the app feels sluggish on a server
 * reached over RDP or in a VM. The renderer reads this once at boot and turns
 * those effects off while the compositor is in software (store/visual-effects).
 *
 * Pure: `app.getGPUFeatureStatus()` is passed in, so the decision is testable.
 */

export interface RenderingInfo {
  /** True when Chromium composites frames on the CPU (no GPU acceleration). */
  software: boolean
  /** Why, in a few words — for logs and the About page, never for logic. */
  reason: string | null
}

/** The shape of `app.getGPUFeatureStatus()` this needs (the rest is noise). */
export interface GpuFeatureStatusLike {
  gpu_compositing?: unknown
}

/**
 * `gpu_compositing` is `enabled` when the GPU composites, and one of
 * `disabled_software`, `disabled_off`, `unavailable_software`,
 * `unavailable_off`, … otherwise. Anything that is not plainly enabled counts
 * as software — including a missing or unreadable status, which is what a GPU
 * process that failed to start looks like.
 */
export function renderingInfoFrom(
  gpuFeatureStatus: GpuFeatureStatusLike | null | undefined,
  remoteDisplayReason: string | null
): RenderingInfo {
  if (remoteDisplayReason) {
    return { software: true, reason: `remote display: ${remoteDisplayReason}` }
  }

  const compositing = gpuFeatureStatus?.gpu_compositing

  if (typeof compositing !== 'string' || compositing.trim() === '') {
    return { software: true, reason: 'gpu status unavailable' }
  }

  if (compositing === 'enabled' || compositing.startsWith('enabled')) {
    return { software: false, reason: null }
  }

  return { software: true, reason: `gpu compositing ${compositing}` }
}
