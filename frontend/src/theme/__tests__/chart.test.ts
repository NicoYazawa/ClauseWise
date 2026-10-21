import { afterEach, describe, expect, it, vi } from 'vitest'

import { chartBase, chartTokens } from '@/theme/chart'

describe('chartTokens 读取 CSS 变量', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('变量有值时包装为 rgb()', () => {
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({
      getPropertyValue: (name: string) => (name === '--c-accent' ? '15 118 110' : ''),
    } as unknown as CSSStyleDeclaration)

    const t = chartTokens()
    expect(t.accent).toBe('rgb(15 118 110)')
    // 未定义的变量回退到默认色
    expect(t.neutral).toBe('#6b7280')
    expect(t.pale).toBe('#8fd0c6')
  })

  it('固定语义色不受 CSS 变量影响', () => {
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({
      getPropertyValue: () => '',
    } as unknown as CSSStyleDeclaration)

    const t = chartTokens()
    expect(t.negative).toBe('#c4242a')
    expect(t.warning).toBe('#b45309')
    expect(t.positive).toBe('#247b50')
    expect(t.surface).toBe('#ffffff')
    expect(t.accent).toBe('#0f766e')
  })
})

describe('chartBase 图表基础配置', () => {
  it('透传坐标轴配色并固定网格/提示框配置', () => {
    const t = chartTokens()
    const base = chartBase(t)
    expect(base.textStyle.color).toBe(t.axis)
    expect(base.grid).toMatchObject({ left: 44, right: 16, top: 20, bottom: 28 })
    expect(base.tooltip.trigger).toBe('axis')
    expect(base.tooltip.backgroundColor).toBe(t.surface)
    expect(base.tooltip.textStyle.color).toBe(t.text)
  })
})
