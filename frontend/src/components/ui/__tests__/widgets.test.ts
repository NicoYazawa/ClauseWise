import { describe, expect, it } from 'vitest'

import BrandLogo from '@/components/ui/BrandLogo.vue'
import DiffPane from '@/components/ui/DiffPane.vue'
import Pagination from '@/components/ui/Pagination.vue'
import StepFlow from '@/components/ui/StepFlow.vue'
import Timeline from '@/components/ui/Timeline.vue'
import { mountWithApp } from '@test/helpers'
import type { ClauseDiffItem, WFNode } from '@/types'

describe('BrandLogo', () => {
  it('默认 28px，可自定义尺寸', async () => {
    const { wrapper } = await mountWithApp(BrandLogo)
    expect(wrapper.find('svg').attributes('width')).toBe('28')
    const { wrapper: large } = await mountWithApp(BrandLogo, { props: { size: 48 } })
    expect(large.find('svg').attributes('width')).toBe('48')
  })
})

describe('Timeline', () => {
  it('空列表渲染空容器', async () => {
    const { wrapper } = await mountWithApp(Timeline, { props: { items: [] } })
    expect(wrapper.findAll('li').length).toBe(0)
  })

  it('多条记录：首节点高亮、中间有连接线、末节点无连接线', async () => {
    const { wrapper } = await mountWithApp(Timeline, {
      props: {
        items: [
          { title: '提交', time: '10:00', operator: '张三', content: '已提交' },
          { title: '审批', time: '11:00', tag: '通过', tagTone: 'success' },
          { title: '归档', time: '12:00', tag: '默认标签' },
        ],
      },
    })
    const lis = wrapper.findAll('li')
    expect(lis.length).toBe(3)
    // 前两个节点带连接线，最后一个不带
    expect(lis[0].find('.absolute.left-\\[5px\\]').exists()).toBe(true)
    expect(lis[2].find('.absolute.left-\\[5px\\]').exists()).toBe(false)
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('通过')
  })

  it('tagTone 各种色调均可渲染', async () => {
    for (const tagTone of ['slate', 'info', 'warn', 'danger', 'success', 'primary'] as const) {
      const { wrapper } = await mountWithApp(Timeline, {
        props: { items: [{ title: 't', tag: 'x', tagTone }] },
      })
      expect(wrapper.text()).toContain('x')
      wrapper.unmount()
    }
  })
})

describe('StepFlow', () => {
  const nodes: WFNode[] = [
    { id: 'start', type: 'start', name: '提交' } as WFNode,
    { id: 'n1', type: 'approval', name: '部门审批', signMode: 'or', timeoutHours: 24, assignees: ['a', 'b'] } as WFNode,
    { id: 'end', type: 'end', name: '完成' } as WFNode,
  ]

  it('运行中：当前节点高亮，之前为完成，之后为待处理', async () => {
    const { wrapper } = await mountWithApp(StepFlow, {
      props: { nodes, currentNodeId: 'n1', status: 'running' },
    })
    expect(wrapper.text()).toContain('部门审批')
    expect(wrapper.text()).toContain('24h')
    expect(wrapper.text()).toContain('a / b')
    expect(wrapper.findAll('.border-accent').length).toBeGreaterThan(0)
  })

  it('非 running 状态全部视为已完成', async () => {
    for (const status of ['approved', 'rejected', 'withdrawn'] as const) {
      const { wrapper } = await mountWithApp(StepFlow, { props: { nodes, currentNodeId: 'n1', status } })
      expect(wrapper.findAll('.border-success-300').length).toBe(3)
      wrapper.unmount()
    }
  })

  it('未知节点类型回退 info 图标，规则条件展示', async () => {
    const { wrapper } = await mountWithApp(StepFlow, {
      props: {
        nodes: [{ id: 'x', type: 'unknown' as never, name: '节点', rules: [{ when: 'score < 60' }] } as unknown as WFNode],
        currentNodeId: 'x',
      },
    })
    expect(wrapper.text()).toContain('score < 60')
  })

  it('无 signMode/timeout/assignees/rules 时不渲染附加信息', async () => {
    const { wrapper } = await mountWithApp(StepFlow, {
      props: { nodes: [{ id: 'a', type: 'start', name: 'S' } as WFNode], currentNodeId: 'a' },
    })
    expect(wrapper.text()).toContain('S')
    expect(wrapper.findAll('p').length).toBe(0)
  })
})

