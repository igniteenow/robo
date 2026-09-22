import { describe, expect, it } from 'vitest'

import { looksLikeDroppedPath, resolveClipboardPasteMessage } from '../app/useComposerState.js'

describe('resolveClipboardPasteMessage', () => {
  it('prefers the caller-supplied override over the backend message', () => {
    // This is the exact priority bug: the hotkey-triggered text-paste
    // fallback already knows text-reading failed (missing xclip, empty
    // clipboard, etc.) and passes a specific hint — that hint must win over
    // the backend's generic image-only response, not be silently discarded.
    expect(resolveClipboardPasteMessage('Clipboard is empty, or xclip is not installed.', 'No image found in clipboard')).toBe(
      'Clipboard is empty, or xclip is not installed.'
    )
  })

  it('falls back to the backend message when no override is given', () => {
    // The explicit "attach an image" call site doesn't pass an override —
    // the backend's own message (which it can tailor, e.g. "Clipboard has
    // image but extraction failed") is the right thing to show there.
    expect(resolveClipboardPasteMessage(undefined, 'Clipboard has image but extraction failed')).toBe(
      'Clipboard has image but extraction failed'
    )
  })

  it('falls back to a default when neither override nor backend message exist', () => {
    expect(resolveClipboardPasteMessage(undefined, undefined)).toBe('No image found in clipboard')
  })

  it('an empty-string backend message still falls through to the default (not shown as blank)', () => {
    expect(resolveClipboardPasteMessage(undefined, '')).toBe('No image found in clipboard')
  })
})

describe('looksLikeDroppedPath', () => {
  it('recognizes macOS screenshot temp paths and file URIs', () => {
    expect(looksLikeDroppedPath('/var/folders/x/T/TemporaryItems/Screenshot\\ 2026-04-21\\ at\\ 1.04.43 PM.png')).toBe(
      true
    )
    expect(
      looksLikeDroppedPath('file:///var/folders/x/T/TemporaryItems/Screenshot%202026-04-21%20at%201.04.43%20PM.png')
    ).toBe(true)
  })

  it('rejects normal multiline or plain text paste', () => {
    expect(looksLikeDroppedPath('hello world')).toBe(false)
    expect(looksLikeDroppedPath('line one\nline two')).toBe(false)
  })

  it('recognizes common image file extensions', () => {
    expect(looksLikeDroppedPath('/Users/me/Desktop/photo.jpg')).toBe(true)
    expect(looksLikeDroppedPath('/Users/me/Desktop/diagram.png')).toBe(true)
    expect(looksLikeDroppedPath('/tmp/capture.webp')).toBe(true)
    expect(looksLikeDroppedPath('/tmp/image.gif')).toBe(true)
  })

  it('recognizes file:// URIs with various extensions', () => {
    expect(looksLikeDroppedPath('file:///home/user/doc.pdf')).toBe(true)
    expect(looksLikeDroppedPath('file:///tmp/screenshot.png')).toBe(true)
  })

  it('recognizes paths with spaces (not backslash-escaped)', () => {
    expect(looksLikeDroppedPath('/var/folders/x/T/TemporaryItems/Screenshot 2026-04-21 at 1.04.43 PM.png')).toBe(true)
  })

  it('rejects empty/whitespace-only input', () => {
    expect(looksLikeDroppedPath('')).toBe(false)
    expect(looksLikeDroppedPath('   ')).toBe(false)
    expect(looksLikeDroppedPath('\n')).toBe(false)
  })

  it('rejects URLs that are not file:// URIs', () => {
    expect(looksLikeDroppedPath('https://example.com/image.png')).toBe(false)
    expect(looksLikeDroppedPath('http://localhost/file.pdf')).toBe(false)
  })

  it('rejects short slash-like strings without path structure', () => {
    // No second '/' or '.' → not a plausible file path
    expect(looksLikeDroppedPath('/help')).toBe(false)
    expect(looksLikeDroppedPath('/model sonnet')).toBe(false)
    expect(looksLikeDroppedPath('/api')).toBe(false)
  })

  it('accepts absolute paths with directory separators or extensions', () => {
    expect(looksLikeDroppedPath('/usr/bin/test')).toBe(true)
    expect(looksLikeDroppedPath('/tmp/file.txt')).toBe(true)
    expect(looksLikeDroppedPath('/etc/hosts')).toBe(true) // has second /
  })
})
