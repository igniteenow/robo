/**
 * Team mode's entry points, registered through the same contribution areas a
 * plugin would use: the `/team` page in the workspace pane and a sidebar nav
 * row. (The ⌘K row lives with the other built-in nav rows in the palette so
 * it is localized like them.) The page is lazy — nothing of Team mode loads
 * until the user opens it.
 */

import { lazy } from 'react'

import { registry } from '@/contrib/registry'

import { type RouteContribution, ROUTES_AREA, SIDEBAR_NAV_AREA, type SidebarNavContribution } from '../routes'

export const TEAM_ROUTE = '/team'

const TeamPage = lazy(async () => ({ default: (await import('./page')).TeamPage }))

let registered = false

export function registerTeamContributions(): void {
  if (registered) {
    return
  }

  registered = true

  registry.registerMany([
    {
      id: 'team',
      area: ROUTES_AREA,
      title: 'Team',
      data: { path: TEAM_ROUTE } satisfies RouteContribution,
      render: () => <TeamPage />
    },
    {
      id: 'team',
      area: SIDEBAR_NAV_AREA,
      order: 10,
      // The label is the fallback; the sidebar reads `sidebar.nav.team` first.
      data: { codicon: 'organization', label: 'Team', path: TEAM_ROUTE } satisfies SidebarNavContribution
    }
  ])
}
