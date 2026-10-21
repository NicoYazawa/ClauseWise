import type { Contract, ReviewReport, ReviewTask, RiskFinding } from '@/types'
import { contractTypeLabels, formatAmount, formatDateTime } from '@/utils/format'

const levelLabels: Record<RiskFinding['riskLevel'], string> = { high: '高风险', medium: '中风险', low: '低风险' }
// Share the frontend status colors: negative / warning / neutral (low risk is not colored, to avoid all three lighting up)
const levelColors: Record<RiskFinding['riskLevel'], string> = { high: '#c4242a', medium: '#b45309', low: '#6b7280' }
const sourceLabels: Record<RiskFinding['source'], string> = { rule: '规则引擎', llm: '大模型 RAG' }

function esc(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** Assemble the review-report HTML (inline styles, reused for Word export and PDF print); structure aligned with design doc 3.2.8 */
export function buildReportHtml(report: ReviewReport, contract: Contract, task: ReviewTask): string {
  const rows = report.findings
    .map(
      (f) => `
      <tr>
        <td style="padding:8px 10px;border:1px solid #e2e8f0;font-family:Consolas,monospace;font-size:12px;">F-${f.id}</td>
        <td style="padding:8px 10px;border:1px solid #e2e8f0;white-space:nowrap;"><b style="color:${levelColors[f.riskLevel]}">${levelLabels[f.riskLevel]}</b></td>
        <td style="padding:8px 10px;border:1px solid #e2e8f0;font-size:13px;">${esc(f.riskType)}</td>
        <td style="padding:8px 10px;border:1px solid #e2e8f0;font-size:13px;">${esc(f.clauseNo)}</td>
        <td style="padding:8px 10px;border:1px solid #e2e8f0;font-size:13px;line-height:1.7;">
          <p style="margin:0 0 6px;"><b>风险描述：</b>${esc(f.issue)}</p>
          <p style="margin:0 0 6px;"><b>原文摘录：</b>${esc(f.originalText)}</p>
          <p style="margin:0 0 6px;"><b>依据：</b>${esc(f.legalBasis)}</p>
          <p style="margin:0;"><b>修改建议：</b>${esc(f.suggestion)}</p>
        </td>
        <td style="padding:8px 10px;border:1px solid #e2e8f0;font-size:12px;white-space:nowrap;">${sourceLabels[f.source]}</td>
      </tr>`,
    )
    .join('')

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>审查报告 - ${esc(contract.title)}</title>
<style>
  @media print { body { padding: 0; } }
</style>
</head>
<body style="font-family:'Microsoft YaHei','PingFang SC',sans-serif;color:#334155;max-width:860px;margin:0 auto;padding:32px 24px;">
  <div style="border-bottom:3px solid #0f766e;padding-bottom:14px;margin-bottom:20px;">
    <p style="margin:0;font-size:12px;color:#0f766e;font-weight:bold;letter-spacing:2px;">智审条款 · AI 智能合同合规审查平台</p>
    <h1 style="margin:8px 0 4px;font-size:22px;color:#0f172a;">合同合规审查报告</h1>
    <p style="margin:0;font-size:13px;color:#64748b;">报告编号 #${report.id} · 任务 #${task.id} · 生成于 ${formatDateTime(report.createdAt)}</p>
  </div>

  <h2 style="font-size:15px;color:#0f766e;margin:18px 0 8px;">一、合同信息</h2>
  <table style="width:100%;border-collapse:collapse;font-size:13px;">
    <tr>
      <td style="padding:6px 10px;border:1px solid #e2e8f0;width:90px;background:#f8fafc;">合同标题</td>
      <td style="padding:6px 10px;border:1px solid #e2e8f0;">${esc(contract.title)}</td>
      <td style="padding:6px 10px;border:1px solid #e2e8f0;width:90px;background:#f8fafc;">合同编号</td>
      <td style="padding:6px 10px;border:1px solid #e2e8f0;font-family:Consolas,monospace;">${esc(contract.contractNo)}</td>
    </tr>
    <tr>
      <td style="padding:6px 10px;border:1px solid #e2e8f0;background:#f8fafc;">合同类型</td>
      <td style="padding:6px 10px;border:1px solid #e2e8f0;">${contractTypeLabels[contract.contractType]}</td>
      <td style="padding:6px 10px;border:1px solid #e2e8f0;background:#f8fafc;">合同金额</td>
      <td style="padding:6px 10px;border:1px solid #e2e8f0;">${contract.amount > 0 ? formatAmount(contract.amount) : '—'}</td>
    </tr>
    <tr>
      <td style="padding:6px 10px;border:1px solid #e2e8f0;background:#f8fafc;">相对方</td>
      <td style="padding:6px 10px;border:1px solid #e2e8f0;">${esc(contract.counterparty.name)}</td>
      <td style="padding:6px 10px;border:1px solid #e2e8f0;background:#f8fafc;">审查类型</td>
      <td style="padding:6px 10px;border:1px solid #e2e8f0;">${task.taskType === 'full' ? '全文审查' : task.taskType === 'clause' ? '单条款审查' : '增量审查'}</td>
    </tr>
  </table>

  <h2 style="font-size:15px;color:#0f766e;margin:18px 0 8px;">二、审查结论</h2>
  <table style="width:100%;border-collapse:collapse;font-size:13px;text-align:center;">
    <tr>
      <td style="padding:10px;border:1px solid #e2e8f0;width:25%;"><p style="margin:0;font-size:26px;font-weight:bold;color:#0f766e;">${report.summary.score}</p><p style="margin:4px 0 0;color:#64748b;">合规评分</p></td>
      <td style="padding:10px;border:1px solid #e2e8f0;"><p style="margin:0;font-size:26px;font-weight:bold;color:${levelColors.high};">${report.summary.high}</p><p style="margin:4px 0 0;color:#64748b;">高风险（阻断）</p></td>
      <td style="padding:10px;border:1px solid #e2e8f0;"><p style="margin:0;font-size:26px;font-weight:bold;color:${levelColors.medium};">${report.summary.medium}</p><p style="margin:4px 0 0;color:#64748b;">中风险（重点复核）</p></td>
      <td style="padding:10px;border:1px solid #e2e8f0;"><p style="margin:0;font-size:26px;font-weight:bold;color:${levelColors.low};">${report.summary.low}</p><p style="margin:4px 0 0;color:#64748b;">低风险（参考建议）</p></td>
    </tr>
  </table>
  <div style="margin-top:10px;padding:10px 14px;border:1px solid #e2e8f0;background:#f8fafc;border-radius:4px;font-size:13px;line-height:1.8;">
    <b>整体审查意见：</b>${esc(report.overallOpinion)}
  </div>

  <h2 style="font-size:15px;color:#0f766e;margin:18px 0 8px;">三、风险发现清单（${report.findings.length} 项）</h2>
  <table style="width:100%;border-collapse:collapse;font-size:13px;">
    <thead>
      <tr style="background:#f1f5f9;">
        <th style="padding:8px 10px;border:1px solid #e2e8f0;font-size:12px;">编号</th>
        <th style="padding:8px 10px;border:1px solid #e2e8f0;font-size:12px;">等级</th>
        <th style="padding:8px 10px;border:1px solid #e2e8f0;font-size:12px;">风险类型</th>
        <th style="padding:8px 10px;border:1px solid #e2e8f0;font-size:12px;">条款定位</th>
        <th style="padding:8px 10px;border:1px solid #e2e8f0;font-size:12px;text-align:left;">风险详情与修改建议</th>
        <th style="padding:8px 10px;border:1px solid #e2e8f0;font-size:12px;">来源</th>
      </tr>
    </thead>
    <tbody>${rows || '<tr><td colspan="6" style="padding:20px;text-align:center;border:1px solid #e2e8f0;color:#94a3b8;">未发现风险</td></tr>'}</tbody>
  </table>

  <h2 style="font-size:15px;color:#0f766e;margin:18px 0 8px;">四、审查溯源信息</h2>
  <p style="font-size:12px;color:#64748b;line-height:1.9;margin:0;">
    审查模型：${esc(report.meta.model)} · Prompt 版本：${esc(report.meta.promptVersion)} · Token 消耗：${report.meta.tokensUsed.toLocaleString()} ·
    审查耗时：${(report.meta.durationMs / 1000).toFixed(1)}s<br/>
    风险结论由规则引擎硬校验与 RAG 检索软校验（BM25 + kNN 混合检索，RRF 融合）双轨合并生成，每条结论均可溯源至知识库依据。
  </p>

  <p style="margin-top:28px;padding-top:12px;border-top:1px solid #e2e8f0;font-size:11px;color:#94a3b8;">
    本报告由 AI 生成，供合同合规审查参考；导出行为已写入审计日志（audit_log · review.export，保存 ≥ 3 年）。
  </p>
</body>
</html>`
}

/** Export as a Word document (HTML format, natively openable by Word / WPS) */
export function downloadWord(html: string, filename: string): void {
  const blob = new Blob(['\ufeff', html], { type: 'application/msword;charset=utf-8' })
  triggerDownload(blob, filename)
}

/** Assemble a plain-text review report (.txt fallback format) */
export function downloadText(text: string, filename: string): void {
  const blob = new Blob(['\ufeff', text], { type: 'text/plain;charset=utf-8' })
  triggerDownload(blob, filename)
}

/** Hidden-iframe printing: the browser's "Save as PDF" produces a PDF (content is uniformly esc-escaped) */
export function printAsPdf(html: string): boolean {
  const frame = document.createElement('iframe')
  frame.setAttribute('aria-hidden', 'true')
  frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden'
  frame.srcdoc = html
  frame.addEventListener('load', () => {
    frame.contentWindow?.focus()
    frame.contentWindow?.print()
    setTimeout(() => frame.remove(), 60_000)
  })
  document.body.appendChild(frame)
  return true
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
