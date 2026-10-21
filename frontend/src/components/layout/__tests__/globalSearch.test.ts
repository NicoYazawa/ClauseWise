import { flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import GlobalSearchBox from '@/components/layout/GlobalSearchBox.vue'
import GlobalSearchPanel from '@/components/layout/GlobalSearchPanel.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchContracts: vi.fn(),
  fetchLaws: vi.fn(),
  fetchTemplates: vi.fn(),
}))

vi.mock('@/api/contracts', () => ({ fetchContracts: (...a: unknown[]) => mocks.fetchContracts(...a) }))
vi.mock('@/api/knowledge', () => ({
  fetchLaws: (...a: unknown[]) => mocks.fetchLaws(...a),
  fetchTemplates: (...a: unknown[]) => mocks.fetchTemplates(...a),
}))

/** 去掉防抖延迟，让搜索在测试中同步触发 */
vi.mock('@vueuse/core', async () => {
  const actual = await vi.importActual<typeof import('@vueuse/core')>('@vueuse/core')
  return { ...actual, useDebounceFn: (fn: (...a: unknown[]) => unknown) => fn }
})

const contract = {
  id: 1,
  title: '设备采购合同',
  contractNo: 'HT-1',
  contractType: 'sale',
  counterparty: { name: '甲方' },
}
const laws = [
  { id: 1, title: '民法典合同编', content: '合同履行', sourceRef: '民法典', docType: 'law' },
  { id: 2, title: '指导案例一', content: '合同纠纷', sourceRef: '', docType: 'case' },
]
const templates = [{ id: 1, name: '合同付款条款', content: '按月支付', contractType: 'sale' }]

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchContracts.mockResolvedValue([contract])
  mocks.fetchLaws.mockResolvedValue(laws)
  mocks.fetchTemplates.mockResolvedValue(templates)
})

describe('GlobalSearchPanel', () => {
  async function typeKeyword(wrapper: Awaited<ReturnType<typeof mountWithApp>>['wrapper'], value: string) {
    const input = wrapper.find('input[type="search"]')
    await input.setValue(value)
    await flushPromises()
    await nextTick()
    return input
  }

  it('输入关键词后展示合同/法条/模板三组建议', async () => {
    const { wrapper } = await mountWithApp(GlobalSearchPanel, { initialPath: '/dashboard' })
    await flushPromises()
    await typeKeyword(wrapper, '合同')

    expect(mocks.fetchContracts).toHaveBeenCalledWith({ keyword: '合同' })
    const text = wrapper.text()
    expect(text).toContain('设备采购合同')
    expect(text).toContain('民法典合同编')
    expect(text).toContain('合同付款条款')
  })

  it('无匹配时展示空结果（不渲染下拉）', async () => {
    mocks.fetchContracts.mockResolvedValue([])
    mocks.fetchLaws.mockResolvedValue([])
    mocks.fetchTemplates.mockResolvedValue([])
    const { wrapper } = await mountWithApp(GlobalSearchPanel, { initialPath: '/dashboard' })
    await flushPromises()
    await typeKeyword(wrapper, '不存在')
    expect(wrapper.find('.shadow-float').exists()).toBe(false)
  })

  it('点击建议项跳转并清空关键词', async () => {
    const { wrapper, router } = await mountWithApp(GlobalSearchPanel, { initialPath: '/dashboard' })
    await flushPromises()
    await typeKeyword(wrapper, '合同')

    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    const item = wrapper.findAll('button').find((b) => b.text().includes('设备采购合同'))
    await item!.trigger('click')
    expect(pushSpy).toHaveBeenCalledWith('/contracts/1')
    expect((wrapper.find('input[type="search"]').element as HTMLInputElement).value).toBe('')
  })

  it('点击「查看全部」跳转搜索页并带查询词', async () => {
    const { wrapper, router } = await mountWithApp(GlobalSearchPanel, { initialPath: '/dashboard' })
    await flushPromises()
    await typeKeyword(wrapper, '合同')

    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    const viewAll = wrapper.findAll('button').at(-1)
    await viewAll!.trigger('click')
    expect(pushSpy).toHaveBeenCalledWith({ path: '/search', query: { q: '合同' } })
  })

  it('方向键切换高亮、回车打开选中项', async () => {
    const { wrapper, router } = await mountWithApp(GlobalSearchPanel, { initialPath: '/dashboard' })
    await flushPromises()
    const input = await typeKeyword(wrapper, '合同')
    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)

    await input.trigger('keydown', { key: 'ArrowDown' })
    await flushPromises()
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(pushSpy).toHaveBeenCalled()
  })

  it('向上方向键在无结果时安全返回', async () => {
    mocks.fetchContracts.mockResolvedValue([])
    mocks.fetchLaws.mockResolvedValue([])
    mocks.fetchTemplates.mockResolvedValue([])
    const { wrapper } = await mountWithApp(GlobalSearchPanel, { initialPath: '/dashboard' })
    await flushPromises()
    const input = await typeKeyword(wrapper, '无')
    await input.trigger('keydown', { key: 'ArrowUp' })
    expect((wrapper.find('input[type="search"]').element as HTMLInputElement).value).toBe('无')
  })

  it('点击分组「查看全部」按分组路径跳转', async () => {
    const { wrapper, router } = await mountWithApp(GlobalSearchPanel, { initialPath: '/dashboard' })
    await flushPromises()
    await typeKeyword(wrapper, '合同')

    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    const groupAll = wrapper.findAll('button').filter((b) => /查看/.test(b.text()))
    await groupAll[0].trigger('click')
    expect(pushSpy).toHaveBeenCalled()
  })

  it('清空按钮清空关键词，Esc 关闭下拉', async () => {
    const { wrapper } = await mountWithApp(GlobalSearchPanel, { initialPath: '/dashboard' })
    await flushPromises()
    await typeKeyword(wrapper, '合同')

    const clearBtn = wrapper.findAll('button').find((b) => b.attributes('aria-label'))
    await clearBtn?.trigger('click')
    expect((wrapper.find('input[type="search"]').element as HTMLInputElement).value).toBe('')

    await typeKeyword(wrapper, '合同')
    await wrapper.find('.relative').trigger('keydown', { key: 'Escape' })
    await nextTick()
    expect(wrapper.find('.shadow-float').exists()).toBe(false)
  })

  it('block 模式使用内联展开样式', async () => {
    const { wrapper } = await mountWithApp(GlobalSearchPanel, {
      props: { mode: 'block' },
      initialPath: '/dashboard',
    })
    await flushPromises()
    await typeKeyword(wrapper, '合同')
    expect(wrapper.find('.shadow-float').classes().join(' ')).toContain('relative')
  })
})

describe('GlobalSearchBox', () => {
  it('桌面端内嵌面板，移动端按钮打开弹窗', async () => {
    const { wrapper } = await mountWithApp(GlobalSearchBox, { initialPath: '/dashboard' })
    await flushPromises()
    expect(wrapper.findComponent(GlobalSearchPanel).exists()).toBe(true)

    const openBtn = wrapper.findAll('button').find((b) => b.attributes('aria-label'))
    await openBtn?.trigger('click')
    await nextTick()
    expect(document.body.textContent ?? '').not.toBe('')
  })
})
