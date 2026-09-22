/**
 * The TUI welcome screen. Copyright (c) 2026 Ignitee Now.
 *
 * What a person sees the moment `robo` opens:
 *
 *   ██████╗  ██████╗ ██████╗  ██████╗     ← the ROBO wordmark, in the flame,
 *   ██╔══██╗██╔═══██╗██╔══██╗██╔═══██╗       top row ember, bottom row red
 *   …
 *   autonomous engineering agent  ◆  by Ignitee Now
 *
 *   ◆ model      deepseek-v4-pro          ◆ session    b5ef55c9
 *     provider   deepseek                   loaded     33 tools · 66 skills
 *     thinking   high                       profile    default
 *     workspace  ~/projects/checkout
 *   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 *   › Describe a task · say Hey Roh Boh after /wake on · /help
 *
 *   ▸ Tools   ▸ Skills 66   ▸ MCP 1   ▸ System prompt
 *
 * Ember (`t.color.accent`) marks the things you act on: the diamonds, the prompt
 * glyph, the rule under the facts. Indigo (`t.color.label`) is structure. Body
 * text keeps the terminal's colour. When a skin renames the agent, the wordmark
 * gives way to that name so the skin's choice is respected.
 */
import { Box, Text, useStdout } from '@robo/ink'
import { useEffect, useState } from 'react'
import unicodeSpinners from 'unicode-animations'

import { CLI_NAME, WAKE_PHRASE } from '../brand.js'
import { mix } from '../lib/color.js'
import { flat } from '../lib/text.js'
import type { Theme } from '../theme.js'
import type { PanelSection, SessionInfo } from '../types.js'

import { Accordion } from './accordion.js'
import { ShimmerRows } from './loaders.js'

const LOADER_TICK_MS = 120
const MARK = '\u25c6'
const STEP = '\u25b8'
const PROMPT = '\u203a'
const RULE = '\u2500'
const RULE_HEAVY = '\u2501'

/** The ROBO wordmark. Same letterforms as the CLI banner, so the product looks
 *  identical whichever interface opens it. 34 columns wide. */
export const WORDMARK: readonly string[] = [
  '\u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2557 ',
  '\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2588\u2588\u2557',
  '\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2551   \u2588\u2588\u2551',
  '\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551',
  '\u2588\u2588\u2551  \u2588\u2588\u2551\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d',
  '\u255a\u2550\u255d  \u255a\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d  \u255a\u2550\u2550\u2550\u2550\u2550\u255d '
]

/** The Ignitee Now flame, one shade per wordmark row, ember at the top burning
 *  down to red. Brand constants from assets/brand/BRAND.md. */
export const FLAME: readonly string[] = ['#F5A13A', '#EF8A22', '#E8742A', '#DF5A30', '#D93F32', '#D52734']

const WORDMARK_WIDTH = 34
const HIDE_BELOW = 24
const TAGLINE = 'autonomous engineering agent'
const BYLINE = 'by Ignitee Now'

function InlineLoader({ label, t }: { label: string; t: Theme }) {
  const [tick, setTick] = useState(0)
  const spinner = unicodeSpinners.braille
  const frame = spinner.frames[tick % spinner.frames.length] ?? '\u280b'

  useEffect(() => {
    const id = setInterval(() => setTick(n => n + 1), Math.max(LOADER_TICK_MS, spinner.interval))

    return () => clearInterval(id)
  }, [spinner.interval])

  return (
    <Text color={t.color.muted} wrap="truncate">
      <Text color={t.color.accent}>{frame}</Text> {label}
    </Text>
  )
}

/** The brand name shaded letter by letter from red to ember. */
export function FlameWord({ bold = true, word }: { bold?: boolean; word: string }) {
  const letters = Array.from(word)
  const span = Math.max(1, letters.length - 1)

  return (
    <Text bold={bold}>
      {letters.map((letter, index) => (
        <Text color={FLAME[Math.round(((FLAME.length - 1) * (span - index)) / span)] ?? FLAME[0]} key={index}>
          {letter}
        </Text>
      ))}
    </Text>
  )
}

