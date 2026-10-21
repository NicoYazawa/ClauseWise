import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ContractDetailView from '@/views/contracts/ContractDetailView.vue'
import ModelPromptView from '@/views/system/ModelPromptView.vue'
import ReviewReportView from '@/views/review/ReviewReportView.vue'
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
  fetchVersions: vi.fn(),
  fetchClauses: vi.fn(),
  downloadContract: vi.fn(),
  uploadContractVersion: vi.fn(),
  fetchModelVersions: vi.fn(),
  setDefaultModel: vi.fn(),
  fetchPrompts: vi.fn(),
  savePromptContent: vi.fn(),
  activatePrompt: vi.fn(),
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
vi.mock('@/api/contracts', () => ({
  fetchContract: (...a: unknown[]) => mocks.fetchContract(...a),
  fetchVersions: (...a: unknown[]) => mocks.fetchVersions(...a),
  fetchClauses: (...a: unknown[]) => mocks.fetchClauses(...a),
  downloadContract: (...a: unknown[]) => mocks.downloadContract(...a),
  uploadContractVersion: (...a: unknown[]) => mocks.uploadContractVersion(...a),
}))
vi.mock('@/api/workflows', () => ({ startApproval: (...a: unknown[]) => mocks.startApproval(...a) }))
vi.mock('@/api/system', () => ({
  fetchModelVersions: (...a: unknown[]) => mocks.fetchModelVersions(...a),
  setDefaultModel: (...a: unknown[]) => mocks.setDefaultModel(...a),
  fetchPrompts: (...a: unknown[]) => mocks.fetchPrompts(...a),
  savePromptContent: (...a: unknown[]) => mocks.savePromptContent(...a),
  activatePrompt: (...a: unknown[]) => mocks.activatePrompt(...a),
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
const detailRoutes = [{ path: '/contracts/:id', component: { template: '<div />' } }]

function report(over: Record<string, unknown> = {}) {
  return {
    id: 88,
    taskId: 7,
    createdAt: '2026-08-28T10:00:00',
    findings: [],
    summary: { score: 95, high: 0, medium: 0, low: 0, blockingHigh: 0, aiHigh: 0, failedClauses: 0, needsReReview: false, taskType: 'full' },
    overallOpinion: '无风险',
    meta: { model: 'm', promptVersion: 'v1', tokensUsed: 0, durationMs: 0 },
    ...over,
  }
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchTask.mockResolvedValue({ id: 7, contractId: 9, contractTitle: '合同', status: 'completed', progress: 100, taskType: 'full', errorMsg: null })
  mocks.fetchReport.mockResolvedValue(report())
  mocks.fetchAgentTrace.mockResolvedValue([])
  mocks.fetchContract.mockResolvedValue({ id: 9, title: '合同', contractNo: 'HT-9', contractType: 'sale', currentVersion: 1, amount: 1, status: 'review_passed', counterparty: { name: '甲' } })
  mocks.startApproval.mockResolvedValue({ id: 3 })
  mocks.startReview.mockResolvedValue({ id: 12 })
  mocks.logReportExport.mockResolvedValue(undefined)
  mocks.fetchVersions.mockResolvedValue([])
  mocks.fetchClauses.mockResolvedValue([])
  mocks.downloadContract.mockResolvedValue('f.pdf')
  mocks.uploadContractVersion.mockResolvedValue({ currentVersion: 2 })
  mocks.fetchModelVersions.mockResolvedValue([])
  mocks.setDefaultModel.mockResolvedValue({})
  mocks.fetchPrompts.mockResolvedValue([])
  mocks.savePromptContent.mockResolvedValue({ version: 'v2' })
  mocks.activatePrompt.mockResolvedValue({})
  document.body.innerHTML = ''
})

describe('ReviewReportView 状态与空数据', () => {
  it('无风险项时展示空提示', async () => {
    const { wrapper } = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes: reportRoutes })
    await flushPromises()
    expect(wrapper.text()).toContain('无风险')
  })

  it('待处理任务展示排队状态', async () => {
    mocks.fetchTask.mockResolvedValue({ id: 7, contractId: 9, contractTitle: '合同', status: 'pending', progress: 0, taskType: 'full', errorMsg: null })
    mocks.fetchReport.mockResolvedValue(null)
    const { wrapper } = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes: reportRoutes })
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
    expect(wrapper.find('textarea').exists()).toBe(false)
  })

  it('失败任务无错误信息时展示兜底文案', async () => {
    mocks.fetchTask.mockResolvedValue({ id: 7, contractId: 9, contractTitle: '合同', status: 'failed', progress: 0, taskType: 'full', errorMsg: null })
    mocks.fetchReport.mockResolvedValue(null)
    const { wrapper } = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes: reportRoutes })
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('阻断项全部修复时展示绿色提示', async () => {
    mocks.fetchReport.mockResolvedValue(
      report({
        findings: [{ id: 1, riskLevel: 'high', riskType: 't', clauseNo: '1', issue: 'i', originalText: 'o', suggestion: 's', legalBasis: 'l', source: 'rule', status: 'fixed' }],
        summary: { score: 60, high: 1, medium: 0, low: 0, blockingHigh: 1, aiHigh: 0, failedClauses: 0, needsReReview: false, taskType: 'full' },
      }),
    )
    const { wrapper } = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes: reportRoutes })
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(100)
  })
})

describe('ContractDetailView 状态变体', () => {
  const base = {
    id: 1, title: '合同', contractNo: 'HT-1', contractType: 'sale', status: 'review_passed', currentVersion: 1, amount: 100,
    ownerName: '张三', counterparty: { name: '甲', idNo: '12345678', phone: '13812345678' },
    createdAt: '2026-08-01T10:00:00', updatedAt: '2026-08-28T10:00:00',
  }

  it('review_blocked 状态可发起审查', async () => {
    mocks.fetchContract.mockResolvedValue({ ...base, status: 'review_blocked' })
    const { wrapper } = await mountWithApp(ContractDetailView, { initialPath: '/contracts/1', routes: detailRoutes })
    await flushPromises()
    expect(wrapper.findAll('button').some((b) => /审查/.test(b.text()))).toBe(true)
  })

  it('review_passed 状态可发起审查', async () => {
    mocks.fetchContract.mockResolvedValue({ ...base, status: 'review_passed' })
    const { wrapper } = await mountWithApp(ContractDetailView, { initialPath: '/contracts/1', routes: detailRoutes })
    await flushPromises()
    expect(wrapper.findAll('button').some((b) => /审查/.test(b.text()))).toBe(true)
  })
})

describe('ModelPromptView 状态组合', () => {
  it('默认模型与启用 Prompt 分别展示状态标识', async () => {
    mocks.fetchModelVersions.mockResolvedValue([
      { id: 1, modelName: 'm1', modelType: 'llm', evalMetrics: { accuracy: 0.9, falsePositive: 0.1, adoptionRate: 0.5 }, activatedAt: '2026-08-28T10:00:00', isDefault: true },
    ])
    mocks.fetchPrompts.mockResolvedValue([
      { id: 1, scene: 'review', version: 'v1', content: 'c', isActive: true, updatedAt: '2026-08-28T10:00:00' },
      { id: 2, scene: 'review', version: 'v2', content: 'c2', isActive: false, updatedAt: '2026-08-28T10:00:00' },
    ])
    const { wrapper } = await mountWithApp(ModelPromptView)
    await flushPromises()
    expect(wrapper.text()).toContain('m1')
    expect(wrapper.text()).toContain('v1')
    expect(wrapper.text()).toContain('v2')
  })
})
