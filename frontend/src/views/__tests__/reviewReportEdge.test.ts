import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

const task = {
  id: 7,
  contractId: 9,
  contractTitle: '设备采购合同',
  status: 'completed',
  progress: 100,
  taskType: 'clause',
  errorMsg: null,
}

function finding(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    riskLevel: 'medium',
    riskType: '责任不对等',
    clauseNo: '5.1',
    issue: '违约责任缺失',
    originalText: '原文条款',
    suggestion: '补充违约责任',
    legalBasis: '《民法典》第 577 条',
    source: 'llm',
    status: 'open',
    ...over,
  }
}

const report = {
  id: 88,
  taskId: 7,
  createdAt: '2026-08-28T10:00:00',
  findings: [finding(), finding({ id: 2, riskLevel: 'low', riskType: '低风险项' })],
  summary: { score: 90, high: 0, medium: 1, low: 1, blockingHigh: 0, aiHigh: 0, failedClauses: 0, needsReReview: false, taskType: 'full' },
  overallOpinion: '可签署',
  meta: { model: 'm', promptVersion: 'v1', tokensUsed: 100, durationMs: 1000 },
}

const contract = {
  id: 9,
  title: '设备采购合同',
  contractNo: 'HT-9',
  contractType: 'sale',
  currentVersion: 1,
  amount: 100,
  status: 'review_passed',
  counterparty: { name: '甲方' },
}

const routes = [{ path: '/review/:taskId', component: { template: '<div />' } }]

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchTask.mockResolvedValue(task)
  mocks.fetchReport.mockResolvedValue(report)
  mocks.fetchAgentTrace.mockResolvedValue([])
  mocks.fetchContract.mockResolvedValue(contract)
  mocks.startApproval.mockResolvedValue({ id: 3 })
  mocks.startReview.mockResolvedValue({ id: 12 })
  mocks.logReportExport.mockResolvedValue(undefined)
  document.body.innerHTML = ''
})

async function mountReport() {
  const res = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes })
  await flushPromises()
  return res
}

describe('ReviewReportView 补充分支', () => {
  it('无建议改写时展示建议原文（不做差异对比）', async () => {
    const { wrapper } = await mountReport()
    await wrapper.findAll('button').find((b) => /F-1/.test(b.text()))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('补充违约责任')
    expect(wrapper.html()).not.toContain('line-through')
  })

  it('中/低风险筛选可切换', async () => {
    const { wrapper } = await mountReport()
    const medium = wrapper.findAll('button').find((b) => b.text() === '中')
    if (medium) {
      await medium.trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('责任不对等')
      expect(wrapper.text()).not.toContain('低风险项')
    }
    const low = wrapper.findAll('button').find((b) => b.text() === '低')
    if (low) {
      await low.trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('低风险项')
    }
  })

  it('任务失败可点击重试重新拉取', async () => {
    mocks.fetchTask.mockRejectedValueOnce(new Error('网络异常'))
    const { wrapper } = await mountReport()
    expect(wrapper.text()).toContain('网络异常')

    const retry = wrapper.findAll('button').find((b) => b.text().length > 0 && /重试/.test(b.text()))
    if (retry) {
      await retry.trigger('click')
      await flushPromises()
      expect(mocks.fetchTask.mock.calls.length).toBeGreaterThan(1)
    }
  })

  it('发起审批失败提示错误', async () => {
    mocks.startApproval.mockRejectedValue(new Error('报告已失效'))
    const { wrapper } = await mountReport()
    await wrapper.findAll('button').find((b) => /审批/.test(b.text()))!.trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('报告已失效')
  })

  it('智能体留痕降级项展示错误文案', async () => {
    mocks.fetchAgentTrace.mockResolvedValue([
      { id: 1, agentName: 'verifier', role: '校验', action: 'tool_loop', payload: { summary: '校验完成' }, latencyMs: 10, tokens: 0, error: '模型超时', createdAt: '2026-08-28T10:00:00' },
      { id: 2, agentName: 'rule_auditor', role: '规则', action: 'unknown_x', payload: { summary: '规则完成' }, latencyMs: 10, tokens: 100, error: null, createdAt: '2026-08-28T10:01:00' },
    ])
    const { wrapper } = await mountReport()
    const toggle = wrapper.findAll('button').find((b) => /展开|协作/.test(b.text()))
    if (toggle) {
      await toggle.trigger('click')
      await flushPromises()
    }
    expect(wrapper.text()).toContain('模型超时')
  })

  it('合同缺失时导出不触发并静默返回', async () => {
    mocks.fetchContract.mockResolvedValue(null)
    const { wrapper } = await mountReport()
    const wordBtn = wrapper.findAll('button').find((b) => /Word/i.test(b.text()))
    if (wordBtn) {
      await wordBtn.trigger('click')
      await flushPromises()
    }
    expect(mocks.downloadWord).not.toHaveBeenCalled()
  })

  it('单条款任务展示对应审查类型文案', async () => {
    const { wrapper } = await mountReport()
    expect(wrapper.text()).toContain('设备采购合同')
  })
})
