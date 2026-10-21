import type { ContractStatus, ContractType, RiskLevel, ReviewTaskStatus, WorkflowStatus } from '@/types'
import { i18n } from '@/i18n'

/** Date-time formatting: 2026-08-28 14:30 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Date formatting: 2026-08-28 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  return formatDateTime(iso).slice(0, 10)
}

/** Relative time: "3 hours ago" / "2 days ago" (i18n-friendly, picks wording by the active language at render time) */
export function fromNow(iso: string): string {
  const t = i18n.global.t
  const diff = Date.now() - new Date(iso).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return t('time.justNow')
  if (minutes < 60) return t('time.minutesAgo', { n: minutes })
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return t('time.hoursAgo', { n: hours })
  const days = Math.floor(hours / 24)
  if (days < 30) return t('time.daysAgo', { n: days })
  return formatDate(iso)
}

/** Amount formatting: uses the currency symbol and locale format for the active language */
export function formatAmount(amount: number): string {
  const isEn = i18n.global.locale.value === 'en-US'
  const symbol = isEn ? '$' : '¥'
  return `${symbol}${amount.toLocaleString(isEn ? 'en-US' : 'zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** Mask a phone number: 138****5678 */
export function maskPhone(phone: string): string {
  if (phone.length !== 11) return phone
  return `${phone.slice(0, 3)}****${phone.slice(7)}`
}

/** Mask an ID number: keep the first 3 and last 2 characters */
export function maskIdNo(idNo: string): string {
  if (idNo.length < 8) return idNo
  return `${idNo.slice(0, 3)}${'*'.repeat(idNo.length - 5)}${idNo.slice(-2)}`
}

/** Duration formatting: 41.2s / 2m05s */
export function formatDuration(ms: number | null): string {
  if (ms == null) return '-'
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const rest = Math.round(s % 60)
  return `${m}m${String(rest).padStart(2, '0')}s`
}

/** Compliance score (3.2.8): 100 - 40xhigh - 15xmedium - 5xlow, floor 0 */
export function calcScore(high: number, medium: number, low: number): number {
  return Math.max(0, 100 - 40 * high - 15 * medium - 5 * low)
}

/** Approval-start threshold (aligned with the backend approval_gate): score met, no blocking items, zero missed clauses, full-text review, report not stale */
export function canStartApproval(summary: {
  score: number
  blockingHigh: number
  failedClauses?: number
  needsReReview?: boolean
  taskType?: string
}): boolean {
  return summary.score >= 85
    && summary.blockingHigh === 0
    && (summary.failedClauses ?? 0) === 0
    && (summary.needsReReview ?? false) === false
    && (summary.taskType ?? 'full') === 'full'
}

// ===================== Status mappings (i18n-friendly) =====================
// A Proxy resolves the label lazily: translation happens at render/compute time
// using the active locale, so switching language updates automatically.
// Call-site API is unchanged (e.g. contractTypeLabels[type], contractStatusLabels[value].label).

function labelMap<K extends string = string>(prefix: string): Record<K, string> {
  return new Proxy({} as Record<K, string>, {
    get(_t, key: string | symbol) {
      if (typeof key !== 'string') return undefined as never
      return i18n.global.t(`${prefix}.${key}`)
    },
  }) as Record<K, string>
}

function statusMap<K extends string = string>(
  prefix: string,
  colors: Record<string, string>,
): Record<K, { label: string; color: string }> {
  return new Proxy({} as Record<K, { label: string; color: string }>, {
    get(_t, key: string | symbol) {
      if (typeof key !== 'string') return undefined as never
      return { label: i18n.global.t(`${prefix}.${key}`), color: colors[key] ?? 'slate' }
    },
  }) as Record<K, { label: string; color: string }>
}

export const contractTypeLabels: Record<ContractType, string> = labelMap<ContractType>('status.contractType')

export const contractStatusLabels: Record<ContractStatus, { label: string; color: string }> = statusMap<ContractStatus>('status.contract', {
  draft: 'slate',
  parsing: 'info',
  parsed: 'primary',
  parse_failed: 'danger',
  under_review: 'warn',
  review_passed: 'success',
  review_blocked: 'danger',
  in_approval: 'warn',
  approved: 'success',
  rejected: 'danger',
  archived: 'slate',
})

export const riskLevelLabels: Record<RiskLevel, { label: string; color: string }> = statusMap<RiskLevel>('status.risk', {
  high: 'danger',
  medium: 'warn',
  low: 'info',
})

export const taskStatusLabels: Record<ReviewTaskStatus, { label: string; color: string }> = statusMap<ReviewTaskStatus>('status.task', {
  pending: 'info',
  running: 'warn',
  completed: 'success',
  failed: 'danger',
})

export const workflowStatusLabels: Record<WorkflowStatus, { label: string; color: string }> = statusMap<WorkflowStatus>('status.workflow', {
  running: 'warn',
  approved: 'success',
  rejected: 'danger',
  withdrawn: 'slate',
})

export const findingStatusLabels: Record<string, string> = labelMap('status.finding')

export const approvalActionLabels: Record<string, string> = labelMap('status.approval')
