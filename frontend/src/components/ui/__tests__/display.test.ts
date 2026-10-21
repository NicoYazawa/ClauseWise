import { describe, expect, it } from 'vitest'

import PageHeader from '@/components/ui/PageHeader.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import RiskBadge from '@/components/ui/RiskBadge.vue'
import ScoreRing from '@/components/ui/ScoreRing.vue'
import SourceBadge from '@/components/ui/SourceBadge.vue'
import StatCard from '@/components/ui/StatCard.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import { mountWithApp } from '@test/helpers'

describe('PageHeader', () => {
  it('仅标题时无面包屑与描述', async () => {
    const { wrapper } = await mountWithApp(PageHeader, { props: { title: '合同列表' } })
    expect(wrapper.find('h1').text()).toBe('合同列表')
    expect(wrapper.find('nav').exists()).toBe(false)
    expect(wrapper.find('p').exists()).toBe(false)
  })

  it('面包屑插槽 + 描述 + 操作区', async () => {
    const { wrapper } = await mountWithApp(PageHeader, {
      props: { title: 'T', description: '说明' },
      slots: { breadcrumb: '<span>父级</span>', actions: '<button>新建</button>' },
    })
    expect(wrapper.find('nav').text()).toContain('父级')
    expect(wrapper.text()).toContain('说明')
    expect(wrapper.find('button').text()).toBe('新建')
  })
})

describe('RiskBadge', () => {
  it('高/中/低风险映射不同色调与文案', async () => {
    for (const level of ['high', 'medium', 'low'] as const) {
      const { wrapper } = await mountWithApp(RiskBadge, { props: { level } })
      expect(wrapper.text().length).toBeGreaterThan(0)
      wrapper.unmount()
    }
  })
})

describe('SourceBadge', () => {
  it('规则引擎与大模型来源', async () => {
    const { wrapper: rule } = await mountWithApp(SourceBadge, { props: { source: 'rule' } })
    expect(rule.text()).toBeTruthy()
    expect(rule.find('span').attributes('title')).toBeTruthy()

    const { wrapper: llm } = await mountWithApp(SourceBadge, { props: { source: 'llm' } })
    expect(llm.text()).toBeTruthy()
  })
})

describe('StatusBadge', () => {
  it('合同 / 任务 / 流程三种 kind 均可解析', async () => {
    const { wrapper: contract } = await mountWithApp(StatusBadge, { props: { kind: 'contract', value: 'draft' } })
    expect(contract.text()).toBeTruthy()

    const { wrapper: task } = await mountWithApp(StatusBadge, { props: { kind: 'task', value: 'running' } })
    expect(task.text()).toBeTruthy()

    const { wrapper: workflow } = await mountWithApp(StatusBadge, { props: { kind: 'workflow', value: 'approved' } })
    expect(workflow.text()).toBeTruthy()
  })

  it('未知状态值回退为原文 key 与 slate 色', async () => {
    const { wrapper } = await mountWithApp(StatusBadge, { props: { kind: 'contract', value: 'unknown_state' } })
    expect(wrapper.text()).toContain('unknown_state')
    expect(wrapper.classes()).toContain('pill-neutral')
  })
})

describe('StatCard', () => {
  it('无图标/趋势/链接时的基础渲染', async () => {
    const { wrapper } = await mountWithApp(StatCard, { props: { label: '合同总数', value: 42 } })
    expect(wrapper.text()).toContain('合同总数')
    expect(wrapper.text()).toContain('42')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('图标、趋势、链接与 tone 全部渲染，点击触发 action', async () => {
    const { wrapper } = await mountWithApp(StatCard, {
      props: { label: 'L', value: 'V', icon: 'file-text', trend: '+12%', linkText: '查看', tone: 'danger' },
    })
    expect(wrapper.text()).toContain('+12%')
    const btn = wrapper.find('button')
    expect(btn.text()).toContain('查看')
    await btn.trigger('click')
    expect(wrapper.emitted('action')).toBeTruthy()
  })

  it('全部 tone 可渲染', async () => {
    for (const tone of ['primary', 'warn', 'danger', 'info', 'success'] as const) {
      const { wrapper } = await mountWithApp(StatCard, { props: { label: 'L', value: 1, tone } })
      expect(wrapper.find('span.rounded-full').classes().length).toBeGreaterThan(0)
      wrapper.unmount()
    }
  })
})

describe('ProgressBar', () => {
  it('四种状态使用不同颜色类', async () => {
    const map = { done: 'bg-success-500', error: 'bg-danger-500', active: 'bg-accent', normal: 'bg-line-control' }
    for (const [status, cls] of Object.entries(map)) {
      const { wrapper } = await mountWithApp(ProgressBar, { props: { value: 50, status: status as never } })
      expect(wrapper.find('.h-full').classes()).toContain(cls)
      wrapper.unmount()
    }
  })

  it('数值被裁剪到 0-100 区间', async () => {
    const { wrapper } = await mountWithApp(ProgressBar, { props: { value: 150 } })
    expect(wrapper.find('.h-full').attributes('style')).toContain('100%')
    const { wrapper: negative } = await mountWithApp(ProgressBar, { props: { value: -10 } })
    expect(negative.find('.h-full').attributes('style')).toContain('0%')
  })

  it('showLabel 显示百分比文本', async () => {
    const { wrapper } = await mountWithApp(ProgressBar, { props: { value: 66, showLabel: true } })
    expect(wrapper.text()).toContain('66%')
    const { wrapper: hidden } = await mountWithApp(ProgressBar, { props: { value: 66 } })
    expect(hidden.text()).toBe('')
  })
})

describe('ScoreRing', () => {
  it('通过线 85 分以上为正向色', async () => {
    const { wrapper } = await mountWithApp(ScoreRing, { props: { score: 90 } })
    expect(wrapper.find('circle[stroke="#247b50"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('90')
  })

  it('60-84 分为警示色', async () => {
    const { wrapper } = await mountWithApp(ScoreRing, { props: { score: 70 } })
    expect(wrapper.find('circle[stroke="#b45309"]').exists()).toBe(true)
  })

  it('60 分以下为负向色', async () => {
    const { wrapper } = await mountWithApp(ScoreRing, { props: { score: 40 } })
    expect(wrapper.find('circle[stroke="#c4242a"]').exists()).toBe(true)
  })

  it('自定义 label 优先于默认文案', async () => {
    const { wrapper } = await mountWithApp(ScoreRing, { props: { score: 90, size: 80, label: '合规分' } })
    expect(wrapper.text()).toContain('合规分')
    expect(wrapper.find('svg').attributes('width')).toBe('80')
  })
})
