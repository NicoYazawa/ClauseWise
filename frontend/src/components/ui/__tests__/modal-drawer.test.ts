import { flushPromises } from '@vue/test-utils'
import { computed, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import BaseDrawer from '@/components/ui/BaseDrawer.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import { mountWithApp } from '@test/helpers'

const motionPref = vi.hoisted(() => ({ value: 'no-preference' as 'no-preference' | 'reduce' }))

vi.mock('@vueuse/core', async () => {
  const actual = await vi.importActual<typeof import('@vueuse/core')>('@vueuse/core')
  return {
    ...actual,
    usePreferredReducedMotion: () => computed(() => motionPref.value),
  }
})

beforeEach(() => {
  motionPref.value = 'no-preference'
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.innerHTML = ''
})

function closeButton(): HTMLButtonElement | null {
  return document.body.querySelector('button[aria-label]')
}

describe('BaseModal', () => {
  it('open=false 时不渲染内容', async () => {
    const { wrapper } = await mountWithApp(BaseModal, {
      props: { open: false, title: '标题' },
      slots: { default: '<p>内容</p>' },
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain('内容')
    expect(document.body.textContent ?? '').not.toContain('内容')
  })

  it('open=true 时 portal 到 body 渲染标题/内容/footer', async () => {
    await mountWithApp(BaseModal, {
      props: { open: true, title: '确认删除', width: 'max-w-sm' },
      slots: { default: '<p>正文内容</p>', footer: '<button>确定</button>' },
    })
    await flushPromises()
    await nextTick()
    const text = document.body.textContent ?? ''
    expect(text).toContain('确认删除')
    expect(text).toContain('正文内容')
    expect(text).toContain('确定')
  })

  it('无 footer 插槽时不渲染底部操作区', async () => {
    await mountWithApp(BaseModal, { props: { open: true, title: 'T' }, slots: { default: 'x' } })
    await flushPromises()
    expect(document.body.innerHTML).not.toContain('justify-end')
  })

  it('点击关闭按钮触发 close 事件', async () => {
    const { wrapper } = await mountWithApp(BaseModal, { props: { open: true, title: 'T' } })
    await flushPromises()
    await nextTick()
    const btn = closeButton()
    expect(btn).toBeTruthy()
    btn!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('减少动效偏好下仍可正常渲染', async () => {
    motionPref.value = 'reduce'
    await mountWithApp(BaseModal, { props: { open: true, title: '无动效' } })
    await flushPromises()
    expect(document.body.textContent ?? '').toContain('无动效')
  })
})

describe('BaseDrawer', () => {
  it('open=false 时不渲染内容', async () => {
    await mountWithApp(BaseDrawer, { props: { open: false, title: '抽屉' }, slots: { default: '内容' } })
    await flushPromises()
    expect(document.body.textContent ?? '').not.toContain('内容')
  })

  it('open=true 时渲染标题、正文与底部', async () => {
    await mountWithApp(BaseDrawer, {
      props: { open: true, title: '详情抽屉', width: 'w-[400px]' },
      slots: { default: '<p>抽屉正文</p>', footer: '<button>保存</button>' },
    })
    await flushPromises()
    await nextTick()
    const text = document.body.textContent ?? ''
    expect(text).toContain('详情抽屉')
    expect(text).toContain('抽屉正文')
    expect(text).toContain('保存')
  })

  it('点击关闭触发 close；减少动效偏好可渲染', async () => {
    motionPref.value = 'reduce'
    const { wrapper } = await mountWithApp(BaseDrawer, { props: { open: true, title: 'D' } })
    await flushPromises()
    await nextTick()
    const btn = closeButton()
    btn!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})
