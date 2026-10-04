import * as React from 'react'

import { Codicon, type CodiconProps } from '@/components/ui/codicon'
import { cn } from '@/lib/utils'

/**
 * Framed surface for fenced code (and any equivalent: diffs, raw payloads,
 * etc.) sized for the conversation column: a hairline-bordered well in the
 * `--ui-code-block-*` tokens, so a code block never reads like the user's
 * message bubble. `CodeCardHeader` adds the language + actions bar on top.
 */
function CodeCard({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'group/code relative min-w-0 max-w-full overflow-hidden rounded-[0.625rem] border border-(--ui-code-block-border) bg-(--ui-code-block-background) [--expandable-fade-from:var(--ui-code-block-background)] text-[length:var(--conversation-tool-font-size)] text-muted-foreground',
        className
      )}
      data-slot="code-card"
      {...props}
    />
  )
}

/**
 * The bar across the top of a code card: the fence's language on the left,
 * actions (copy) on the right. The label is painted from `data-language` by
 * styles.css, so it stays out of the message's selectable / copied text.
 */
function CodeCardHeader({ className, language, ...props }: React.ComponentProps<'div'> & { language?: null | string }) {
  return (
    <div
      className={cn(
        'flex h-7 items-center justify-between gap-2 border-b border-(--ui-code-block-border) bg-(--ui-code-block-header-background) pr-1 pl-3',
        className
      )}
      data-language={language?.trim() || undefined}
      data-slot="code-card-header"
      {...props}
    />
  )
}

function CodeCardIcon({ className, ...props }: CodiconProps) {
  return (
    <Codicon
      className={cn('shrink-0 text-[0.875rem] leading-none text-muted-foreground', className)}
      data-slot="code-card-icon"
      {...props}
    />
  )
}

function CodeCardBody({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'font-mono text-[0.7rem] leading-relaxed text-foreground/90 [&_pre]:m-0 [&_pre]:overflow-x-auto [&_pre]:scrollbar-overlay [&_pre]:bg-transparent! [&_pre]:px-2 [&_pre]:py-1.5 [&_pre]:font-mono [&_pre]:leading-relaxed',
        className
      )}
      data-slot="code-card-body"
      {...props}
    />
  )
}

export { CodeCard, CodeCardBody, CodeCardHeader, CodeCardIcon }