/** The hero: the wordmark in the flame, or the skin's own agent name. */
export function Banner({ maxWidth, t }: { maxWidth?: number; t: Theme }) {
  const term = useStdout().stdout?.columns ?? 80
  const cols = Math.max(1, Math.min(term, maxWidth ?? term))

  if (cols < HIDE_BELOW) {
    return null
  }

  const isRobo = t.brand.name.trim().toLowerCase() === 'robo'
  const tagline = (
    <Text wrap="truncate-end">
      <Text color={t.color.muted}>{TAGLINE}</Text>
      <Text color={t.color.accent}>{`  ${MARK}  `}</Text>
      <Text color={t.color.label}>{BYLINE}</Text>
    </Text>
  )

  if (!isRobo || cols < WORDMARK_WIDTH + 4) {
    return (
      <Box flexDirection="column" marginBottom={1}>
        <Text wrap="truncate-end">
          <Text bold color={t.color.accent}>{`${MARK} `}</Text>
          {isRobo ? <FlameWord word="ROBO" /> : <Text bold color={t.color.accent}>{t.brand.name}</Text>}
        </Text>
        {tagline}
      </Box>
    )
  }

  return (
    <Box flexDirection="column" marginBottom={1}>
      {WORDMARK.map((row, index) => (
        <Text bold color={FLAME[index] ?? FLAME[FLAME.length - 1]} key={index}>
          {row}
        </Text>
      ))}
      {tagline}
    </Box>
  )
}

// ── Skeleton ─────────────────────────────────────────────────────────────────
// Lazy sections render shimmer rows shaped like the real content instead of a
// blank gap that pops when data lands. Row widths mirror a typical listing.
const SKELETON_ROWS: readonly (readonly [number, number])[] = [
  [7, 30],
  [7, 9],
  [14, 12],
  [12, 12],
  [7, 7],
  [10, 13]
]

const SKILLS_MAX = 8
const TOOLSETS_MAX = 8

function homeShort(path: string): string {
  const home = process.env.HOME || process.env.USERPROFILE

  return home && path.startsWith(home) ? `~${path.slice(home.length)}` : path
}

