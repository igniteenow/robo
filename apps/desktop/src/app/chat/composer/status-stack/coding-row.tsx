import { useStore } from '@nanostores/react'
import { memo, useEffect } from 'react'

import { StatusRow } from '@/components/chat/status-row'
import {
  type ActionItemSpec,
  ActionsContextMenu,
  ActionsMenu,
  type MenuKit,
  renderActionItem
} from '@/components/ui/actions-menu'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { CopyButton } from '@/components/ui/copy-button'
import type { RoboGitBranch } from '@/global'
import { useI18n } from '@/i18n'
import { displayPath } from '@/lib/display-path'
import { openWorktreeDialog, registerRepoStatusCwd, repoStatusForCwd, repoWorktreesForCwd } from '@/store/coding-status'
import { notifyError } from '@/store/notifications'

// Tiny uppercase section header, matching the composer "+" menu's labels.
const MENU_SECTION = 'text-[0.625rem] font-semibold uppercase tracking-wider text-(--ui-text-tertiary)'

interface CodingStatusRowProps {
  /** Branch the current draft off into a fresh worktree + session, based on
   *  `base` (a branch name; omitted = current HEAD). The composer owns the
   *  draft, so it supplies the orchestration; the row just collects the new
   *  branch name + base. Omitted (e.g. remote backend) hides the affordance. */
  onBranchOff?: (branch: string, base?: string) => Promise<void>
  /** Check an existing branch out into a fresh worktree + session (no new
   *  branch). Drives the dialog's "convert a branch" picker. */
  onConvertBranch?: (branch: string, path?: null | string, isDefault?: boolean) => Promise<void>
  /** List the repo's local branches for the "convert a branch" picker. */
  onListBranches?: () => Promise<RoboGitBranch[]>
  /** Open the review pane (changed files + diffs). */
  onOpen?: () => void
  /** Jump into an existing worktree (open a fresh session anchored there). */
  onOpenWorktree?: (path: string) => void
  /** Switch the current repo checkout to another branch. */
  onSwitchBranch?: (branch: string) => Promise<void>
  /** Repo root path for the worktree dialog. */
  repoPath?: null | string
}

/**
 * The always-on coding-context row in the tray UNDER the composer, on the
 * left (where a chat app keeps its project chip): current branch and
 * ahead/behind. It is the entry point to the review pane. Hidden when the
 * active session isn't in a local git repo (the probe returns null).
 */
