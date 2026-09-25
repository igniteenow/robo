import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

// A fresh chat's intro (logo + line) renders INSIDE the composer dock, and
// the dock's height is what `--composer-measured-height` is measured from.
// Any rule that pads the intro by that var must therefore be scoped to the
// intro's OTHER home, the thread — a box padded by its own measured height
// grows on every observation, without end, and the chat zone goes blank.
//
// Source-text guard, same category as an ESLint rule: it reads styles.css so
// the loop cannot be reintroduced by an innocent-looking selector edit.

const MEASURED_VARS = ['--composer-measured-height', '--thread-last-message-clearance', '--thread-viewport-height']

function cssRules(css: string): { declarations: string; selector: string }[] {
  const rules: { declarations: string; selector: string }[] = []

  for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectorBlock = match[1].trim()
    // The last line of the text before `{` is the selector; earlier lines are
    // comments or the tail of the previous rule.
    const selector = selectorBlock.split('\n').at(-1)?.trim() ?? ''

    rules.push({ declarations: match[2], selector })
  }

  return rules
}

describe('intro inside the composer dock', () => {
  const css = readFileSync(resolve(__dirname, '../../../styles.css'), 'utf8')

  it('is never padded by the measurement the dock itself produces', () => {
    const introRules = cssRules(css).filter(
      rule => rule.selector.includes('aui_intro') && MEASURED_VARS.some(name => rule.declarations.includes(name))
    )

    // The thread placement is the one allowed to use the measurement.
    expect(introRules.length).toBeGreaterThan(0)

    for (const rule of introRules) {
      expect(rule.selector.startsWith("[data-slot='aui_thread-content']")).toBe(true)
    }
  })
})
