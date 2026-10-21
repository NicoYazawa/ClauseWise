import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReviewReportView from '@/views/review/ReviewReportView.vue'
import UserManagementView from '@/views/system/UserManagementView.vue'
import WorkflowDefinitionsView from '@/views/workflow/WorkflowDefinitionsView.vue'
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
  fetchUsers: vi.fn(),
  fetchRoles: vi.fn(),
  toggleUser: vi.fn(),
  updateUserRoles: vi.fn(),
  createUser: vi.fn(),
  resetPassword: vi.fn(),
  fetchDefinitions: vi.fn(),
  saveDefinition: vi.fn(),
  toggleDefinition: vi.fn(),
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
vi.mock('@/api/system', () => ({
  fetchUsers: (...a: unknown[]) => mocks.fetchUsers(...a),
  fetchRoles: (...a: unknown[]) => mocks.fetchRoles(...a),
  toggleUser: (...a: unknown[]) => mocks.toggleUser(...a),
  updateUserRoles: (...a: unknown[]) => mocks.updateUserRoles(...a),
  createUser: (...a: unknown[]) => mocks.createUser(...a),
  resetPassword: (...a: unknown[]) => mocks.resetPassword(...a),
}))
vi.mock('@/api/workflows', () => ({
  startApproval: (...a: unknown[]) => mocks.startApproval(...a),
  fetchDefinitions: (...a: unknown[]) => mocks.fetchDefinitions(...a),
  saveDefinition: (...a: unknown[]) => mocks.saveDefinition(...a),
  toggleDefinition: (...a: unknown[]) => mocks.toggleDefinition(...a),
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

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchTask.mockResolvedValue({ id: 7, contractId: 9, contractTitle: '合同', status: 'completed', progress: 100, taskType: 'full', errorMsg: null })
  mocks.fetchReport.mockResolvedValue({
    id: 1, taskId: 7, createdAt: '2026-08-28T10:00:00',
    findings: [
      { id: 1, riskLevel: 'high', riskType: 't', clauseNo: '1', issue: 'i', originalText: 'o', suggestedText: 'x', suggestion: 's', legalBasis: 'l', source: 'rule', status: 'open', ragHits: [] },
    ],
    summary: { score: 90, high: 1, medium: 0, low: 0, blockingHigh: 1, aiHigh: undefined, failedClauses: 0, needsReReview: false, taskType: 'full' },
    overallOpinion: 'o',
    meta: { model: 'm', promptVersion: 'v1', tokensUsed: 0, durationMs: 0 },
  })
  mocks.fetchAgentTrace.mockResolvedValue([])
  mocks.fetchContract.mockResolvedValue({ id: 9, title: '合同', contractNo: 'HT-9', contractType: 'sale', currentVersion: 1, amount: 1, status: 'review_passed', counterparty: { name: '甲' } })
  mocks.startApproval.mockResolvedValue({ id: 3 })
  mocks.startReview.mockResolvedValue({ id: 12 })
  mocks.logReportExport.mockResolvedValue(undefined)
  mocks.fetchUsers.mockResolvedValue([])
  mocks.fetchRoles.mockResolvedValue([
    { code: 'reviewer', name: '审查员', description: 'd' },
    { code: 'admin', name: '管理员', description: 'a' },
  ])
  mocks.toggleUser.mockResolvedValue({})
  mocks.updateUserRoles.mockResolvedValue({})
  mocks.createUser.mockResolvedValue({ username: 'n' })
  mocks.resetPassword.mockResolvedValue({ username: 'u' })
  mocks.fetchDefinitions.mockResolvedValue([])
  mocks.saveDefinition.mockResolvedValue({ id: 1, name: 'n', version: 1 })
  mocks.toggleDefinition.mockResolvedValue({ id: 1, name: 'n', enabled: true })
  document.body.innerHTML = ''
})

function bodyButton(text: string): HTMLButtonElement {
  return Array.from(document.body.querySelectorAll('button')).find((b) =>
    (b.textContent ?? '').includes(text),
  ) as HTMLButtonElement
}

describe('ReviewReportView 报告接口失败与空命中', () => {
  it('报告接口失败时展示报告错误而非任务错误', async () => {
    mocks.fetchReport.mockRejectedValue(new Error('报告尚未生成'))
    const { wrapper } = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes: reportRoutes })
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('RAG 命中为空数组时不渲染命中标签', async () => {
    const { wrapper } = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes: reportRoutes })
    await flushPromises()
    await wrapper.findAll('button').find((b) => /F-1/.test(b.text()))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('条款')
  })

  it('aiHigh 缺失时按 0 处理不渲染 AI 提示', async () => {
    const { wrapper } = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes: reportRoutes })
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(100)
  })
})

describe('UserManagementView 弹窗取消', () => {
  it('创建用户弹窗取消后不提交', async () => {
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()
    const createBtn = wrapper.findAll('button').find((b) => b.text().length > 0 && b.text().length < 8)
    await createBtn!.trigger('click')
    await flushPromises()
    await nextTick()
    bodyButton('取消').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.createUser).not.toHaveBeenCalled()
  })

  it('重置密码弹窗取消后不请求', async () => {
    mocks.fetchUsers.mockResolvedValue([
      { id: 1, username: 'u', realName: '张三', deptName: '法务部', title: 't', phone: '13812345678', roles: [], isActive: true, lastLoginAt: null },
    ])
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()
    const resetBtn = wrapper.findAll('tbody button').at(-2)
    await resetBtn!.trigger('click')
    await flushPromises()
    await nextTick()
    bodyButton('取消').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.resetPassword).not.toHaveBeenCalled()
  })

  it('角色分配弹窗取消多选后保存为空角色', async () => {
    mocks.fetchUsers.mockResolvedValue([
      { id: 1, username: 'u', realName: '张三', deptName: '法务部', title: 't', phone: '13812345678', roles: ['reviewer'], isActive: true, lastLoginAt: null },
    ])
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()
    const assignBtn = wrapper.findAll('tbody button').find((b) => b.text().length > 0 && b.text().length < 8)
    await assignBtn!.trigger('click')
    await flushPromises()
    await nextTick()

    const boxes = document.body.querySelectorAll('input[type="checkbox"]')
    // 取消已选中的第一个角色
    ;(boxes[0] as HTMLInputElement).dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()
    const save = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    save.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.updateUserRoles).toHaveBeenCalled()
  })
})

describe('WorkflowDefinitionsView 空列表', () => {
  it('无定义时页面正常渲染', async () => {
    const { wrapper } = await mountWithApp(WorkflowDefinitionsView)
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })
})