export function SessionPanel({ info, maxWidth, sid, t }: SessionPanelProps) {
  const term = useStdout().stdout?.columns ?? 100
  const cols = Math.max(20, Math.min(term, maxWidth ?? term))
  const w = Math.max(20, cols - 4)
  const lineBudget = Math.max(12, w - 2)
  const strip = (s: string) => (s.endsWith('_tools') ? s.slice(0, -6) : s)
  const listFade = mix(t.color.muted, t.color.text, 0.5)

  const [toolsOpen, setToolsOpen] = useState(false)
  const [skillsOpen, setSkillsOpen] = useState(false)
  const [systemOpen, setSystemOpen] = useState(false)
  const [mcpOpen, setMcpOpen] = useState(false)

  const truncLine = (pfx: string, items: string[]) => {
    let line = ''
    let shown = 0

    for (const item of [...items].sort()) {
      const next = line ? `${line}, ${item}` : item

      if (pfx.length + next.length > lineBudget) {
        return line ? `${line}, \u2026+${items.length - shown}` : `${item}, \u2026`
      }

      line = next
      shown++
    }

    return line
  }

  // ── Inventories ──
  const skillEntries = Object.entries(info.skills).sort()
  const skillsTotal = flat(info.skills).length
  const skillsCatCount = skillEntries.length
  const toolEntries = Object.entries(info.tools).sort()
  const toolsTotal = flat(info.tools).length
  // MCP headline counts *connected* servers, matching the classic CLI banner.
  const mcpServers = info.mcp_servers ?? []
  const mcpConnected = mcpServers.filter(s => s.connected).length
  const sysPromptLen = (info.system_prompt ?? '').length

  const listing = (entries: [string, string[]][], max: number, noun: string) => {
    const shown = entries.slice(0, max)
    const overflow = entries.length - max

    return (
      <>
        {shown.map(([k, vs]) => (
          <Text key={k} wrap="truncate">
            <Text color={t.color.label}>{strip(k)}: </Text>
            <Text color={listFade}>{truncLine(strip(k) + ': ', vs)}</Text>
          </Text>
        ))}
        {overflow > 0 && <Text color={t.color.muted}>{`(and ${overflow} more ${noun}\u2026)`}</Text>}
      </>
    )
  }

  const toolsBody = () =>
    info.lazy && toolEntries.length === 0 ? (
      <ShimmerRows color={listFade} highlight={t.color.label} rows={SKELETON_ROWS} />
    ) : (
      listing(toolEntries, TOOLSETS_MAX, 'toolsets')
    )

  const skillsBody = () =>
    info.lazy && skillEntries.length === 0 ? (
      <InlineLoader label="scanning skills" t={t} />
    ) : (
      listing(skillEntries, SKILLS_MAX, 'categories')
    )

  const mcpBody = () => (
    <>
      {mcpServers.map(s => (
        <Text key={s.name} wrap="truncate">
          <Text color={t.color.label}>{`  ${s.name} `}</Text>
          <Text color={t.color.muted}>{`${s.transport} \u00b7 `}</Text>
          {s.connected ? (
            <Text color={t.color.ok}>{`connected \u00b7 ${s.tools} tool${s.tools === 1 ? '' : 's'}`}</Text>
          ) : s.disabled || s.status === 'disabled' ? (
            <Text color={t.color.muted}>disabled</Text>
          ) : s.status === 'connecting' ? (
            <Text color={t.color.warn}>connecting</Text>
          ) : s.status === 'configured' ? (
            <Text color={t.color.muted}>configured</Text>
          ) : (
            <Text color={t.color.error}>failed</Text>
          )}
        </Text>
      ))}
    </>
  )

  const systemBody = () =>
    sysPromptLen === 0 ? (
      <Text color={t.color.muted}>No system prompt loaded.</Text>
    ) : (
      <Text color={t.color.muted}>{info.system_prompt}</Text>
    )

  // ── Facts grid ──
  const contextMax = (info as { context_max?: number }).context_max
  const provider = info.model.includes('/') ? info.model.split('/')[0] : ''
  const modelShort = info.model.split('/').pop() ?? info.model
  const ruleWidth = Math.max(8, Math.min(w, 100) - 2)
  const half = Math.max(24, Math.floor((Math.min(w, 100) - 4) / 2))
  const inventory =
    (info.lazy && !toolsTotal ? '\u2026' : `${toolsTotal}`) +
    ' tools \u00b7 ' +
    (info.lazy && !skillsTotal ? '\u2026' : `${skillsTotal}`) +
    ' skills' +
    (mcpConnected ? ` \u00b7 ${mcpConnected} MCP` : '')
  const thinking = contextMax
    ? `${contextMax.toLocaleString()} tokens`
    : info.reasoning_effort
      ? `${info.reasoning_effort}`
      : '\u2014'

  const cell = (label: string, value: string, width: number, lead = ' ') => (
    <Text wrap="truncate-end">
      <Text bold color={t.color.accent}>
        {lead}
      </Text>
      <Text color={t.color.label}>{` ${label.padEnd(10)}`}</Text>
      <Text color={t.color.text}>{value.slice(0, Math.max(4, width - 12))}</Text>
    </Text>
  )

  const infoColumn = (
    <Box flexDirection="column" width="100%">
      <Box flexDirection="row" gap={2}>
        <Box flexDirection="column" width={half}>
          {cell('model', modelShort, half, MARK)}
          {cell('provider', provider || info.service_tier || '\u2014', half)}
          {cell(contextMax ? 'context' : 'thinking', thinking, half)}
          {cell('workspace', info.cwd ? homeShort(info.cwd) : '\u2014', half)}
        </Box>
        <Box flexDirection="column" width={half}>
          {cell('session', sid ? sid.slice(0, 12) : 'new', half, MARK)}
          {cell('loaded', inventory, half)}
          {cell('profile', info.profile_name || 'default', half)}
          {cell('version', info.version ? `${info.version}` : '\u2014', half)}
        </Box>
      </Box>
      <Text color={t.color.accent}>{RULE_HEAVY.repeat(ruleWidth)}</Text>
      <Text wrap="truncate-end">
        <Text bold color={t.color.accent}>{`${PROMPT} `}</Text>
        <Text color={t.color.muted}>
          {`Describe a task \u00b7 /attach <file> to give Robo a document \u00b7 say ${WAKE_PHRASE} after /wake on \u00b7 /help`}
        </Text>
      </Text>

      <Box flexDirection="column" marginTop={1}>
        <Accordion onToggle={() => setToolsOpen(v => !v)} open={toolsOpen} t={t} title="Tools">
          {toolsBody()}
        </Accordion>
      </Box>

      <Box flexDirection="column" marginTop={1}>
        <Accordion
          count={skillsTotal}
          onToggle={() => setSkillsOpen(v => !v)}
          open={skillsOpen}
          suffix={skillsCatCount > 0 ? `in ${skillsCatCount} categor${skillsCatCount === 1 ? 'y' : 'ies'}` : undefined}
          t={t}
          title="Skills"
        >
          {skillsBody()}
        </Accordion>
      </Box>

      {sysPromptLen > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Accordion
            onToggle={() => setSystemOpen(v => !v)}
            open={systemOpen}
            suffix={`\u2014 ${sysPromptLen.toLocaleString()} chars`}
            t={t}
            title="System Prompt"
          >
            {systemBody()}
          </Accordion>
        </Box>
      )}

      {mcpServers.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Accordion
            count={mcpConnected}
            onToggle={() => setMcpOpen(v => !v)}
            open={mcpOpen}
            suffix="connected"
            t={t}
            title="MCP Servers"
          >
            {mcpBody()}
          </Accordion>
        </Box>
      )}

      <Text />

      {typeof info.update_behind === 'number' && info.update_behind > 0 && (
        <Text wrap="truncate-end">
          <Text bold color={t.color.warn}>
            {`\u2191 ${info.update_behind} ${info.update_behind === 1 ? 'update' : 'updates'} behind`}
          </Text>
          <Text color={t.color.muted}>{' \u2014 run '}</Text>
          <Text bold color={t.color.text}>
            {info.update_command || `${CLI_NAME} update`}
          </Text>
        </Text>
      )}

      {info.install_warning && (
        <Text bold color={t.color.warn} wrap="wrap">
          ! {info.install_warning}
        </Text>
      )}
    </Box>
  )

  return (
    <Box flexDirection="column" marginBottom={1} paddingX={1}>
      {infoColumn}
    </Box>
  )
}

