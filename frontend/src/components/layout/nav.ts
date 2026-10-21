/** Navigation model: shared data for the sidebar and top-bar breadcrumbs */

export interface NavItem {
  labelKey: string
  to: string
  icon?: string
  /** Exact match (for entries sharing a prefix with other children, e.g. /workflow) */
  exact?: boolean
}

export interface NavGroup {
  labelKey: string
  icon: string
  adminOnly?: boolean
  items: NavItem[]
}

/** Single-page entries (no children) */
export const navSingles: NavItem[] = [
  { labelKey: 'menu.dashboard', to: '/dashboard', icon: 'dashboard' },
  { labelKey: 'menu.contracts', to: '/contracts', icon: 'file-text' },
  { labelKey: 'menu.review', to: '/review', icon: 'sparkles' },
  { labelKey: 'menu.qa', to: '/knowledge/qa', icon: 'search' },
]

/** Grouped entries: the group name is a small leading label, children are always visible */
export const navGroups: NavGroup[] = [
  {
    labelKey: 'menu.workflow',
    icon: 'check-circle',
    items: [
      { labelKey: 'menu.workflowList', to: '/workflow', exact: true },
      { labelKey: 'menu.workflowDefinitions', to: '/workflow/definitions' },
    ],
  },
  {
    labelKey: 'menu.knowledge',
    icon: 'book-open',
    items: [
      { labelKey: 'menu.laws', to: '/knowledge/laws' },
      { labelKey: 'menu.templates', to: '/knowledge/templates' },
    ],
  },
  {
    labelKey: 'menu.system',
    icon: 'settings',
    adminOnly: true,
    items: [
      { labelKey: 'menu.users', to: '/system/users' },
      { labelKey: 'menu.roles', to: '/system/roles' },
      { labelKey: 'menu.audit', to: '/system/audit-logs' },
      { labelKey: 'menu.models', to: '/system/models' },
      { labelKey: 'menu.agents', to: '/system/agents' },
    ],
  },
]

export function navMatches(item: NavItem, path: string): boolean {
  if (item.exact) return path === item.to
  return path === item.to || path.startsWith(`${item.to}/`)
}

export interface Crumb {
  parentKey?: string
  labelKey: string
}

/** Top-bar breadcrumb: find the most specific entry for the current path */
export function findCrumb(path: string): Crumb | null {
  for (const group of navGroups) {
    for (const item of group.items) {
      if (navMatches(item, path)) return { parentKey: group.labelKey, labelKey: item.labelKey }
    }
  }
  let best: NavItem | null = null
  for (const item of navSingles) {
    if (navMatches(item, path) && (!best || item.to.length > best.to.length)) best = item
  }
  return best ? { labelKey: best.labelKey } : null
}
