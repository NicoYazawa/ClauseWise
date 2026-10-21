import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { buildReportHtml, downloadText, downloadWord, printAsPdf } from '@/utils/export'
import type { Contract, ReviewReport, ReviewTask, RiskFinding } from '@/types'

function finding(over: Partial<RiskFinding> = {}): RiskFinding {
  return {
    id: 1,
    riskLevel: 'high',
    riskType: '付款条件<异常>',
    clauseNo: '3.2',
    issue: '账期过长 & 风险',
    originalText: '原文"摘录"',
    legalBasis: '《民法典》第 509 条',
    suggestion: '建议缩短账期',
    source: 'rule',
    ...over,
  } as RiskFinding
}

function report(over: Partial<ReviewReport> = {}): ReviewReport {
  return {
    id: 88,
    createdAt: new Date(2026, 7, 28, 14, 30).toISOString(),
    findings: [finding()],
    summary: { score: 72, high: 1, medium: 2, low: 3 },
    overallOpinion: '存在高风险条款，建议修改后再签署',
    meta: { model: 'contract-review', promptVersion: 'v3', tokensUsed: 12345, durationMs: 4200 },
    ...over,
  } as unknown as ReviewReport
}

function contract(over: Partial<Contract> = {}): Contract {
  return {
    title: '设备采购合同',
    contractNo: 'HT-2026-001',
    contractType: 'sale',
    amount: 1234.5,
    counterparty: { name: '某某科技' },
    ...over,
  } as unknown as Contract
}

function task(over: Partial<ReviewTask> = {}): ReviewTask {
  return { id: 7, taskType: 'full', ...over } as unknown as ReviewTask
}

describe('buildReportHtml 报告 HTML 组装', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'zh-CN'
  })

  it('包含合同信息、结论、发现行与溯源信息', () => {
    const html = buildReportHtml(report(), contract(), task())
    expect(html).toContain('<title>审查报告 - 设备采购合同</title>')
    expect(html).toContain('HT-2026-001')
    expect(html).toContain('¥1,234.50')
    expect(html).toContain('F-1')
    expect(html).toContain('高风险')
    expect(html).toContain('规则引擎')
    expect(html).toContain('全文审查')
    expect(html).toContain('12,345')
    expect(html).toContain('4.2s')
  })

  it('HTML 特殊字符被转义', () => {
    const html = buildReportHtml(report(), contract(), task())
    expect(html).toContain('付款条件&lt;异常&gt;')
    expect(html).toContain('账期过长 &amp; 风险')
    expect(html).toContain('原文&quot;摘录&quot;')
    expect(html).not.toContain('<异常>')
  })

  it('无发现时展示空态行', () => {
    const html = buildReportHtml(report({ findings: [] }), contract(), task())
    expect(html).toContain('未发现风险')
    expect(html).toContain('（0 项）')
  })

  it('金额为 0 时显示破折号', () => {
    expect(buildReportHtml(report(), contract({ amount: 0 }), task())).toContain('—')
  })

  it('任务类型映射：单条款 / 增量审查', () => {
    expect(buildReportHtml(report(), contract(), task({ taskType: 'clause' }))).toContain('单条款审查')
    expect(buildReportHtml(report(), contract(), task({ taskType: 'diff' }))).toContain('增量审查')
  })

  it('大模型来源与中/低风险等级颜色', () => {
    const html = buildReportHtml(
      report({
        findings: [
          finding({ riskLevel: 'medium', source: 'llm' }),
          finding({ riskLevel: 'low', source: 'llm' }),
        ],
      }),
      contract(),
      task(),
    )
    expect(html).toContain('大模型 RAG')
    expect(html).toContain('#b45309')
    expect(html).toContain('#6b7280')
  })
})

describe('导出下载', () => {
  const createObjectURL = vi.fn(() => 'blob:mock')
  const revokeObjectURL = vi.fn()

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  function stubUrl() {
    Object.defineProperty(URL, 'createObjectURL', { value: createObjectURL, configurable: true, writable: true })
    Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURL, configurable: true, writable: true })
  }

  function stubAnchor() {
    const anchor = { href: '', download: '', click: vi.fn(), remove: vi.fn() }
    vi.spyOn(document, 'createElement').mockReturnValue(anchor as unknown as HTMLElement)
    vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n)
    vi.spyOn(document.body, 'removeChild').mockImplementation((n) => n)
    return anchor
  }

  it('downloadWord 触发浏览器保存并清理 URL', () => {
    stubUrl()
    const anchor = stubAnchor()
    downloadWord('<html/>', 'report.doc')
    expect(createObjectURL).toHaveBeenCalled()
    expect(anchor.download).toBe('report.doc')
    expect(anchor.click).toHaveBeenCalled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock')
  })

  it('downloadText 触发浏览器保存', () => {
    stubUrl()
    const anchor = stubAnchor()
    downloadText('纯文本', 'report.txt')
    expect(anchor.click).toHaveBeenCalled()
    expect(anchor.download).toBe('report.txt')
  })

  it('printAsPdf 注入隐藏 iframe 并返回 true', () => {
    const focus = vi.fn()
    const print = vi.fn()
    const frame = {
      setAttribute: vi.fn(),
      style: {} as CSSStyleDeclaration,
      srcdoc: '',
      addEventListener: vi.fn((_evt: string, cb: () => void) => cb()),
      contentWindow: { focus, print },
      remove: vi.fn(),
      parentNode: document.body,
    }
    vi.spyOn(document, 'createElement').mockReturnValue(frame as unknown as HTMLElement)
    vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n)
    vi.useFakeTimers()
    expect(printAsPdf('<html/>')).toBe(true)
    expect(frame.setAttribute).toHaveBeenCalledWith('aria-hidden', 'true')
    expect(print).toHaveBeenCalled()
    vi.advanceTimersByTime(60_000)
    expect(frame.remove).toHaveBeenCalled()
    vi.useRealTimers()
  })
})