export function Panel({ sections, t, title }: PanelProps) {
  return (
    <Box borderColor={t.color.border} borderStyle="round" flexDirection="column" paddingX={2} paddingY={1}>
      <Box marginBottom={1}>
        <Text bold color={t.color.accent}>{`${MARK} `}</Text>
        <Text bold color={t.color.text}>
          {title}
        </Text>
      </Box>

      {sections.map((sec, si) => (
        <Box flexDirection="column" key={si} marginTop={si > 0 ? 1 : 0}>
          {sec.title && (
            <Text wrap="truncate">
              <Text bold color={t.color.accent}>{`${STEP} `}</Text>
              <Text bold color={t.color.text}>
                {sec.title}
              </Text>
            </Text>
          )}

          {sec.rows?.map(([k, v], ri) => (
            <Text key={ri} wrap="truncate">
              <Text color={t.color.label}>{k.padEnd(20)}</Text>
              <Text color={t.color.text}>{v}</Text>
            </Text>
          ))}

          {sec.items?.map((item, ii) => (
            <Text color={t.color.text} key={ii} wrap="truncate">
              {`${RULE} ${item}`}
            </Text>
          ))}

          {sec.text && <Text color={t.color.muted}>{sec.text}</Text>}
        </Box>
      ))}
    </Box>
  )
}

interface PanelProps {
  sections: PanelSection[]
  t: Theme
  title: string
}

interface SessionPanelProps {
  info: SessionInfo
  maxWidth?: number
  sid?: string | null
  t: Theme
}
