import { describe, expect, it } from 'vitest'

import { diffText, similarity } from '@/utils/diff'

describe('diffText 字符级 LCS', () => {
  it('完全相同的文本返回 single same 段', () => {
    const r = diffText('合同条款', '合同条款')
    expect(r.left).toEqual([{ type: 'same', text: '合同条款' }])
    expect(r.right).toEqual([{ type: 'same', text: '合同条款' }])
  })

  it('空文本直接回退为整段展示', () => {
    const r = diffText('', '新增')
    expect(r.left).toEqual([{ type: 'same', text: '' }])
    expect(r.right).toEqual([{ type: 'same', text: '新增' }])
    expect(diffText('旧', '')).toEqual({
      left: [{ type: 'same', text: '旧' }],
      right: [{ type: 'same', text: '' }],
    })
  })

  it('超长文本回退（避免 LCS 计算开销）', () => {
    const long = 'a'.repeat(1501)
    const r = diffText(long, 'b')
    expect(r.left).toEqual([{ type: 'same', text: long }])
  })

  it('插入字符只在右侧出现 add 段', () => {
    const r = diffText('甲乙丙', '甲乙新丙')
    expect(r.left.every((s) => s.type !== 'add')).toBe(true)
    expect(r.right.some((s) => s.type === 'add')).toBe(true)
    expect(r.right.map((s) => s.text).join('')).toBe('甲乙新丙')
  })

  it('删除字符只在左侧出现 del 段', () => {
    const r = diffText('甲乙丙', '甲丙')
    expect(r.left.some((s) => s.type === 'del')).toBe(true)
    expect(r.left.map((s) => s.text).join('')).toBe('甲乙丙')
    expect(r.right.every((s) => s.type !== 'del')).toBe(true)
  })

  it('相邻同类型片段合并为一段', () => {
    const r = diffText('abc', 'aXbYc')
    const adds = r.right.filter((s) => s.type === 'add')
    expect(adds.length).toBeGreaterThan(0)
    // 每个 add 段都不为空
    expect(adds.every((s) => s.text.length > 0)).toBe(true)
  })

  it('尾部追加字符（while j < m 分支）', () => {
    const r = diffText('甲', '甲乙丙丁')
    expect(r.right.map((s) => s.text).join('')).toBe('甲乙丙丁')
  })

  it('尾部删除字符（while i < n 分支）', () => {
    const r = diffText('甲乙丙丁', '甲')
    expect(r.left.map((s) => s.text).join('')).toBe('甲乙丙丁')
  })

  it('完全不同的文本', () => {
    const r = diffText('AAA', 'BBB')
    expect(r.left.map((s) => s.text).join('')).toBe('AAA')
    expect(r.right.map((s) => s.text).join('')).toBe('BBB')
  })
})

describe('similarity 字符重合度', () => {
  it('双空视为完全相似', () => {
    expect(similarity('', '')).toBe(1)
  })

  it('完全一致为 1', () => {
    expect(similarity('合同', '合同')).toBe(1)
  })

  it('部分重合按比例计算', () => {
    expect(similarity('abcd', 'ab')).toBe(0.5)
  })

  it('无重合为 0', () => {
    expect(similarity('abc', 'xyz')).toBe(0)
  })

  it('一侧为空时按较大长度归一', () => {
    expect(similarity('', 'abc')).toBe(0)
    expect(similarity('abc', '')).toBe(0)
  })
})
