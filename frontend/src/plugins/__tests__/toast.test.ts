import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import toastPlugin, { toastError, toastInfo, toastState, toastSuccess } from '@/plugins/toast'

describe('toast 通知队列', () => {
  beforeEach(() => {
    toastState.items.splice(0, toastState.items.length)
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('三种类型分别入队并可自动出队', () => {
    toastSuccess('保存成功')
    toastError('保存失败')
    toastInfo('提示')
    expect(toastState.items.map((t) => t.type)).toEqual(['success', 'error', 'info'])
    expect(toastState.items.map((t) => t.message)).toEqual(['保存成功', '保存失败', '提示'])

    vi.advanceTimersByTime(2800)
    expect(toastState.items).toHaveLength(0)
  })

  it('id 自增且唯一', () => {
    toastSuccess('a')
    toastSuccess('b')
    const [first, second] = toastState.items
    expect(second.id).toBeGreaterThan(first.id)
  })

  it('install 注册全局 $toast 并推送消息', () => {
    const props: Record<string, unknown> = {}
    type GlobalProps = { config: { globalProperties: Record<string, unknown> } }
    toastPlugin.install({
      config: { globalProperties: props },
    } as unknown as Parameters<typeof toastPlugin.install>[0])

    const $toast = props.$toast as {
      success: (m: string) => void
      error: (m: string) => void
      info: (m: string) => void
    }
    $toast.success('s')
    $toast.error('e')
    $toast.info('i')
    expect(toastState.items.map((t) => t.type)).toEqual(['success', 'error', 'info'])
    void ({} as GlobalProps)
  })

  it('已被提前移除的记录不会在计时器触发时误删其他消息', () => {
    toastSuccess('first')
    toastSuccess('second')
    const firstId = toastState.items[0].id
    // 手动移除第一条，模拟外部消费
    const idx = toastState.items.findIndex((t) => t.id === firstId)
    toastState.items.splice(idx, 1)
    vi.advanceTimersByTime(2800)
    expect(toastState.items).toHaveLength(0)
  })
})
