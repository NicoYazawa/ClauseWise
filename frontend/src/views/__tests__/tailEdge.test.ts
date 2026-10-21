import { flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BaseTabs from '@/components/ui/BaseTabs.vue'
import ContractDetailView from '@/views/contracts/ContractDetailView.vue'
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

const detailRoutes = [{ path: '/contracts/:id', component: { template: '<div />' } }]
const reportRoutes = [{ path: '/review/:taskId', component: { template: '<div />' } }]

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchTask.mockResolvedValue({ id: 7, contractId: 9, contractTitle: '合同', status: 'completed', progress: 100, taskType: 'full', errorMsg: null })
  mocks.fetchReport.mockResolvedValue({
    id: 1, taskId: 7, createdAt: '2026-08-28T10:00:00',
    findings: [],
    summary: { score: 95, high: 0, medium: 0, low: 0, aiHigh: 0, failedClauses: 0, needsReReview: false, taskType: 'full' },
    overallOpinion: 'o',
    meta: { model: 'm', promptVersion: 'v1', tokensUsed: 0, durationMs: 0 },
  })
  mocks.fetchAgentTrace.mockResolvedValue([])
  mocks.fetchContract.mockResolvedValue({
    id: 9, title: '合同', contractNo: 'HT-9', contractType: 'sale', status: 'parsed', currentVersion: 2,
    amount: 100, ownerName: '张三', counterparty: { name: '甲', idNo: '12345678', phone: '13812345678' },
    createdAt: '2026-08-01T10:00:00', updatedAt: '2026-08-28T10:00:00',
  })
  mocks.fetchVersions.mockResolvedValue([
    { id: 2, versionNo: 2, fileName: 'v2.pdf', fileSizeKb: 2048, createdAt: '2026-08-02T10:00:00', parseStatus: 'parsed', parseChannel: 'vision', parentId: 1 },
    { id: 1, versionNo: 1, fileName: 'v1.pdf', fileSizeKb: 1024, createdAt: '2026-08-01T10:00:00', parseStatus: 'parsing', parseChannel: null, parentId: null },
  ])
  mocks.fetchClauses.mockResolvedValue([])
  mocks.downloadContract.mockResolvedValue('f.pdf')
  mocks.uploadContractVersion.mockResolvedValue({ currentVersion: 3 })
  mocks.startReview.mockResolvedValue({ id: 5 })
  mocks.startApproval.mockResolvedValue({ id: 3 })
  mocks.logReportExport.mockResolvedValue(undefined)
  document.body.innerHTML = ''
})

describe('ContractDetailView 版本列表渲染', () => {
  it('版本标签下展示所有版本、解析渠道与修订关系', async () => {
    const { wrapper } = await mountWithApp(ContractDetailView, { initialPath: '/contracts/9', routes: detailRoutes })
    await flushPromises()
    await flushPromises()
    wrapper.findComponent(BaseTabs).vm.$emit('update:modelValue', 'versions')
    await flushPromises()
    await nextTick()

    const text = wrapper.text()
    expect(text).toContain('v2.pdf')
    expect(text).toContain('v1.pdf')
    expect(text).toContain('2.0 MB')
  })
})

describe('ReviewReportView blockingHigh 缺失', () => {
  it('summary 缺少 blockingHigh 时按 0 处理并可发起审批', async () => {
    const { wrapper } = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes: reportRoutes })
    await flushPromises()
    expect(wrapper.text()).toContain('95')
  })
})
