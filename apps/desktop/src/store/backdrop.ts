import { atom } from 'nanostores'

import { persistBoolean, storedBoolean, writeKey } from '@/lib/storage'

// v2: the faint circuit image now starts OFF. Behind a dark theme it turned the
// whole transcript murky, so the clean surface is the default. v1 was written
// for every install on its first launch (the subscribe below persists the
// initial value), so only a new key can change the default for existing users;
// Settings → Appearance still turns it back on.
const KEY = 'robo.desktop.backdrop.v2'

writeKey('robo.desktop.backdrop.v1', null)

/** Whether the faint statue image renders behind the chat transcript. */
export const $backdrop = atom(storedBoolean(KEY, false))

$backdrop.subscribe(on => persistBoolean(KEY, on))

export function setBackdrop(on: boolean) {
  $backdrop.set(on)
}
