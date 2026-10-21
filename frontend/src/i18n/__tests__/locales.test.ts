/**
 * Critical path: i18n bilingual entry sync (project convention: zh-CN / en-US key sets must match).
 * A missing key directly causes the UI to fall back to blank or show the key, which is a release blocker.
 */
import { describe, expect, it } from 'vitest'

import en from '@/i18n/locales/en-US'
import zh from '@/i18n/locales/zh-CN'

function flattenKeys(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return flattenKeys(value as Record<string, unknown>, path)
    }
    return [path]
  })
}

describe('i18n 双语键同步', () => {
  const zhKeys = new Set(flattenKeys(zh as Record<string, unknown>))
  const enKeys = new Set(flattenKeys(en as Record<string, unknown>))

  it('en-US 不缺 zh-CN 的键', () => {
    const missing = [...zhKeys].filter(k => !enKeys.has(k))
    expect(missing, `en-US 缺失键：${missing.join(', ')}`).toEqual([])
  })

  it('zh-CN 不缺 en-US 的键', () => {
    const extra = [...enKeys].filter(k => !zhKeys.has(k))
    expect(extra, `zh-CN 缺失键：${extra.join(', ')}`).toEqual([])
  })

  it('叶节点词条值非空', () => {
    const empties: string[] = []
    for (const dict of [zh as Record<string, unknown>, en as Record<string, unknown>]) {
      const walk = (node: Record<string, unknown>, prefix: string) => {
        for (const [key, value] of Object.entries(node)) {
          const path = prefix ? `${prefix}.${key}` : key
          if (value && typeof value === 'object' && !Array.isArray(value)) {
            walk(value as Record<string, unknown>, path)
          } else if (typeof value === 'string' && value.trim() === '') {
            empties.push(path)
          }
        }
      }
      walk(dict, '')
    }
    expect(empties).toEqual([])
  })
})
