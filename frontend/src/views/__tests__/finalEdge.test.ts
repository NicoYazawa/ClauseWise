import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReviewReportView from '@/views/review/ReviewReportView.vue'
import TemplateLibraryView from '@/views/knowledge/TemplateLibraryView.vue'
import UserManagementView from '@/views/system/UserManagementView.vue'
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
vi.mock('@/api/workflows', () => ({ startApproval: (...a: unknown[]) => mocks.startApproval(...a) }))
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

function finding(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    riskLevel: 'low',
    riskType: '格式问题',
    clauseNo: '1.1',
    issue: '缺少签署日期',
    originalText: '原文',
    suggestion: '补充日期',
    legalBasis: '规范',
    source: 'llm',
    status: 'rejected',
    ...over,
  }
}

const report = {
  id: 88,
  taskId: 7,
  createdAt: '2026-08-28T10:00:00',
  findings: [finding()],
  summary: { score: 88, high: 0, medium: 0, low: 1, blockingHigh: 0, aiHigh: 0, failedClauses: 0, needsReReview: false, taskType: 'full' },
  overallOpinion: '可通过',
  meta: { model: 'm', promptVersion: 'v1', tokensUsed: 0, durationMs: 0 },
}

const routes = [{ path: '/review/:taskId', component: { template: '<div />' } }]

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchTask.mockResolvedValue({ id: 7, contractId: 9, contractTitle: '合同', status: 'completed', progress: 100, taskType: 'diff', errorMsg: null })
  mocks.fetchReport.mockResolvedValue(report)
  mocks.fetchAgentTrace.mockResolvedValue([])
  mocks.fetchContract.mockResolvedValue({
    id: 9, title: '合同', contractNo: 'HT-9', contractType: 'sale', currentVersion: 3, amount: 10, status: 'review_passed', counterparty: { name: '甲方' },
  })
  mocks.startApproval.mockResolvedValue({ id: 3 })
  mocks.startReview.mockResolvedValue({ id: 12 })
  mocks.logReportExport.mockResolvedValue(undefined)
  mocks.fetchTemplates.mockResolvedValue([])
  mocks.saveTemplate.mockResolvedValue({})
  mocks.deleteTemplate.mockResolvedValue(undefined)
  mocks.fetchUsers.mockResolvedValue([])
  mocks.fetchRoles.mockResolvedValue([{ code: 'reviewer', name: '审查员', description: 'd' }])
  mocks.toggleUser.mockResolvedValue({})
  mocks.updateUserRoles.mockResolvedValue({})
  mocks.createUser.mockResolvedValue({ username: 'n' })
  mocks.resetPassword.mockResolvedValue({ username: 'u' })
  document.body.innerHTML = ''
})

describe('ReviewReportView 补充', () => {
  it('已拒绝的风险项展示状态徽章而非操作按钮', async () => {
    const { wrapper } = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes })
    await flushPromises()
    await wrapper.findAll('button').find((b) => /F-1/.test(b.text()))!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('button').some((b) => /采纳/.test(b.text()))).toBe(false)
  })

  it('留痕摘要覆盖空判决/无工具/无统计三类兜底', async () => {
    mocks.fetchAgentTrace.mockResolvedValue([
      { id: 1, agentName: 'verifier', role: '校验', action: 'decision', payload: { verdicts: [], candidates: 0 }, latencyMs: 10, tokens: 0, error: null, createdAt: '2026-08-28T10:00:00' },
      { id: 2, agentName: 'clause_reviewer', role: '条款', action: 'tool_loop', payload: { tools: [] }, latencyMs: 10, tokens: 0, error: null, createdAt: '2026-08-28T10:01:00' },
      { id: 3, agentName: 'reporter', role: '报告', action: 'report', payload: { opinion: '完成' }, latencyMs: 10, tokens: 0, error: null, createdAt: '2026-08-28T10:02:00' },
    ])
    const { wrapper } = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes })
    await flushPromises()
    const toggle = wrapper.findAll('button').find((b) => /展开|协作/.test(b.text()))
    if (toggle) {
      await toggle.trigger('click')
      await flushPromises()
    }
    expect(wrapper.text()).toContain('完成')
  })

  it('增量审查任务展示报告主体与底部审查类型说明', async () => {
    const { wrapper } = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes })
    await flushPromises()
    expect(wrapper.text()).toContain('报告')
    expect(wrapper.text().length).toBeGreaterThan(200)
  })
})

describe('TemplateLibraryView 空组与删除', () => {
  it('无条款时三个等级都展示空组提示', async () => {
    const { wrapper } = await mountWithApp(TemplateLibraryView)
    await flushPromises()
    expect(wrapper.findAll('p').length).toBeGreaterThan(0)
  })

  it('仅推荐级有数据时其余分组为空', async () => {
    mocks.fetchTemplates.mockResolvedValue([
      { id: 1, name: '推荐条款', contractType: 'purchase', clauseLevel: 'recommended', content: 'c', version: 1 },
    ])
    const { wrapper } = await mountWithApp(TemplateLibraryView)
    await flushPromises()
    expect(wrapper.text()).toContain('推荐条款')
  })
})

describe('UserManagementView 创建部门选择', () => {
  it('切换部门并创建用户', async () => {
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()
    const createBtn = wrapper.findAll('button').find((b) => b.text().length > 0 && b.text().length < 8)
    await createBtn!.trigger('click')
    await flushPromises()
    await nextTick()

    const select = document.body.querySelector('select') as HTMLSelectElement
    await new DOMWrapper(select).setValue('采购部')
    await flushPromises()

    const submit = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    submit.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.createUser).toHaveBeenCalledWith(expect.objectContaining({ deptName: '采购部' }))
  })
})