export const CodingStatusRow = memo(function CodingStatusRow({
  onBranchOff,
  onConvertBranch,
  onListBranches,
  onOpen,
  onOpenWorktree,
  onSwitchBranch,
  repoPath
}: CodingStatusRowProps) {
  const { t } = useI18n()
  const s = t.statusStack.coding
  const p = t.sidebar.projects
  const fileMenu = t.fileMenu
  const resolvedRepoPath = repoPath?.trim() || undefined
  // This surface's OWN worktree, always — never the primary's. The row used to
  // fall back to the global `$repoStatus` for a blank repoPath, which painted
  // the main pane's branch/± onto a tile whose cwd hadn't resolved yet. That
  // fallback bought nothing (the primary's computed is keyed to `$currentCwd`,
  // which is blank in exactly the same case) and cost a wrong-tree rail.
  const status = useStore(repoStatusForCwd(resolvedRepoPath))
  const worktrees = useStore(repoWorktreesForCwd(resolvedRepoPath))

  // While mounted, keep this worktree in the coding-status refresh set so the
  // turn-settle / tool-complete / focus edges re-probe it too (tiles otherwise
  // only refreshed when the MAIN cwd probe happened to cover them).
  useEffect(() => registerRepoStatusCwd(resolvedRepoPath), [resolvedRepoPath])

  const switchToBranch = async (branch: string) => {
    if (!onSwitchBranch) {
      return
    }

    try {
      await onSwitchBranch(branch)
    } catch (err) {
      notifyError(err, s.switchFailed(branch))
    }
  }

  // useKeybinds now handles the ⌘⇧B hotkey globally, through
  // openWorktreeDialog. One dialog is mounted in the sidebar, so N mounted
  // rails can no longer each open their own copy. The menu items below only
  // publish the intent. They pin the repo of THIS rail, so the kebab of a tile
  // targets the worktree of that tile.
  const startBranch = (base: string | undefined) => {
    void openWorktreeDialog({ base, repoPath: resolvedRepoPath })
  }

  if (!status) {
    return null
  }

  const branchLabel = status.detached ? s.detached : status.branch || s.noBranch
  // The kebab offers branching off the trunk and/or the current branch. The
  // worktree-add bases the new branch on `base` (a branch name; undefined =
  // current HEAD). We dedupe so "on main" shows a single trunk entry, and fall
  // back to a plain off-HEAD branch when no trunk is detected.
  const current = status.detached ? null : status.branch
  const branchTargets: { base: string | undefined; label: string }[] = []

  // Current branch first (the 99% "branch off where I am"), then the trunk just
  // below it ("New branch from main"), deduped when they're the same.
  if (current) {
    branchTargets.push({ base: current, label: s.branchOffFrom(current) })
  }

  if (status.defaultBranch && status.defaultBranch !== current) {
    branchTargets.push({ base: status.defaultBranch, label: s.branchOffFrom(status.defaultBranch) })
  }

  if (branchTargets.length === 0) {
    branchTargets.push({ base: undefined, label: s.newBranch })
  }

  const switchTarget =
    onSwitchBranch && current && status.defaultBranch && status.defaultBranch !== current ? status.defaultBranch : null

  // Other worktrees to jump into — everything except the one we're already in
  // (matched by its checked-out branch) and the bare/main placeholder entry.
  const otherWorktrees = onOpenWorktree
    ? worktrees.filter(w => w.path && !w.detached && w.branch && w.branch !== current)
    : []

  // The branch actions, rendered identically by the kebab dropdown and the
  // row's right-click menu so the two never drift. `onBranchOff` gates the
  // whole menu (omitted = remote backend), matching the kebab.
  const renderBranchItems = (kit: MenuKit) => {
    const branchItems: ActionItemSpec[] = branchTargets.map(target => ({
      key: target.base ?? '__head__',
      label: <span className="truncate">{target.label}</span>,
      onSelect: () => startBranch(target.base)
    }))

    const worktreeItems: ActionItemSpec[] = otherWorktrees.map(worktree => ({
      key: worktree.path,
      label: <span className="truncate">{worktree.branch}</span>,
      onSelect: () => onOpenWorktree?.(worktree.path)
    }))

    return (
      <>
        <kit.Label className={MENU_SECTION}>{s.newBranch}</kit.Label>
        {branchItems.map(item => renderActionItem(kit, item))}
        {switchTarget &&
          renderActionItem(kit, {
            key: '__switch__',
            label: <span className="truncate">{s.switchTo(switchTarget)}</span>,
            onSelect: () => void switchToBranch(switchTarget)
          })}
        <kit.Separator />
        <kit.Label className={MENU_SECTION}>{s.worktrees}</kit.Label>
        {worktreeItems.map(item => renderActionItem(kit, item))}
        {/* Create a fresh worktree off the current HEAD (the generic "spin up a
            worktree here", mirroring the sidebar's + button). */}
        {renderActionItem(kit, {
          key: '__start__',
          label: <span className="truncate">{p.startWork}</span>,
          onSelect: () => startBranch(undefined)
        })}
        {onConvertBranch &&
          renderActionItem(kit, {
            key: '__convert__',
            label: <span className="truncate">{p.convertBranch}</span>,
            onSelect: () => startBranch(undefined)
          })}
      </>
    )
  }

  return (
    <>
      <ActionsContextMenu contentClassName="w-60" disabled={!onBranchOff} items={renderBranchItems}>
        <StatusRow
          // "Where am I working", quietly under the box: no chrome of its own,
          // lined up with the composer's text.
          className="coding-status-bar min-h-7 w-full px-2 py-1 hover:bg-transparent"
          // Static branch glyph — never the loading spinner. This row only renders
          // once `status` exists, so a spinner here only ever fired on *refreshes*
          // of an already-loaded repo (window focus, turn settle), reading as an
          // annoying icon "blip" with no first-load value. Refreshes are silent.
          // It's a button (not the whole row) so the glyph opens the review pane
          // while the strip around it stays inert; size-3.5 fills the slot exactly.
          leading={
            <button className="flex size-3.5 items-center justify-center" onClick={onOpen} type="button">
              <Codicon className="text-(--ui-green)" name="git-branch" size="0.8rem" />
            </button>
          }
        >
          <div className="flex min-w-0 flex-1 items-center gap-1">
            {/* Branch name — the other half of the review-pane target. `contents`
                so the button lays out nothing of its own: the label stays the
                same flex child it always was, and the hit area is the text. */}
            <button className="contents" onClick={onOpen} type="button">
              <span className="min-w-0 truncate text-xs font-normal text-muted-foreground/92" title={branchLabel}>
                {branchLabel}
              </span>
            </button>

            {/* Worktree path + copy — plain muted text, not a chip. Always in the
                flex so hover doesn't reflow the row; opacity alone reveals the
                pair. The path sizes to its content (the `flex-1` lives on the
                wrapper) so the glyph sits against the end of the text instead of
                drifting to the far edge of the row. `displayPath` collapses
                home → ~; the copy still takes the real absolute path, and it's
                the shared `CopyButton` so it confirms with the same inline
                checkmark as every other copy in the app. */}
            {resolvedRepoPath && (
              <div className="flex min-w-0 flex-1 items-center gap-0.5 opacity-0 transition-opacity group-hover/status-row:opacity-100 group-focus-within/status-row:opacity-100">
                <span
                  className="min-w-0 truncate font-mono text-[0.62rem] leading-4 text-muted-foreground/50"
                  data-slot="coding-status-cwd"
                >
                  {displayPath(resolvedRepoPath)}
                </span>
                <CopyButton
                  appearance="icon"
                  buttonSize="icon-xs"
                  className="pointer-events-none size-4 shrink-0 text-muted-foreground/50 hover:text-foreground group-hover/status-row:pointer-events-auto group-focus-within/status-row:pointer-events-auto"
                  iconClassName="size-3"
                  label={fileMenu.copyPath}
                  side="top"
                  stopPropagation
                  text={resolvedRepoPath}
                />
              </div>
            )}

            {/* Branch actions kebab — same pattern as the session/worktree rows.
                ALWAYS laid out; only its opacity flips on hover/focus/open, so
                revealing it never reflows the row (no layout shift). pointer-events
                follow opacity so the invisible trigger isn't clickable at rest. */}
            {onBranchOff && (
              <ActionsMenu
                align="end"
                contentClassName="w-60"
                // The row sits under the composer, low on the screen, so the
                // menu opens upward.
                items={renderBranchItems}
                side="top"
              >
                <Button
                  aria-label={s.newBranch}
                  className="pointer-events-none size-4 shrink-0 text-muted-foreground/60 opacity-0 transition hover:text-foreground group-hover/status-row:pointer-events-auto group-hover/status-row:opacity-100 group-focus-within/status-row:pointer-events-auto group-focus-within/status-row:opacity-100 data-[state=open]:pointer-events-auto data-[state=open]:opacity-100"
                  size="icon-xs"
                  variant="ghost"
                >
                  <Codicon name="kebab-vertical" size="0.8rem" />
                </Button>
              </ActionsMenu>
            )}
          </div>

          {/* Ahead/behind vs the upstream, when there is something to say. The
              working-tree line counts (+n −m) used to sit here too; they are
              gone — a lockfile churn read as "+17678 −17678" next to the
              prompt, which is noise, not status. The review pane (click the
              branch) has the real diff. `contents` keeps the span a direct
              flex child of the row. */}
          {(status.ahead > 0 || status.behind > 0) && (
            <button className="contents" onClick={onOpen} type="button">
              <span className="ml-auto flex shrink-0 items-center gap-1.5 text-[0.68rem] leading-4 text-muted-foreground/75 tabular-nums">
                {status.ahead > 0 && (
                  <span className="flex items-center gap-0.5" title={s.ahead(status.ahead)}>
                    <span aria-hidden>↑</span>
                    {status.ahead}
                  </span>
                )}
                {status.behind > 0 && (
                  <span className="flex items-center gap-0.5" title={s.behind(status.behind)}>
                    <span aria-hidden>↓</span>
                    {status.behind}
                  </span>
                )}
              </span>
            </button>
          )}
        </StatusRow>
      </ActionsContextMenu>
    </>
  )
})
