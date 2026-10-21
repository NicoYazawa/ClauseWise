import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import {
  approvalActionLabels,
  contractStatusLabels,
  contractTypeLabels,
  findingStatusLabels,
  formatAmount,
  formatDate,
  formatDateTime,
  formatDuration,
  fromNow,
  maskIdNo,
  maskPhone,
  riskLevelLabels,
  taskStatusLabels,
  workflowStatusLabels,
} from '@/utils/format'

afterEach(() => {
  i18n.global.locale.value = 'zh-CN'
  vi.useRealTimers()
})

describe('日期与时间格式化', () => {
  it('空值返回占位符', () => {
    expect(formatDateTime(null)).toBe('-')
    expect(formatDateTime(undefined)).toBe('-')
    expect(formatDate(null)).toBe('-')
    expect(formatDate(undefined)).toBe('-')
  })

  it('格式化为 YYYY-MM-DD HH:mm', () => {
    const iso = new Date(2026, 7, 28, 14, 30).toISOString()
    expect(formatDateTime(iso)).toBe('2026-08-28 14:30')
    expect(formatDate(iso)).toBe('2026-08-28')
  })

  it('单数字月份/日期补零', () => {
    const iso = new Date(2026, 0, 5, 9, 7).toISOString()
    expect(formatDateTime(iso)).toBe('2026-01-05 09:07')
  })
})

describe('fromNow 相对时间（四种粒度）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-28T12:00:00'))
  })

  it('1 分钟内显示「刚刚」', () => {
    expect(fromNow(new Date('2026-08-28T11:59:30').toISOString())).toBe(i18n.global.t('time.justNow'))
  })

  it('1 小时内按分钟', () => {
    expect(fromNow(new Date('2026-08-28T11:55:00').toISOString())).toBe(
      i18n.global.t('time.minutesAgo', { n: 5 }),
    )
  })

  it('24 小时内按小时', () => {
    expect(fromNow(new Date('2026-08-28T10:00:00').toISOString())).toBe(
      i18n.global.t('time.hoursAgo', { n: 2 }),
    )
  })

  it('30 天内按天', () => {
    expect(fromNow(new Date('2026-08-25T12:00:00').toISOString())).toBe(
      i18n.global.t('time.daysAgo', { n: 3 }),
    )
  })

  it('超过 30 天回退为日期', () => {
    expect(fromNow(new Date('2026-06-01T12:00:00').toISOString())).toBe('2026-06-01')
  })
})

describe('金额格式化（中英双币种）', () => {
  it('中文环境使用 ¥ 与千分位', () => {
    expect(formatAmount(1234.5)).toBe('¥1,234.50')
  })

  it('英文环境使用 $', () => {
    i18n.global.locale.value = 'en-US'
    expect(formatAmount(1234.5)).toBe('$1,234.50')
    expect(formatAmount(0)).toBe('$0.00')
  })
})

describe('脱敏', () => {
  it('11 位手机号中间打码，其他原样返回', () => {
    expect(maskPhone('13812345678')).toBe('138****5678')
    expect(maskPhone('12345')).toBe('12345')
    expect(maskPhone('')).toBe('')
  })

  it('8 位及以上证件号保留前三后二，短号原样返回', () => {
    expect(maskIdNo('91110100MA00X0Y0Z0')).toBe('911' + '*'.repeat(13) + 'Z0')
    expect(maskIdNo('1234567')).toBe('1234567')
  })
})

describe('耗时格式化', () => {
  it('空值返回占位符', () => {
    expect(formatDuration(null)).toBe('-')
  })

  it('不足 1 分钟按秒', () => {
    expect(formatDuration(41200)).toBe('41.2s')
    expect(formatDuration(0)).toBe('0.0s')
  })

  it('超过 1 分钟为 NmSSs（秒补零）', () => {
    expect(formatDuration(125000)).toBe('2m05s')
    expect(formatDuration(600000)).toBe('10m00s')
  })
})

describe('状态映射 Proxy（懒翻译）', () => {
  it('合同类型按 i18n key 翻译', () => {
    expect(contractTypeLabels.sale).toBe(i18n.global.t('status.contractType.sale'))
  })

  it('合同状态返回 label + color', () => {
    expect(contractStatusLabels.draft).toEqual({ label: i18n.global.t('status.contract.draft'), color: 'slate' })
    expect(contractStatusLabels.approved.color).toBe('success')
  })

  it('未知 key 的颜色回退为 slate', () => {
    expect((contractStatusLabels as Record<string, { color: string }>).unknownState.color).toBe('slate')
    expect((riskLevelLabels as Record<string, { color: string }>).unknownLevel.color).toBe('slate')
  })

  it('非字符串属性访问返回 undefined（Symbol 分支）', () => {
    expect((contractStatusLabels as unknown as Record<symbol, unknown>)[Symbol('x')]).toBeUndefined()
    expect((contractTypeLabels as unknown as Record<symbol, unknown>)[Symbol('x')]).toBeUndefined()
  })

  it('其余状态表均可读取', () => {
    expect(riskLevelLabels.high.color).toBe('danger')
    expect(taskStatusLabels.completed.color).toBe('success')
    expect(workflowStatusLabels.withdrawn.color).toBe('slate')
    expect(findingStatusLabels.open).toBe(i18n.global.t('status.finding.open'))
    expect(approvalActionLabels.approve).toBe(i18n.global.t('status.approval.approve'))
  })
})
