// Plain words for what Robo is doing right now.
//
// The live area and the status bar used to show tool calls the way the
// protocol names them — `Terminal("npm test")`, `Read File("src/app.ts")` —
// next to token counts, while the status bar cycled through decorative verbs
// ("analyzing…", "planning…") that had nothing to do with the real step. A
// person following along saw tokens and code-speak, not "Running npm test".
//
// This module phrases every built-in tool the way the classic CLI spinner and
// the desktop app already do ("Running …", "Reading …", "Searching the web for
// …"), in the present tense while the call runs and in the past tense once it
// is done, and picks the one short verb the status bar shows. The stored trail
// lines keep their `Label("preview")` form (lib/text.ts) — this is a
// render-time translation, so transcripts, resume and the parsers are
// untouched. Custom, plugin and MCP tools have no curated verb and keep their
// raw label, exactly as the CLI does.
//
// Honours `display.friendly_tool_labels` (config.yaml, default true), the
// same switch the CLI reads; off, every surface shows the raw labels again.

import { compactPreview, toolTrailLabel } from './text.js'

interface ToolPhrase {
  doing: string
  done: string
  // "Searching the web for X" reads better than "Searching the web X".
  joiner?: ' for '
  // The verb alone — the argument preview adds nothing a person needs.
  noPreview?: true
  // The one-word form for the status bar (≤ 12 characters; see STATUS_VERB_MAX).
  verb: string
}

// Mirrors the built-in verbs of agent/display.py (`_TOOL_VERBS`), with the
// past tense the desktop app uses, so every surface says the same thing.
export const TOOL_PHRASES: Record<string, ToolPhrase> = {
  browser_click: { doing: 'Clicking', done: 'Clicked', verb: 'browsing' },
  browser_navigate: { doing: 'Opening', done: 'Opened', verb: 'browsing' },
  browser_type: { doing: 'Typing', done: 'Typed', verb: 'browsing' },
  clarify: { doing: 'Asking you', done: 'Asked you', noPreview: true, verb: 'asking' },
  cronjob: { doing: 'Scheduling', done: 'Scheduled', verb: 'scheduling' },
  delegate_task: { doing: 'Delegating', done: 'Delegated', verb: 'delegating' },
  execute_code: { doing: 'Running code', done: 'Ran code', noPreview: true, verb: 'running' },
  image_generate: { doing: 'Generating an image', done: 'Generated an image', noPreview: true, verb: 'generating' },
  memory: { doing: 'Updating memory', done: 'Updated memory', noPreview: true, verb: 'remembering' },
  patch: { doing: 'Editing', done: 'Edited', verb: 'editing' },
  read_file: { doing: 'Reading', done: 'Read', verb: 'reading' },
  search_files: { doing: 'Searching files', done: 'Searched files', joiner: ' for ', verb: 'searching' },
  session_search: {
    doing: 'Searching past sessions',
    done: 'Searched past sessions',
    noPreview: true,
    verb: 'searching'
  },
  skill_manage: { doing: 'Updating skill', done: 'Updated skill', verb: 'updating' },
  skill_view: { doing: 'Reading skill', done: 'Read skill', verb: 'reading' },
  skills_list: { doing: 'Listing skills', done: 'Listed skills', noPreview: true, verb: 'listing' },
  terminal: { doing: 'Running', done: 'Ran', verb: 'running' },
  text_to_speech: { doing: 'Generating speech', done: 'Generated speech', noPreview: true, verb: 'speaking' },
  todo: { doing: 'Updating the plan', done: 'Updated the plan', noPreview: true, verb: 'planning' },
  video_generate: { doing: 'Generating a video', done: 'Generated a video', noPreview: true, verb: 'generating' },
  vision_analyze: { doing: 'Looking at the image', done: 'Looked at the image', noPreview: true, verb: 'looking' },
  web_extract: { doing: 'Reading', done: 'Read', verb: 'reading' },
  web_search: { doing: 'Searching the web', done: 'Searched the web', joiner: ' for ', verb: 'searching' },
  write_file: { doing: 'Writing', done: 'Wrote', verb: 'writing' }
}

// Status-bar verbs must fit the fixed verb slot of the busy indicator
// (components/appChrome.tsx pads every verb to the same width).
export const STATUS_VERB_MAX = 12

// The verb the status bar shows while no tool runs.
export const PHASE_VERBS = {
  // The model's reply is streaming in.
  answering: 'writing',
  // Waiting on the model, or reading its reasoning.
  thinking: 'thinking',
  // A tool we have no curated verb for.
  tool: 'working'
} as const

const PREVIEW_MAX = 64

const toolArgPreview = (context: string) => compactPreview(context, PREVIEW_MAX)

/**
 * "Running npm test" / "Ran npm test" for a built-in tool; the raw
 * `Label("preview")` the trail already uses for anything else.
 */
export function describeToolCall(name: string, context = '', done = false, friendly = true): string {
  const phrase = friendly ? TOOL_PHRASES[name] : undefined
  const preview = toolArgPreview(context)

  if (!phrase) {
    const label = toolTrailLabel(name)

    return preview ? `${label}("${preview}")` : label
  }

  const head = done ? phrase.done : phrase.doing

  if (phrase.noPreview || !preview) {
    return head
  }

  return `${head}${phrase.joiner ?? ' '}${preview}`
}

// `Label("preview")` or `Label`, optionally followed by the ` (1.2s)` the
// trail appends — the exact shapes lib/text.ts's formatToolCall /
// buildToolTrailLine produce.
const TRAIL_CALL_RE = /^([A-Z][A-Za-z0-9 ]*?)(?:\("([\s\S]*)"\))?( \(\d+(?:\.\d)?s\))?$/

const toolNameFromLabel = (label: string) => label.trim().toLowerCase().replace(/ /g, '_')

/**
 * Re-phrase a stored trail call (`Terminal("npm test") (1.2s)`) for display:
 * `Ran npm test (1.2s)`. Anything that is not a recognised built-in call is
 * returned unchanged, so plugin/MCP rows and legacy lines never get mangled.
 */
export function friendlyToolCall(call: string, done = true, friendly = true): string {
  if (!friendly) {
    return call
  }

  const match = TRAIL_CALL_RE.exec(call)

  if (!match) {
    return call
  }

  const [, label, preview = '', took = ''] = match
  const name = toolNameFromLabel(label!)

  if (!TOOL_PHRASES[name]) {
    return call
  }

  return `${describeToolCall(name, preview, done, true)}${took}`
}

export interface LiveActivity {
  streaming?: string
  tools?: { name: string }[]
}

/**
 * The one short verb the status bar shows for what Robo is doing right now:
 * the running tool's verb, else "writing" while the answer streams, else
 * "thinking". Always ≤ STATUS_VERB_MAX characters.
 */
export function liveActivityVerb(state: LiveActivity, friendly = true): string {
  const tool = state.tools?.at(-1)

  if (tool) {
    const verb = friendly ? TOOL_PHRASES[tool.name]?.verb : undefined

    return verb ?? PHASE_VERBS.tool
  }

  if (state.streaming) {
    return PHASE_VERBS.answering
  }

  return PHASE_VERBS.thinking
}
