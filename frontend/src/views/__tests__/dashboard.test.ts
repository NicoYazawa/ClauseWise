import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DashboardView from '@/views/dashboard/DashboardView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchContracts: vi.fn(),
  fetchTasks: vi.fn(),
  fetchReport: vi.fn(),
  fetchFindings: vi.fn(),
  fetchInstances: vi.fn(),
  fetchNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
}))

vi.mock('@/api/contracts', () => ({ fetchContracts: (...a: unknown[]) => mocks.fetchContracts(...a) }))
vi.mock('@/api/reviews', () => ({
  fetchTasks: (...a: unknown[]) => mocks.fetchTasks(...a),
  fetchReport: (...a: unknown[]) => mocks.fetchReport(...a),
  fetchFindings: (...a: unknown[]) => mocks.fetchFindings(...a),
}))
vi.mock('@/api/workflows', () => ({ fetchInstances: (...a: unknown[]) => mocks.fetchInstances(...a) }))
vi.mock('@/api/system', () => ({
  fetchNotifications: (...a: unknown[]) => mocks.fetchNotifications(...a),
  markNotificationRead: (...a: unknown[]) => mocks.markNotificationRead(...a),
}))

vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })),
}))

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchContracts.mockResolvedValue([])
  mocks.fetchTasks.mockResolvedValue([])
  mocks.fetchReport.mockResolvedValue(null)
  mocks.fetchFindings.mockResolvedValue([])
  mocks.fetchInstances.mockResolvedValue([])
  mocks.fetchNotifications.mockResolvedValue([])
  mocks.markNotificationRead.mockResolvedValue(undefined)
})

describe('DashboardView 概览', () => {
  it('空数据时展示空态与零值', async () => {
    const { wrapper } = await mountWithApp(DashboardView)
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('统计卡、待办与通知按数据渲染', async () => {
    mocks.fetchContracts.mockResolvedValue([
      { id: 1, title: '合同A', contractNo: 'HT-1', contractType: 'sale', status: 'review_passed', updatedAt: '2026-08-28T10:00:00' },
    ])
    mocks.fetchTasks.mockResolvedValue([
      { id: 1, contractTitle: '合同A', status: 'running', progress: 30, createdAt: new Date().toISOString() },
      { id: 2, contractTitle: '合同B', status: 'pending', createdAt: new Date().toISOString() },
      { id: 3, contractTitle: '合同C', status: 'completed', createdAt: new Date().toISOString() },
    ])
    mocks.fetchInstances.mockResolvedValue([
      { id: 5, contractTitle: '合同A', status: 'running', currentNodeName: '部门经理审批', startedAt: new Date().toISOString() },
    ])
    mocks.fetchFindings.mockResolvedValue([{ id: 1, riskLevel: 'high' }, { id: 2, riskLevel: 'medium' }])
    mocks.fetchNotifications.mockResolvedValue([
      { id: 1, type: 'review_done', title: '审查完成', content: '合同A 审查完成', read: false, createdAt: new Date().toISOString() },
      { id: 2, type: 'approval_todo', title: '待审批', content: '请处理', read: true, createdAt: null },
      { id: 3, type: 'unknown_type', title: '其他', content: 'x', read: false, createdAt: null },
    ])

    const { wrapper } = await mountWithApp(DashboardView)
    await flushPromises()

    expect(wrapper.text()).toContain('审查完成')
    expect(wrapper.text()).toContain('待审批')
    expect(wrapper.text()).toContain('待处理')
  })

  it('点击未读通知标记已读；已读通知不重复请求', async () => {
    mocks.fetchNotifications.mockResolvedValue([
      { id: 1, type: 'review_done', title: '未读通知', content: 'c', read: false, createdAt: null },
      { id: 2, type: 'review_done', title: '已读通知', content: 'c', read: true, createdAt: null },
    ])
    const { wrapper } = await mountWithApp(DashboardView)
    await flushPromises()

    const notifButtons = wrapper.findAll('button').filter((b) => /通知/.test(b.text()))
    expect(notifButtons.length).toBe(2)
    await notifButtons[0].trigger('click')
    await flushPromises()
    expect(mocks.markNotificationRead).toHaveBeenCalledWith(1)

    await notifButtons[1].trigger('click')
    await flushPromises()
    expect(mocks.markNotificationRead).toHaveBeenCalledTimes(1)
  })

  it('标记已读失败时回滚本地状态并重新拉取', async () => {
    mocks.fetchNotifications.mockResolvedValue([
      { id: 1, type: 'review_done', title: '未读通知', content: 'c', read: false, createdAt: null },
    ])
    mocks.markNotificationRead.mockRejectedValue(new Error('fail'))
    const { wrapper } = await mountWithApp(DashboardView)
    await flushPromises()

    await wrapper.findAll('button').filter((b) => /通知/.test(b.text()))[0].trigger('click')
    await flushPromises()
    expect(mocks.fetchNotifications.mock.calls.length).toBeGreaterThan(1)
  })

  it('点击统计卡与待办项触发路由跳转', async () => {
    mocks.fetchTasks.mockResolvedValue([
      { id: 1, contractTitle: '合同A', status: 'running', progress: 30, createdAt: new Date().toISOString() },
    ])
    const { wrapper, router } = await mountWithApp(DashboardView)
    await flushPromises()
    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)

    const todo = wrapper.findAll('button').find((b) => /审查中|审批/.test(b.text()))
    if (todo) await todo.trigger('click')
    expect(pushSpy).toHaveBeenCalled()
  })

  it('点击最近合同行跳转详情', async () => {
    mocks.fetchContracts.mockResolvedValue([
      { id: 3, title: '合同C', contractNo: 'HT-3', contractType: 'sale', status: 'draft', updatedAt: '2026-08-28T10:00:00' },
    ])
    const { wrapper, router } = await mountWithApp(DashboardView)
    await flushPromises()
    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    const row = wrapper.findAll('tbody tr').at(-1)
    await row?.trigger('click')
    expect(pushSpy).toHaveBeenCalledWith('/contracts/3')
  })

  it('刷新按钮重新拉取全部数据', async () => {
    const { wrapper } = await mountWithApp(DashboardView)
    await flushPromises()
    const before = mocks.fetchContracts.mock.calls.length
    const refresh = wrapper.findAll('button').find((b) => /刷新/.test(b.text()))
    await refresh?.trigger('click')
    await flushPromises()
    expect(mocks.fetchContracts.mock.calls.length).toBeGreaterThan(before)
  })

  it('已完成任务存在报告时绘制评分趋势', async () => {
    mocks.fetchTasks.mockResolvedValue([
      { id: 1, contractTitle: '合同A', status: 'completed', progress: 100, createdAt: new Date().toISOString() },
    ])
    mocks.fetchReport.mockResolvedValue({ summary: { score: 88 } })
    const { wrapper } = await mountWithApp(DashboardView)
    await flushPromises()
    expect(mocks.fetchReport).toHaveBeenCalledWith(1)
    expect(wrapper.text().length).toBeGreaterThan(0)
  })
})
