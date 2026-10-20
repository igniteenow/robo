import assert from 'node:assert/strict'

import { test } from 'vitest'

import { renderingInfoFrom } from './rendering-info'

test('a GPU-composited session keeps the full effects', () => {
  assert.deepEqual(renderingInfoFrom({ gpu_compositing: 'enabled' }, null), { software: false, reason: null })
  assert.equal(renderingInfoFrom({ gpu_compositing: 'enabled_on' }, null).software, false)
})

test('software compositing is reported with its Chromium status', () => {
  for (const status of ['disabled_software', 'disabled_off', 'unavailable_software', 'unavailable_off']) {
    const info = renderingInfoFrom({ gpu_compositing: status }, null)

    assert.equal(info.software, true, status)
    assert.equal(info.reason, `gpu compositing ${status}`)
  }
})

test('a remote display is software whatever the GPU says', () => {
  const info = renderingInfoFrom({ gpu_compositing: 'enabled' }, 'rdp (SESSIONNAME=RDP-Tcp#3)')

  assert.equal(info.software, true)
  assert.equal(info.reason, 'remote display: rdp (SESSIONNAME=RDP-Tcp#3)')
})

test('no readable GPU status counts as software (the GPU process did not come up)', () => {
  assert.equal(renderingInfoFrom(null, null).software, true)
  assert.equal(renderingInfoFrom(undefined, null).software, true)
  assert.equal(renderingInfoFrom({}, null).software, true)
  assert.equal(renderingInfoFrom({ gpu_compositing: '' }, null).software, true)
  assert.equal(renderingInfoFrom({ gpu_compositing: 42 }, null).software, true)
})
