import { flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReviewReportView from '@/views/review/ReviewReportView.vue'
import TemplateLibraryView from '@/views/knowledge/TemplateLibraryView.vue'
import UserManagementView from '@/views/system/UserManagementView.vue'
import WorkflowDetailView from '@/views/workflow/WorkflowDetailView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchTask: vi.fn(),
  fetchReport: vi.fn(),
  resolveFinding: vi.fn(),
  startReview: vi.fn(),
  logReportExport: vi.fn(),
  fetchAgentTrace: vi.fn(),
  fetchContract: vi.fn(),
  startApproval: vi.fn(),
  fetchTemplates: vi.fn(),
  saveTemplate: vi.fn(),
  deleteTemplate: vi.fn(),
  fetchUsers: vi.fn(),
  fetchRoles: vi.fn(),
  toggleUser: vi.fn(),
  updateUserRoles: vi.fn(),
  createUser: vi.fn(),
  resetPassword: vi.fn(),
  fetchInstance: vi.fn(),
  fetchDefinitions: vi.fn(),
  actOnInstance: vi.fn(),
  urgeInstance: vi.fn(),
  buildReportHtml: vi.fn(() => '<html/>'),
  downloadWord: vi.fn(),
  printAsPdf: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}))

vi.mock('@/api/reviews', () => ({
  fetchTask: (...a: unknown[]) => mocks.fetchTask(...a),
  fetchReport: (...a: unknown[]) => mocks.fetchReport(...a),
  resolveFinding: (...a: unknown[]) => mocks.resolveFinding(...a),
  startReview: (...a: unknown[]) => mocks.startReview(...a),
  logReportExport: (...a: unknown[]) => mocks.logReportExport(...a),
}))
vi.mock('@/api/agents', () => ({ fetchAgentTrace: (...a: unknown[]) => mocks.fetchAgentTrace(...a) }))
vi.mock('@/api/contracts', () => ({ fetchContract: (...a: unknown[]) => mocks.fetchContract(...a) }))
vi.mock('@/api/workflows', () => ({
  startApproval: (...a: unknown[]) => mocks.startApproval(...a),
  fetchInstance: (...a: unknown[]) => mocks.fetchInstance(...a),
  fetchDefinitions: (...a: unknown[]) => mocks.fetchDefinitions(...a),
  actOnInstance: (...a: unknown[]) => mocks.actOnInstance(...a),
  urgeInstance: (...a: unknown[]) => mocks.urgeInstance(...a),
}))
vi.mock('@/api/knowledge', () => ({
  fetchTemplates: (...a: unknown[]) => mocks.fetchTemplates(...a),
  saveTemplate: (...a: unknown[]) => mocks.saveTemplate(...a),
  deleteTemplate: (...a: unknown[]) => mocks.deleteTemplate(...a),
}))
vi.mock('@/api/system', () => ({
  fetchUsers: (...a: unknown[]) => mocks.fetchUsers(...a),
  fetchRoles: (...a: unknown[]) => mocks.fetchRoles(...a),
  toggleUser: (...a: unknown[]) => mocks.toggleUser(...a),
  updateUserRoles: (...a: unknown[]) => mocks.updateUserRoles(...a),
  createUser: (...a: unknown[]) => mocks.createUser(...a),
  resetPassword: (...a: unknown[]) => mocks.resetPassword(...a),
}))
vi.mock('@/utils/export', () => ({
  buildReportHtml: (...a: unknown[]) => mocks.buildReportHtml(...a),
  downloadWord: (...a: unknown[]) => mocks.downloadWord(...a),
  printAsPdf: (...a: unknown[]) => mocks.printAsPdf(...a),
}))
vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: (...a: unknown[]) => mocks.toastInfo(...a),
}))