describe('Pagination', () => {
  it('total 为 0 时整体不渲染', async () => {
    const { wrapper } = await mountWithApp(Pagination, { props: { page: 1, pageSize: 10, total: 0 } })
    expect(wrapper.find('div').exists()).toBe(false)
  })

  it('展示区间与页码，点击页码发出 change', async () => {
    const { wrapper } = await mountWithApp(Pagination, { props: { page: 1, pageSize: 10, total: 100 } })
    expect(wrapper.text()).toContain('1')
    const pageButtons = wrapper.findAll('button').filter((b) => /^\d+$/.test(b.text()))
    expect(pageButtons.length).toBeGreaterThan(0)
    await pageButtons[1].trigger('click')
    expect(wrapper.emitted('change')?.at(-1)).toEqual([2])
  })

  it('首页禁用上一页，末页禁用下一页', async () => {
    const { wrapper: first } = await mountWithApp(Pagination, { props: { page: 1, pageSize: 10, total: 20 } })
    const buttons = first.findAll('button')
    expect(buttons[0].attributes('disabled')).toBeDefined()
    expect(buttons.at(-1)!.attributes('disabled')).toBeUndefined()

    const { wrapper: last } = await mountWithApp(Pagination, { props: { page: 2, pageSize: 10, total: 20 } })
    const lastButtons = last.findAll('button')
    expect(lastButtons[0].attributes('disabled')).toBeUndefined()
    expect(lastButtons.at(-1)!.attributes('disabled')).toBeDefined()
  })

  it('中间页时页码窗口以当前页为中心', async () => {
    const { wrapper } = await mountWithApp(Pagination, { props: { page: 6, pageSize: 10, total: 200 } })
    const nums = wrapper.findAll('button').filter((b) => /^\d+$/.test(b.text())).map((b) => b.text())
    expect(nums).toContain('6')
    expect(nums).toContain('4')
    expect(nums).toContain('8')
  })
})

describe('DiffPane', () => {
  const items: ClauseDiffItem[] = [
    { clauseNo: '1.1', kind: 'modified', oldText: '旧文本', newText: '新文本', summary: '修改了账期' } as ClauseDiffItem,
    { clauseNo: '1.2', kind: 'added', oldText: '', newText: '新增条款', summary: '新增' } as ClauseDiffItem,
    { clauseNo: '1.3', kind: 'removed', oldText: '删除条款', newText: '', summary: '删除' } as ClauseDiffItem,
    { clauseNo: '1.4', kind: 'drift', oldText: '偏移', newText: '偏移2', summary: '偏移' } as ClauseDiffItem,
  ]

  it('全部条目均无文本时展示空态', async () => {
    const { wrapper } = await mountWithApp(DiffPane, {
      props: { items: [{ clauseNo: '1', kind: 'modified', oldText: '', newText: '', summary: 's' } as ClauseDiffItem] },
    })
    expect(wrapper.text()).toContain('未检测到条款差异')
  })

  it('新增/删除/修改/偏移四种差异类型都可渲染', async () => {
    const { wrapper } = await mountWithApp(DiffPane, { props: { items } })
    expect(wrapper.text()).toContain('1.1')
    expect(wrapper.text()).toContain('修改了账期')
    // 只有新增的空原文会展示占位
    expect(wrapper.text()).toContain('1.2')
    expect(wrapper.text()).toContain('1.3')
    expect(wrapper.text()).toContain('1.4')
  })

  it('单侧缺失时展示对应占位文案', async () => {
    const { wrapper } = await mountWithApp(DiffPane, {
      props: { items: [{ clauseNo: '9', kind: 'added', oldText: '', newText: 'x', summary: 's' } as ClauseDiffItem] },
    })
    expect(wrapper.findAll('p.italic').length).toBeGreaterThan(0)
  })
})
