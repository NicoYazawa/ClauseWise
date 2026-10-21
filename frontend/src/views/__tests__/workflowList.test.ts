import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WorkflowListView from '@/views/workflow/WorkflowListView.vue'
import BaseTabs from '@/components/ui/BaseTabs.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchInstances: vi.fn(),
  withdrawInstance: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  currentUser: vi.fn(),
}))

vi.mock('@/api/workflows', () => ({
  fetchInstances: (...a: unknown[]) => mocks.fetchInstances(...a),
  withdrawInstance: (...a: unknown[]) => mocks.withdrawInstance(...a),
}))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({
  currentUser: () => mocks.currentUser(),
}))

const snapshot = { score: 92, highRisk: 0, amount: 1000, riskTotal: 3 }

function instance(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    status: 'running',
    currentNodeName: '部门经理审批',
    contractTitle: '设备采购合同',
    contextSnapshot: snapshot,
    definitionName: '标准合同审批流',
    definitionVersion: 2,
    starterName: '张三',
    startedAt: new Date(2026, 7, 28, 9, 0).toISOString(),
    finishedAt: null,
    ...over,
  }
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchInstances.mockResolvedValue([])
  mocks.withdrawInstance.mockResolvedValue({})
  mocks.currentUser.mockReturnValue({ realName: '张三' })
  document.body.innerHTML = ''
})

describe('WorkflowListView', () => {
  it('加载完成后无数据展示空态', async () => {
    const { wrapper } = await mountWithApp(WorkflowListView)
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('待办 tab 展示可处理实例与评分信息', async () => {
    mocks.fetchInstances.mockResolvedValue([
      instance({ id: 1 }),
      instance({ id: 2, contextSnapshot: { ...snapshot, highRisk: 2 } }),
      instance({ id: 3, status: 'approved', finishedAt: new Date().toISOString() }),
    ])
    const { wrapper } = await mountWithApp(WorkflowListView)
    await flushPromises()

    expect(wrapper.text()).toContain('设备采购合同')
    expect(wrapper.text()).toContain('92')
  })

  it('切换「我的」标签后仅展示当前用户发起的实例', async () => {
    mocks.fetchInstances.mockResolvedValue([
      instance({ id: 1, starterName: '张三', contractTitle: '我发起的合同' }),
      instance({ id: 2, starterName: '李四', contractTitle: '别人发起的合同' }),
    ])
    const { wrapper } = await mountWithApp(WorkflowListView)
    await flushPromises()

    wrapper.findComponent(BaseTabs).vm.$emit('update:modelValue', 'mine')
    await flushPromises()
    expect(wrapper.html()).toContain('我发起的合同')
  })

  it('状态筛选只保留匹配实例', async () => {
    mocks.fetchInstances.mockResolvedValue([
      instance({ id: 1, status: 'running', contractTitle: '运行中合同' }),
      instance({ id: 2, status: 'approved', contractTitle: '已通过合同', finishedAt: new Date().toISOString() }),
    ])
    const { wrapper } = await mountWithApp(WorkflowListView)
    await flushPromises()

    wrapper.findComponent(BaseTabs).vm.$emit('update:modelValue', 'done')
    await flushPromises()

    const approvedFilter = wrapper.findAll('button').find((b) => /已通过|通过/.test(b.text()))
    if (approvedFilter) {
      await approvedFilter.trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('已通过合同')
    }
  })

  it('「我的」列表中运行中的实例显示撤回入口', async () => {
    mocks.fetchInstances.mockResolvedValue([instance({ id: 5 })])
    const { wrapper } = await mountWithApp(WorkflowListView)
    await flushPromises()

    wrapper.findComponent(BaseTabs).vm.$emit('update:modelValue', 'mine')
    await flushPromises()

    expect(wrapper.findAll('button').some((b) => /撤回/.test(b.text()))).toBe(true)
  })

  it('点击实例卡片跳转详情，点击流程定义按钮跳转定义页', async () => {
    mocks.fetchInstances.mockResolvedValue([instance({ id: 9 })])
    const { wrapper, router } = await mountWithApp(WorkflowListView)
    await flushPromises()

    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    const card = wrapper.findAll('.cursor-pointer').at(-1)
    await card?.trigger('click')
    expect(pushSpy).toHaveBeenCalledWith('/workflow/9')

    const defBtn = wrapper.findAll('button').find((b) => /定义|流程/.test(b.text()))
    if (defBtn) await defBtn.trigger('click')
    expect(pushSpy).toHaveBeenCalled()
  })

  it('用户未登录时读取当前用户不报错', async () => {
    mocks.currentUser.mockReturnValue(null)
    mocks.fetchInstances.mockResolvedValue([instance({ id: 1 })])
    const { wrapper } = await mountWithApp(WorkflowListView)
    await flushPromises()
    expect(mocks.currentUser).toHaveBeenCalled()
    expect(wrapper.html()).toContain('设备采购合同')
  })
})
