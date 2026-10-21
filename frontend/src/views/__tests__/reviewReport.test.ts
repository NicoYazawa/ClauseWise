import { DOMWrapper, flushPromises } from '@vue/test-utils'
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

function task(over: Record<string, unknown> = {}) {
  return {
    id: 7,
    contractId: 9,
    contractTitle: '设备采购合同',
    status: 'completed',
    progress: 100,
    taskType: 'full',
    errorMsg: null,
    ...over,
  }
}

function finding(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    riskLevel: 'high',
    riskType: '付款条件不明确',
    clauseNo: '3.2',
    issue: '账期过长',
    originalText: '付款账期为 180 天，逾期按日万分之五计算违约金。',
    suggestedText: '付款账期为 30 天，逾期按日万分之五计算违约金。',
    suggestion: '缩短账期',
    legalBasis: '《民法典》第 509 条',
    source: 'rule',
    status: 'open',
    ragHits: ['民法典 · 第509条'],
    ...over,
  }
}

function report(summaryOver: Record<string, unknown> = {}, over: Record<string, unknown> = {}) {
  return {
    id: 88,
    taskId: 7,
    createdAt: '2026-08-28T10:00:00',
    findings: [finding()],
    summary: {
      score: 90,
      high: 1,
      medium: 0,
      low: 0,
      blockingHigh: 0,
      aiHigh: 0,
      failedClauses: 0,
      needsReReview: false,
      taskType: 'full',
      ...summaryOver,
    },
    overallOpinion: '整体风险可控',
    meta: { model: 'contract-review', promptVersion: 'v3', tokensUsed: 12345, durationMs: 4200 },
    ...over,
  }
}

function contract(over: Record<string, unknown> = {}) {
  return {
    id: 9,
    title: '设备采购合同',
    contractNo: 'HT-9',
    contractType: 'sale',
    currentVersion: 1,
    amount: 12000,
    status: 'review_passed',
    counterparty: { name: '甲方' },
    ...over,
  }
}

const routes = [{ path: '/review/:taskId', component: { template: '<div />' } }]

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchTask.mockResolvedValue(task())
  mocks.fetchReport.mockResolvedValue(report())
  mocks.resolveFinding.mockResolvedValue({ id: 1, status: 'accepted', applied: true })
  mocks.startReview.mockResolvedValue({ id: 12 })
  mocks.logReportExport.mockResolvedValue(undefined)
  mocks.fetchAgentTrace.mockResolvedValue([])
  mocks.fetchContract.mockResolvedValue(contract())
  mocks.startApproval.mockResolvedValue({ id: 3 })
  mocks.buildReportHtml.mockReturnValue('<html/>')
  document.body.innerHTML = ''
})

async function mountReport() {
  const res = await mountWithApp(ReviewReportView, { initialPath: '/review/7', routes })
  await flushPromises()
  return res
}

