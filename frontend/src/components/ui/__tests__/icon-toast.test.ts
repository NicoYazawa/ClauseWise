import { flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import Icon from '@/components/ui/Icon.vue'
import ToastHost from '@/components/ui/ToastHost.vue'
import { toastState } from '@/plugins/toast'
import { mountWithApp } from '@test/helpers'

describe('Icon', () => {
  it('已知图标渲染对应 SVG 路径，默认 18px', async () => {
    const { wrapper } = await mountWithApp(Icon, { props: { name: 'search' } })
    expect(wrapper.find('svg').attributes('width')).toBe('18')
    expect(wrapper.html()).toContain('circle')
  })

  it('未知图标回退 info 图标（字典默认分支）', async () => {
    const { wrapper } = await mountWithApp(Icon, { props: { name: '__not_exist__' } })
    expect(wrapper.html()).toContain('circle')
  })

  it('size 支持数字与字符串', async () => {
    const { wrapper: num } = await mountWithApp(Icon, { props: { name: 'check', size: 24 } })
    expect(num.find('svg').attributes('width')).toBe('24')
    const { wrapper: str } = await mountWithApp(Icon, { props: { name: 'check', size: '1em' } })
    expect(str.find('svg').attributes('width')).toBe('1em')
  })
})

describe('ToastHost', () => {
  beforeEach(() => {
    toastState.items.splice(0, toastState.items.length)
    document.body.innerHTML = ''
  })

  afterEach(() => {
    toastState.items.splice(0, toastState.items.length)
  })

  it('无消息时不渲染任何 toast', async () => {
    const { wrapper } = await mountWithApp(ToastHost)
    await nextTick()
    expect(document.body.querySelector('[role="status"]')).toBeNull()
    wrapper.unmount()
  })

  it('按队列渲染成功/错误/提示（Teleport 到 body）', async () => {
    toastState.items.push(
      { id: 1, type: 'success', message: '保存成功' },
      { id: 2, type: 'error', message: '保存失败' },
      { id: 3, type: 'info', message: '提示信息' },
    )
    const { wrapper } = await mountWithApp(ToastHost)
    await flushPromises()
    await nextTick()

    const text = document.body.textContent ?? ''
    expect(text).toContain('保存成功')
    expect(text).toContain('保存失败')
    expect(text).toContain('提示信息')
    expect(document.body.querySelectorAll('[role="status"]').length).toBeGreaterThan(0)
    wrapper.unmount()
  })
})