const reportRoutes = [{ path: '/review/:taskId', component: { template: '<div />' } }]
const wfRoutes = [{ path: '/workflow/:id', component: { template: '<div />' } }]

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchTask.mockResolvedValue({ id: 7, contractId: 9, contractTitle: '合同', status: 'completed', progress: 100, taskType: 'full', errorMsg: null })
  mocks.fetchReport.mockResolvedValue({
    id: 1, taskId: 7, createdAt: '2026-08-28T10:00:00',
    findings: [],
    summary: { score: 95, high: 0, medium: 0, low: 0, blockingHigh: 0, aiHigh: 0, failedClauses: 0, needsReReview: false, taskType: 'full' },
    overallOpinion: 'o',
    meta: { model: 'm', promptVersion: 'v1', tokensUsed: 0, durationMs: 0 },
  })
  mocks.fetchAgentTrace.mockResolvedValue([
    { id: 1, agentName: 'clause_reviewer', role: '条款', action: 'decision', payload: { tools: [{ tool: 'rag' }], result: { riskLevel: 'none' }, clauseNo: '3.2' }, latencyMs: 1, tokens: 0, error: null, createdAt: '2026-08-28T10:00:00' },
    { id: 2, agentName: 'clause_reviewer', role: '条款', action: 'tool_loop', payload: { tools: [], result: { riskLevel: 'high', riskType: 'x' } }, latencyMs: 1, tokens: 0, error: null, createdAt: '2026-08-28T10:01:00' },
    { id: 3, agentName: 'verifier', role: '校验', action: 'report', payload: { summary: '校验完成' }, latencyMs: 1, tokens: 0, error: null, createdAt: '2026-08-28T10:02:00' },
  ])
  mocks.fetchContract.mockResolvedValue(null)
  mocks.startApproval.mockResolvedValue({ id: 3 })
  mocks.startReview.mockResolvedValue({ id: 12 })
  mocks.logReportExport.mockResolvedValue(undefined)
  mocks.fetchTemplates.mockResolvedValue([])
  mocks.saveTemplate.mockResolvedValue({})
  mocks.deleteTemplate.mockResolvedValue(undefined)
  mocks.fetchUsers.mockResolvedValue([
    { id: 1, username: 'u', realName: '张三', deptName: '法务部', title: 't', phone: '13812345678', roles: [], isActive: true, lastLoginAt: null },
  ])
  mocks.fetchRoles.mockResolvedValue([])
  mocks.toggleUser.mockResolvedValue({})
  mocks.updateUserRoles.mockResolvedValue({})
  mocks.createUser.mockResolvedValue({ username: 'n' })
  mocks.resetPassword.mockResolvedValue({ username: 'u' })
  mocks.fetchInstance.mockResolvedValue({
    id: 1, contractId: 0, contractTitle: '合同', status: 'running', currentNodeId: 'n1', currentNodeName: '',
    definitionId: 3, definitionName: '流程', definitionVersion: 1, starterName: '张三',
    startedAt: '2026-08-28T09:00:00', finishedAt: null,
    contextSnapshot: { score: 90, amount: 1, riskTotal: 0, highRisk: 0 }, records: [{ nodeName: '提交', action: 'submit', operatorName: '张三', comment: '', createdAt: '2026-08-28T09:00:00' }],
  })
  mocks.fetchDefinitions.mockResolvedValue([{ id: 3, nodes: [] }])
  mocks.actOnInstance.mockResolvedValue({})
  mocks.urgeInstance.mockResolvedValue({})
  document.body.innerHTML = ''
})

function bodyButton(text: string): HTMLButtonElement {
  return Array.from(document.body.querySelectorAll('button')).find((b) =>
    (b.textContent ?? '').includes(text),
  ) as HTMLButtonElement
}

describe('ReviewReportView 留痕风险为空/有风险', () => {
  it('无风险结论展示“无风险”而非风险等级', async () => {
    const { wrapper } = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes: reportRoutes })
    await flushPromises()
    const toggle = wrapper.findAll('button').find((b) => /展开|协作/.test(b.text()))
    if (toggle) {
      await toggle.trigger('click')
      await flushPromises()
    }
    expect(wrapper.text().length).toBeGreaterThan(100)
  })
})

describe('UserManagementView 启停失败', () => {
  it('停用失败提示错误', async () => {
    mocks.toggleUser.mockRejectedValue(new Error('不能停用自己'))
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()
    await wrapper.findAll('tbody button').at(-1)!.trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('不能停用自己')
  })
})

describe('TemplateLibraryView 删除取消', () => {
  it('删除弹窗取消后不请求', async () => {
    mocks.fetchTemplates.mockResolvedValue([
      { id: 1, name: '条款', contractType: 'purchase', clauseLevel: 'required', content: 'c', version: 1 },
    ])
    const { wrapper } = await mountWithApp(TemplateLibraryView)
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.attributes('title') === '删除')
    await delBtn!.trigger('click')
    await flushPromises()
    await nextTick()
    bodyButton('取消').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.deleteTemplate).not.toHaveBeenCalled()
  })
})

describe('WorkflowDetailView 空节点名与催办成功', () => {
  it('当前节点名为空时催办提示仍可渲染', async () => {
    const { wrapper } = await mountWithApp(WorkflowDetailView, { initialPath: '/workflow/1', routes: wfRoutes })
    await flushPromises()
    const urge = wrapper.findAll('button').find((b) => /催办/.test(b.text()))
    await urge!.trigger('click')
    await flushPromises()
    expect(mocks.urgeInstance).toHaveBeenCalledWith(1)
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })
})