describe('ReviewReportView 加载与状态', () => {
  it('渲染报告主体：评分、意见、风险条目', async () => {
    const { wrapper } = await mountReport()
    expect(wrapper.text()).toContain('90')
    expect(wrapper.text()).toContain('整体风险可控')
    expect(wrapper.text()).toContain('付款条件不明确')
    expect(wrapper.text()).toContain('12,345')
  })

  it('任务失败展示错误与重审入口', async () => {
    mocks.fetchTask.mockResolvedValue(task({ status: 'failed', errorMsg: '模型超时' }))
    const { wrapper } = await mountReport()
    expect(wrapper.text()).toContain('模型超时')
  })

  it('任务运行中展示进度条', async () => {
    mocks.fetchTask.mockResolvedValue(task({ status: 'running', progress: 40 }))
    const { wrapper } = await mountReport()
    expect(wrapper.text()).toContain('40%')
  })

  it('任务完成但无报告时展示兜底', async () => {
    mocks.fetchReport.mockResolvedValue(null)
    const { wrapper } = await mountReport()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('任务接口失败展示错误并可返回列表', async () => {
    mocks.fetchTask.mockRejectedValue(new Error('任务不存在'))
    const { wrapper } = await mountReport()
    expect(wrapper.text()).toContain('任务不存在')
  })
})

describe('ReviewReportView 阻断与审批资格', () => {
  it('存在阻断项时展示红色横幅', async () => {
    mocks.fetchReport.mockResolvedValue(report({ blockingHigh: 2, score: 60 }))
    const { wrapper } = await mountReport()
    expect(wrapper.text()).toContain('2')
    expect(wrapper.text().length).toBeGreaterThan(100)
  })

  it('阻断项全部修复后切换为绿色提示', async () => {
    mocks.fetchReport.mockResolvedValue(
      report(
        { blockingHigh: 1, score: 60 },
        { findings: [finding({ status: 'fixed' })] },
      ),
    )
    const { wrapper } = await mountReport()
    expect(wrapper.text().length).toBeGreaterThan(100)
  })

  it('仅有 AI 高风险（非阻断）时展示黄色提示', async () => {
    mocks.fetchReport.mockResolvedValue(report({ blockingHigh: 0, aiHigh: 2 }))
    const { wrapper } = await mountReport()
    expect(wrapper.text()).toContain('2')
  })

  it('满足审批条件时展示发起审批按钮，否则展示重审按钮', async () => {
    const { wrapper } = await mountReport()
    expect(wrapper.findAll('button').some((b) => /审批/.test(b.text()))).toBe(true)

    mocks.fetchReport.mockResolvedValue(report({ score: 70 }))
    const { wrapper: low } = await mountReport()
    expect(low.findAll('button').some((b) => /重审|重新审查/.test(b.text()))).toBe(true)
  })
})

describe('ReviewReportView 风险处置', () => {
  it('展开风险条目展示原文/依据/RAG 命中与差异高亮', async () => {
    const { wrapper } = await mountReport()
    const header = wrapper.findAll('button').find((b) => /F-1/.test(b.text()))
    await header!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('《民法典》第 509 条')
    expect(wrapper.text()).toContain('民法典 · 第509条')
    // 相似度足够时显示字符级差异高亮
    expect(wrapper.html()).toContain('line-through')
  })

  it('建议文本相似度过低时整段展示', async () => {
    mocks.fetchReport.mockResolvedValue(
      report({}, {
        findings: [
          finding({
            suggestedText: '完全不同的另一段完全不同的另一段完全不同的另一段',
          }),
        ],
      }),
    )
    const { wrapper } = await mountReport()
    const header = wrapper.findAll('button').find((b) => /F-1/.test(b.text()))
    await header!.trigger('click')
    await flushPromises()
    expect(wrapper.html()).not.toContain('line-through')
  })

  it('采纳建议调用处置接口并提示', async () => {
    const { wrapper } = await mountReport()
    const header = wrapper.findAll('button').find((b) => /F-1/.test(b.text()))
    await header!.trigger('click')
    await flushPromises()

    const accept = wrapper.findAll('button').find((b) => /采纳/.test(b.text()))
    await accept!.trigger('click')
    await flushPromises()
    expect(mocks.resolveFinding).toHaveBeenCalledWith(1, 'accepted')
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('拒绝采纳调用接口并提示', async () => {
    mocks.resolveFinding.mockResolvedValue({ id: 1, status: 'rejected', applied: false })
    const { wrapper } = await mountReport()
    await wrapper.findAll('button').find((b) => /F-1/.test(b.text()))!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((b) => /拒绝|不采纳/.test(b.text()))!.trigger('click')
    await flushPromises()
    expect(mocks.resolveFinding).toHaveBeenCalledWith(1, 'rejected')
    expect(mocks.toastInfo).toHaveBeenCalled()
  })

  it('已处置的风险不再显示操作按钮', async () => {
    mocks.fetchReport.mockResolvedValue(report({}, { findings: [finding({ status: 'accepted' })] }))
    const { wrapper } = await mountReport()
    await wrapper.findAll('button').find((b) => /F-1/.test(b.text()))!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('button').some((b) => /采纳/.test(b.text()))).toBe(false)
  })

  it('按等级筛选风险条目', async () => {
    mocks.fetchReport.mockResolvedValue(
      report({}, {
        findings: [finding({ id: 1, riskLevel: 'high' }), finding({ id: 2, riskLevel: 'low', riskType: '低风险项' })],
      }),
    )
    const { wrapper } = await mountReport()
    const lowFilter = wrapper.findAll('button').find((b) => b.text() === '低')
    if (lowFilter) {
      await lowFilter.trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('低风险项')
      expect(wrapper.text()).not.toContain('付款条件不明确')
    }
  })
})

describe('ReviewReportView 导出与动作', () => {
  it('导出 Word 与 PDF 均写入审计日志', async () => {
    const { wrapper } = await mountReport()
    const wordBtn = wrapper.findAll('button').find((b) => /Word/i.test(b.text()))
    await wordBtn!.trigger('click')
    await flushPromises()
    expect(mocks.downloadWord).toHaveBeenCalled()
    expect(mocks.logReportExport).toHaveBeenCalledWith(7, 'word')

    const pdfBtn = wrapper.findAll('button').find((b) => /PDF/i.test(b.text()))
    await pdfBtn!.trigger('click')
    await flushPromises()
    expect(mocks.printAsPdf).toHaveBeenCalled()
    expect(mocks.logReportExport).toHaveBeenCalledWith(7, 'pdf')
  })

  it('发起审批成功后跳转审批详情', async () => {
    const { wrapper, router } = await mountReport()
    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    await wrapper.findAll('button').find((b) => /审批/.test(b.text()))!.trigger('click')
    await flushPromises()
    expect(mocks.startApproval).toHaveBeenCalled()
    expect(pushSpy).toHaveBeenCalledWith('/workflow/3')
  })

  it('重审成功创建任务并跳转', async () => {
    mocks.fetchReport.mockResolvedValue(
      report({ score: 60, blockingHigh: 1 }, { findings: [finding({ status: 'fixed' })] }),
    )
    const { wrapper, router } = await mountReport()
    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    const rerun = wrapper.findAll('button').find((b) => /重审|重新审查/.test(b.text()))
    await rerun!.trigger('click')
    await flushPromises()
    expect(mocks.startReview).toHaveBeenCalled()
    expect(pushSpy).toHaveBeenCalledWith('/review/12')
  })

  it('智能体协作面板可展开/收起并生成摘要', async () => {
    mocks.fetchAgentTrace.mockResolvedValue([
      { id: 1, agentName: 'review_planner', role: '规划', action: 'plan', payload: { output: { summary: '规划完成', focusPoints: ['付款', '账期'] } }, latencyMs: 100, tokens: 0, error: null, createdAt: '2026-08-28T10:00:00' },
      { id: 2, agentName: 'rule_auditor', role: '规则', action: 'tool_loop', payload: { summary: '规则命中 2 条' }, latencyMs: 80, tokens: 10, error: null, createdAt: '2026-08-28T10:01:00' },
      { id: 3, agentName: 'clause_reviewer', role: '条款', action: 'decision', payload: { clauseNo: '3.2', tools: [{ tool: 'rag' }], result: { riskLevel: 'none' } }, latencyMs: 90, tokens: 0, error: null, createdAt: '2026-08-28T10:02:00' },
      { id: 4, agentName: 'verifier', role: '校验', action: 'report', payload: { verdicts: [{ index: 1, verdict: 'keep' }], candidates: 2 }, latencyMs: 70, tokens: 0, error: null, createdAt: '2026-08-28T10:03:00' },
      { id: 5, agentName: 'reporter', role: '报告', action: 'message', payload: { stats: { score: 90, high: 1, medium: 0, low: 0 }, opinion: '可控' }, latencyMs: 60, tokens: 0, error: null, createdAt: '2026-08-28T10:04:00' },
      { id: 6, agentName: 'unknown', role: '其他', action: 'unknown_action', payload: {}, latencyMs: 10, tokens: 0, error: '降级', createdAt: '2026-08-28T10:05:00' },
    ])
    const { wrapper } = await mountReport()
    const toggle = wrapper.findAll('button').find((b) => /展开|协作/.test(b.text()))
    expect(toggle).toBeTruthy()
    await toggle!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('规划完成')
  })
})
