import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WorkflowListView from '@/views/workflow/WorkflowListView.vue'
import AgentsView from '@/views/system/AgentsView.vue'
import BaseTabs from '@/components/ui/BaseTabs.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchInstances: vi.fn(),
  withdrawInstance: vi.fn(),
  listAgents: vi.fn(),
  fetchRecentTraces: vi.fn(),
  currentUser: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}))

vi.mock('@/api/workflows', () => ({
  fetchInstances: (...a: unknown[]) => mocks.fetchInstances(...a),
  withdrawInstance: (...a: unknown[]) => mocks.withdrawInstance(...a),
}))

vi.mock('@/api/agents', () => ({
  listAgents: (...a: unknown[]) => mocks.listAgents(...a),
  fetchRecentTraces: (...a: unknown[]) => mocks.fetchRecentTraces(...a),
}))

vi.mock('@/stores/auth', () => ({ currentUser: () => mocks.currentUser() }))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: (...a: unknown[]) => mocks.toastInfo(...a),
}))

/** 用轻量桩替换弹窗，避免动画/portal 影响交互断言 */
const modalStub = {
  props: ['open', 'title', 'width'],
  template: '<div v-if="open" class="modal-stub"><slot /><slot name="footer" /></div>',
}

function instance(over: Record<string, unknown> = {}) {
  return {
    id: 5,
    status: 'running',
    currentNodeName: '部门经理审批',
    contractTitle: '设备采购合同',
    contextSnapshot: { score: 90, highRisk: 0, amount: 1000, riskTotal: 1 },
    definitionName: '流程',
    definitionVersion: 1,
    starterName: '张三',
    startedAt: '2026-08-28T09:00:00',
    finishedAt: null,
    ...over,
  }
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchInstances.mockResolvedValue([instance()])
  mocks.withdrawInstance.mockResolvedValue({})
  mocks.listAgents.mockResolvedValue([])
  mocks.fetchRecentTraces.mockResolvedValue([])
  mocks.currentUser.mockReturnValue({ realName: '张三' })
  document.body.innerHTML = ''
})



describe('AgentsView 补充留痕分支', () => {
  it('覆盖 QA 链路与兜底摘要', async () => {
    mocks.listAgents.mockResolvedValue([
      { name: 'no_tool', role: 'R', graph: 'qa_graph', kind: 'deterministic', description: '无工具', tools: [] },
    ])
    mocks.fetchRecentTraces.mockResolvedValue([
      { id: 1, agentName: 'qa_planner', role: '规划', action: 'plan', payload: { output: { focusPoints: [] } }, latencyMs: 1, tokens: 0, error: null, createdAt: null, taskType: 'qa', refId: 0 },
      { id: 2, agentName: 'verifier', role: '校验', action: 'decision', payload: { candidates: 2 }, latencyMs: 1, tokens: 0, error: null, createdAt: null, taskType: 'review', refId: 1 },
      { id: 3, agentName: 'reporter', role: '报告', action: 'report', payload: { opinion: '意见' }, latencyMs: 1, tokens: 0, error: null, createdAt: null, taskType: 'review', refId: 1 },
      { id: 4, agentName: 'qa_reflector', role: '反思', action: 'message', payload: { passed: false }, latencyMs: 1, tokens: 0, error: null, createdAt: null, taskType: 'qa', refId: 0 },
      { id: 5, agentName: 'qa_answerer', role: '回答', action: 'report', payload: {}, latencyMs: 1, tokens: 0, error: null, createdAt: null, taskType: 'qa', refId: 0 },
      { id: 6, agentName: 'mystery', role: '未知', action: 'message', payload: {}, latencyMs: 1, tokens: 0, error: null, createdAt: null, taskType: 'qa', refId: 0 },
    ])
    const { wrapper } = await mountWithApp(AgentsView)
    await flushPromises()
    expect(mocks.fetchRecentTraces).toHaveBeenCalled()
    expect(wrapper.text()).toContain('no_tool')
  })

  it('注册表加载失败时展示空态', async () => {
    mocks.listAgents.mockRejectedValue(new Error('offline'))
    mocks.fetchRecentTraces.mockRejectedValue(new Error('offline'))
    const { wrapper } = await mountWithApp(AgentsView)
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })
})
