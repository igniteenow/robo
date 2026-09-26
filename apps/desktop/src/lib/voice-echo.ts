// Is a barge-in capture really the user talking over Robo?
//
// The barge-in monitor trips on SOUND, not on words: a cough, a door, a TV —
// and, on laptop speakers, Robo's own voice leaking back into the microphone
// (Windows echo cancellation does not reliably remove same-app playback). The
// voice chat used to act on the trip itself: it cut Robo off and cancelled the
// turn in flight, so every noise in the room threw the question away, and Robo
// "hearing itself" ended up answering its own words in a loop.
//
// The conversation now waits for the capture's transcript and asks this module
// whether it is a real interruption. Pure and dependency-free so it is unit
// tested directly.

/** Sounds that carry no request — noise transcribed as a hesitation. */
const FILLER_WORDS = new Set([
  'ah',
  'eh',
  'er',
  'erm',
  'hm',
  'hmm',
  'huh',
  'mhm',
  'mm',
  'mmm',
  'oh',
  'uh',
  'uhm',
  'um',
  'umm'
])

/** Share of the capture's words that must occur in Robo's reply to call it echo. */
const ECHO_WORD_SHARE = 0.7

/** Lowercase words: letters, combining marks and digits in any script;
 *  apostrophes kept inside words ("don't"). */
export function speechWords(text: string): string[] {
  const words = text.toLowerCase().normalize('NFKC').match(/[\p{L}\p{M}\p{N}]+(?:['’][\p{L}\p{M}\p{N}]+)*/gu)

  return (words ?? []).map(word => word.replace(/’/g, "'"))
}

/** True when the transcript is empty or only hesitation sounds ("um", "hmm"). */
export function isFillerOnly(transcript: string): boolean {
  const words = speechWords(transcript)

  return words.length === 0 || words.every(word => FILLER_WORDS.has(word))
}

/**
 * True when the transcript is most likely Robo's own reply picked up by the
 * microphone. Long captures count as echo when most of their words appear in
 * the reply; short ones (one or two words) only when they appear in the reply
 * word for word, so a short real interruption ("wait", "no thanks") is not
 * swallowed just because the reply happened to contain those words somewhere.
 */
export function isLikelyEcho(transcript: string, spokenText: string): boolean {
  const heard = speechWords(transcript)
  const spoken = speechWords(spokenText)

  if (heard.length === 0 || spoken.length === 0) {
    return false
  }

  if (heard.length <= 2) {
    return containsRun(spoken, heard)
  }

  const spokenSet = new Set(spoken)
  const matched = heard.filter(word => spokenSet.has(word)).length

  return matched / heard.length >= ECHO_WORD_SHARE
}

function containsRun(haystack: string[], needle: string[]): boolean {
  for (let start = 0; start + needle.length <= haystack.length; start += 1) {
    if (needle.every((word, offset) => haystack[start + offset] === word)) {
      return true
    }
  }

  return false
}
