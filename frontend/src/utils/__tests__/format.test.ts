/**
 * Critical path: the approval-start threshold (maps one-to-one to the eligibility conditions in backend app/services/approval_gate.py).
 * The frontend button is only a hint; it must not treat "missing-review / stale / partial report" as startable.
 */
import { describe, expect, it } from 'vitest'

import { calcScore, canStartApproval, maskIdNo, maskPhone } from '@/utils/format'

const clean = { score: 90, blockingHigh: 0, failedClauses: 0, needsReReview: false, taskType: 'full' }

describe('canStartApproval（审批资格前端镜像）', () => {
  it('完整、无漏审、当前内容的全文报告可发起', () => {
    expect(canStartApproval(clean)).toBe(true)
  })

  it('分数不达标不可发起', () => {
    expect(canStartApproval({ ...clean, score: 84 })).toBe(false)
    expect(canStartApproval({ ...clean, score: 85 })).toBe(true)
  })

  it('存在高风险阻断项不可发起', () => {
    expect(canStartApproval({ ...clean, blockingHigh: 1 })).toBe(false)
  })

  it('漏审条款（failedClauses>0）不可发起', () => {
    expect(canStartApproval({ ...clean, failedClauses: 1 })).toBe(false)
  })

  it('报告已标记需重新审查（内容/版本变化、历史报告）不可发起', () => {
    expect(canStartApproval({ ...clean, needsReReview: true })).toBe(false)
  })

  it('局部审查（clause/diff）报告不能授权整份合同审批', () => {
    expect(canStartApproval({ ...clean, taskType: 'clause' })).toBe(false)
    expect(canStartApproval({ ...clean, taskType: 'diff' })).toBe(false)
  })

  it('缺省字段按安全默认处理（缺 failedClauses 视为可、缺 needsReReview 视为否）', () => {
    expect(canStartApproval({ score: 90, blockingHigh: 0 })).toBe(true)
    expect(canStartApproval({ score: 90, blockingHigh: 0, needsReReview: undefined, taskType: undefined })).toBe(true)
  })
})

describe('calcScore 评分', () => {
  it('100 - 40H - 15M - 5L，下限 0', () => {
    expect(calcScore(0, 0, 0)).toBe(100)
    expect(calcScore(1, 1, 1)).toBe(40)
    expect(calcScore(3, 0, 0)).toBe(0)
    expect(calcScore(0, 0, 1)).toBe(95)
  })
})

describe('敏感信息脱敏', () => {
  it('手机号与证件号仅展示前缀', () => {
    expect(maskPhone('13812345678')).toBe('138****5678')
    expect(maskIdNo('91110100MA00X0Y0Z0')).toContain('*')
    expect(maskIdNo('91110100MA00X0Y0Z0')).not.toBe('91110100MA00X0Y0Z0')
  })
})
