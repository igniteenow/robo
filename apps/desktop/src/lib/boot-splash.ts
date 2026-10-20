/**
 * The boot splash is static markup in index.html: it is part of a new window's
 * very first frame, long before this bundle has run, so the window never opens
 * onto a bare background. Once the app has committed its first tree the splash
 * has done its job; `removeBootSplash` takes it down (idempotent, safe to call
 * from any window, including ones that never showed it).
 */

export const BOOT_SPLASH_ID = 'boot-splash'
export const BOOT_SPLASH_ATTR = 'data-boot-splash'

interface DocumentLike {
  documentElement: { removeAttribute: (name: string) => void }
  getElementById: (id: string) => { remove: () => void } | null
}

export function removeBootSplash(doc: DocumentLike): void {
  doc.getElementById(BOOT_SPLASH_ID)?.remove()
  doc.documentElement.removeAttribute(BOOT_SPLASH_ATTR)
}
