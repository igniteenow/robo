/**
 * `/attach <path>` — put a file into Robo's knowledge base, then ask about it.
 * Copyright (c) 2026 Ignitee Now.
 *
 * Any size, any of: text, code, Markdown, CSV, JSON, HTML, PDF, Word, Excel,
 * PowerPoint. The file is indexed by the gateway (local SQLite full-text
 * search, nothing uploaded anywhere), so the same document is available to the
 * TUI, the dashboard chat and the desktop app. `/attach` alone lists what is
 * already indexed. Dragging a file onto the terminal pastes its path, so
 * `/attach ` followed by a drag is the whole gesture.
 */
import type { SlashCommand, SlashRunCtx } from '../types.js'

interface IndexedDoc {
  added_at?: string
  chunks?: number
  kind?: string
  size?: string
  source?: string
  title?: string
}

interface KnowledgeAddResponse {
  indexed?: IndexedDoc
  path?: string
}

interface KnowledgeListResponse {
  documents?: IndexedDoc[]
  stats?: { bytes?: number; chunks?: number; documents?: number; path?: string }
}

const unquote = (raw: string): string => {
  const text = raw.trim()
  const quoted = /^(['"])(.*)\1$/.exec(text)
  return (quoted ? quoted[2] : text).replace(/\\ /g, ' ')
}

const runAdd = (path: string, ctx: SlashRunCtx): void => {
  ctx.transcript.sys(`attach: indexing ${path} …`)
  ctx.gateway
    .rpc<KnowledgeAddResponse>('knowledge.add', { path })
    .then(
      ctx.guarded<KnowledgeAddResponse>(r => {
        const doc = r.indexed
        if (!doc) {
          return ctx.transcript.sys('attach: nothing was indexed')
        }
        const parts = doc.chunks === 1 ? '1 part' : `${doc.chunks ?? 0} parts`
        ctx.transcript.sys(
          `attach: indexed ${doc.title ?? path} · ${doc.size ?? ''} · ${parts}. Ask about it; Robo will quote the passages it uses.`
        )
      })
    )
    .catch(ctx.guardedErr)
}

const runList = (ctx: SlashRunCtx): void => {
  ctx.gateway
    .rpc<KnowledgeListResponse>('knowledge.list', {})
    .then(
      ctx.guarded<KnowledgeListResponse>(r => {
        const docs = r.documents ?? []
        if (docs.length === 0) {
          return ctx.transcript.sys('knowledge base: empty. Usage: /attach <file> (drag a file onto the terminal to paste its path)')
        }
        const lines = docs.slice(0, 20).map(d => `  ${d.title ?? d.source ?? '?'} · ${d.size ?? ''} · ${d.chunks ?? 0} parts · ${d.added_at ?? ''}`)
        const more = docs.length > 20 ? `\n  … and ${docs.length - 20} more` : ''
        ctx.transcript.sys(`knowledge base: ${docs.length} document${docs.length === 1 ? '' : 's'}\n${lines.join('\n')}${more}`)
      })
    )
    .catch(ctx.guardedErr)
}

export const attachCommands: SlashCommand[] = [
  {
    aliases: ['upload', 'index', 'knowledge'],
    help: 'Add a file of any size to the knowledge base so you can ask about it; no argument lists what is indexed',
    name: 'attach',
    run: (arg, ctx) => {
      const path = unquote(arg)
      if (!path) {
        return runList(ctx)
      }
      runAdd(path, ctx)
    },
    usage: '/attach <path>'
  }
]
