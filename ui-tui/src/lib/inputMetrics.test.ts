import { describe, expect, it } from 'vitest'

import { stableComposerColumns } from './inputMetrics.js'

// appLayout.tsx renders the composer row at `width={composer.cols - 2}` and,
// inside that same row, places `GoodVibesHeart` `position="absolute"
// right={0}` alongside the prompt prefix and the TextInput. GoodVibesHeart
// only paints while its ~650ms flash animation is active, but when it does,
// it must not land on the row's last cell — which is also the last column of
// a full input line.
describe('stableComposerColumns — GoodVibesHeart never shares the last input column', () => {
  const rowWidth = (totalCols: number) => Math.max(1, totalCols - 2)

  it('leaves at least 1 spare column at the row edge across a range of widths/prompts', () => {
    for (let totalCols = 20; totalCols <= 140; totalCols += 1) {
      for (const promptWidth of [2, 4, 8, 12]) {
        for (const termuxMode of [false, true]) {
          if (promptWidth >= totalCols) {
            continue
          }

          const inputColumns = stableComposerColumns(totalCols, promptWidth, termuxMode)
          const used = promptWidth + inputColumns
          const spare = rowWidth(totalCols) - used

          // Only assert the invariant where there's room to keep it — once
          // the 1-column floor kicks in, the composer is already too narrow
          // to type comfortably and the heart overlap is the least of it.
          if (inputColumns > 1) {
            expect(spare).toBeGreaterThanOrEqual(1)
          }
        }
      }
    }
  })

  it('narrow terminals (no scrollbar gutter reserved) still carve out exactly 1 column for the heart', () => {
    // 40 total, promptWidth 8, Termux → afterPrompt 32 is below the Termux
    // scrollbar-gutter threshold (36), so nothing but the new heart
    // reservation keeps the row's right edge clear.
    expect(stableComposerColumns(40, 8, true)).toBe(29) // 40 - 8 - 2(padding) - 0(scrollbar) - 1(heart)
    expect(stableComposerColumns(10, 3, false)).toBe(4) // 10 - 3 - 2(padding) - 0(scrollbar) - 1(heart)
  })

  it('wide terminals reuse the existing scrollbar gutter for the heart (no extra reservation)', () => {
    // afterPrompt 92 clears the desktop scrollbar-gutter threshold (24), so
    // those 2 already-reserved columns cover the heart too.
    expect(stableComposerColumns(100, 8, false)).toBe(88) // 100 - 8 - 2(padding) - 2(scrollbar, covers heart) - 0
  })

  it('never returns less than 1, even when there is no room for any reservation', () => {
    expect(stableComposerColumns(6, 3, false)).toBe(1)
    expect(stableComposerColumns(1, 5, false)).toBe(1)
  })
})
