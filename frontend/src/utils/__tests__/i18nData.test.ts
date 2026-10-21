/**
 * Critical path: backend Chinese constants -> i18n key reverse-lookup (REVERSE_MAP).
 * Unmapped constants must fall back to showing the raw Chinese, never blank out or show the key.
 */
import { describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import { translateData } from '@/utils/i18nData'

describe('translateData 后端中文常量翻译', () => {
  it('收录的节点名按当前语言渲染', () => {
    i18n.global.locale.value = 'zh-CN'
    expect(translateData('部门经理审批')).toBe(i18n.global.t('data.node.deptManager'))
    expect(translateData('通过签署')).toBe(i18n.global.t('data.node.signEnd'))
  })

  it('收录的规则在 en-US 下同样生效', () => {
    i18n.global.locale.value = 'en-US'
    expect(translateData('法务加签')).toBe(i18n.global.t('data.node.legalCountersign'))
    i18n.global.locale.value = 'zh-CN'
  })

  it('未收录常量原样回退，不显示 key', () => {
    expect(translateData('自定义审批节点')).toBe('自定义审批节点')
    expect(translateData('')).toBe('')
    expect(translateData(null)).toBe('')
    expect(translateData(undefined)).toBe('')
  })

  it('收尾节点常量全部收录（后端 workflow_engine 固定写入）', () => {
    i18n.global.locale.value = 'en-US'
    for (const name of ['通过签署', '已否决', '结束', '条件判断', '抄送']) {
      const out = translateData(name)
      expect(out.startsWith('data.'), `${name} 的 i18n 词条缺失`).toBe(false)
      expect(out, `${name} 未收录`).not.toBe(name) // Under en-US it must be the translation, not the raw Chinese
    }
    i18n.global.locale.value = 'zh-CN'
  })
})
