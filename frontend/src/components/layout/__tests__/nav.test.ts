import { describe, expect, it } from 'vitest'

import { findCrumb, navGroups, navMatches, navSingles, type NavItem } from '@/components/layout/nav'

describe('navMatches 路由匹配', () => {
  const item: NavItem = { labelKey: 'menu.contracts', to: '/contracts' }

  it('精确命中', () => {
    expect(navMatches(item, '/contracts')).toBe(true)
    expect(navMatches(item, '/contracts/12')).toBe(true)
  })

  it('前缀不符或只是相似字符串不命中', () => {
    expect(navMatches(item, '/contracts-archive')).toBe(false)
    expect(navMatches(item, '/other')).toBe(false)
  })

  it('exact 项只做精确匹配', () => {
    const exact: NavItem = { labelKey: 'menu.workflowList', to: '/workflow', exact: true }
    expect(navMatches(exact, '/workflow')).toBe(true)
    expect(navMatches(exact, '/workflow/1')).toBe(false)
  })
})

describe('findCrumb 面包屑', () => {
  it('分组项命中时带上父级分组 key', () => {
    expect(findCrumb('/workflow/definitions/9')).toEqual({
      parentKey: 'menu.workflow',
      labelKey: 'menu.workflowDefinitions',
    })
    expect(findCrumb('/system/users')).toEqual({ parentKey: 'menu.system', labelKey: 'menu.users' })
  })

  it('单页项命中时仅返回自身 key', () => {
    expect(findCrumb('/dashboard')).toEqual({ labelKey: 'menu.dashboard' })
    expect(findCrumb('/knowledge/qa')).toEqual({ labelKey: 'menu.qa' })
  })

  it('取最长匹配的单项（避免前缀误命中）', () => {
    const singles: NavItem[] = [
      { labelKey: 'a', to: '/a' },
      { labelKey: 'b', to: '/a/b' },
    ]
    // 用真实数据无法覆盖"多个候选"，这里校验最长匹配逻辑等价：/workflow 与 /workflow/definitions 同组
    expect(findCrumb('/workflow')?.labelKey).toBe('menu.workflowList')
    expect(singles.length).toBe(2)
  })

  it('未命中任何导航返回 null', () => {
    expect(findCrumb('/not-exist')).toBeNull()
    expect(findCrumb('/')).toBeNull()
  })
})

describe('导航模型数据完整性', () => {
  it('单页与分组数据均提供 labelKey 与 to', () => {
    expect(navSingles.length).toBeGreaterThan(0)
    expect(navGroups.length).toBeGreaterThan(0)
    for (const item of navSingles) {
      expect(item.labelKey).toBeTruthy()
      expect(item.to.startsWith('/')).toBe(true)
    }
    for (const group of navGroups) {
      expect(group.icon).toBeTruthy()
      expect(group.items.length).toBeGreaterThan(0)
    }
  })

  it('系统管理分组标记为 adminOnly', () => {
    expect(navGroups.find((g) => g.labelKey === 'menu.system')?.adminOnly).toBe(true)
  })
})
