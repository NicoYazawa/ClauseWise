import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LawLibraryView from '@/views/knowledge/LawLibraryView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchLaws: vi.fn(),
  saveLaw: vi.fn(),
  markExpired: vi.fn(),
  importLaws: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}))

vi.mock('@/api/knowledge', () => ({
  fetchLaws: (...a: unknown[]) => mocks.fetchLaws(...a),
  saveLaw: (...a: unknown[]) => mocks.saveLaw(...a),
  markExpired: (...a: unknown[]) => mocks.markExpired(...a),
  importLaws: (...a: unknown[]) => mocks.importLaws(...a),
}))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: (...a: unknown[]) => mocks.toastInfo(...a),
}))

function law(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    docType: 'law',
    title: '民法典第五百零九条',
    content: '当事人应当按照约定全面履行自己的义务',
    sourceRef: '民法典',
    effectiveDate: '2021-01-01',
    expiryDate: null,
    status: 'active',
    vectorized: true,
    hitCount: 12,
    ...over,
  }
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchLaws.mockResolvedValue([])
  mocks.saveLaw.mockResolvedValue({})
  mocks.markExpired.mockResolvedValue({})
  mocks.importLaws.mockResolvedValue({ imported: 3, vectorized: 3 })
  document.body.innerHTML = ''
})

function bodyButton(text: string): HTMLButtonElement {
  return Array.from(document.body.querySelectorAll('button')).find((b) =>
    (b.textContent ?? '').includes(text),
  ) as HTMLButtonElement
}

async function openModal(wrapper: Awaited<ReturnType<typeof mountWithApp>>['wrapper'], text: string) {
  const btn = wrapper.findAll('button').find((b) => b.text().includes(text))
  await btn!.trigger('click')
  await flushPromises()
  await nextTick()
}

describe('LawLibraryView 列表与筛选', () => {
  it('渲染法条/案例、生效/失效、向量化状态', async () => {
    mocks.fetchLaws.mockResolvedValue([
      law({ id: 1 }),
      law({ id: 2, docType: 'case', status: 'expired', vectorized: false, title: '指导案例' }),
    ])
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()

    expect(wrapper.text()).toContain('民法典第五百零九条')
    expect(wrapper.text()).toContain('指导案例')
    expect(wrapper.text().length).toBeGreaterThan(100)
  })

  it('关键词过滤生效', async () => {
    mocks.fetchLaws.mockResolvedValue([
      law({ id: 1, title: '合同编' }),
      law({ id: 2, docType: 'case', title: '票据案例', content: '票据' }),
    ])
    const { wrapper } = await mountWithApp(LawLibraryView, { initialPath: '/knowledge/laws?q=合同' })
    await flushPromises()
    expect(wrapper.text()).toContain('合同编')
    expect(wrapper.text()).not.toContain('票据案例')
  })

  it('类型筛选生效', async () => {
    mocks.fetchLaws.mockResolvedValue([
      law({ id: 1, title: '合同编' }),
      law({ id: 2, docType: 'case', title: '票据案例', content: '票据' }),
    ])
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    const select = wrapper.find('select')
    await select.setValue('case')
    await flushPromises()
    expect(wrapper.text()).toContain('票据案例')
    expect(wrapper.text()).not.toContain('合同编')
  })

  it('超过一页时分页', async () => {
    mocks.fetchLaws.mockResolvedValue(
      Array.from({ length: 12 }, (_, i) => law({ id: i + 1, title: `法条${i + 1}` })),
    )
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    expect(wrapper.text()).toContain('法条1')
    await wrapper.findAll('button').find((b) => b.text() === '2')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('法条11')
  })

  it('点击标题打开详情抽屉（有无失效日期两种情况）', async () => {
    mocks.fetchLaws.mockResolvedValue([
      law({ id: 1 }),
      law({ id: 2, title: '失效法条', expiryDate: '2026-01-01', status: 'expired', vectorized: false }),
    ])
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()

    await wrapper.findAll('tbody button')[0].trigger('click')
    await flushPromises()
    await nextTick()
    expect(document.body.textContent ?? '').toContain('民法典')

    const titleBtn = wrapper.findAll('tbody button').find((b) => b.text() === '失效法条')
    await titleBtn!.trigger('click')
    await flushPromises()
    await nextTick()
    expect(document.body.textContent ?? '').toContain('2026-01-01')
  })
})

describe('LawLibraryView 编辑与新建', () => {
  it('新建时字段必填校验', async () => {
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    await openModal(wrapper, '新增法条')

    bodyButton('保存并向量化').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.saveLaw).not.toHaveBeenCalled()
    expect(mocks.toastError).toHaveBeenCalled()
  })

  it('新建成功后关闭弹窗并提示', async () => {
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    await openModal(wrapper, '新增法条')

    const inputs = document.body.querySelectorAll('input:not([type="file"])')
    await new DOMWrapper(inputs[0]).setValue('新法条标题')
    await new DOMWrapper(document.body.querySelector('textarea')!).setValue('法条正文')
    bodyButton('保存并向量化').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(mocks.saveLaw).toHaveBeenCalledWith(expect.objectContaining({ title: '新法条标题' }))
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('编辑时提交携带 id 与原有失效日期', async () => {
    mocks.fetchLaws.mockResolvedValue([law({ id: 9, expiryDate: '2027-01-01' })])
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    const editBtn = wrapper.findAll('tbody button')[1]
    await editBtn.trigger('click')
    await flushPromises()
    await nextTick()

    await new DOMWrapper(document.body.querySelector('input:not([type="file"])')!).setValue('改后的标题')
    bodyButton('保存').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(mocks.saveLaw).toHaveBeenCalledWith(expect.objectContaining({ id: 9, expiryDate: '2027-01-01' }))
  })

  it('保存失败时提示错误信息', async () => {
    mocks.saveLaw.mockRejectedValue(new Error('向量化失败'))
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    await openModal(wrapper, '新增法条')

    const inputs = document.body.querySelectorAll('input:not([type="file"])')
    await new DOMWrapper(inputs[0]).setValue('标题')
    await new DOMWrapper(document.body.querySelector('textarea')!).setValue('正文')
    bodyButton('保存并向量化').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(mocks.toastError).toHaveBeenCalledWith('向量化失败')
  })

  it('标记失效成功后提示', async () => {
    mocks.fetchLaws.mockResolvedValue([law({ id: 3 })])
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    const banBtn = wrapper.findAll('tbody button')[2]
    await banBtn.trigger('click')
    await flushPromises()
    expect(mocks.markExpired).toHaveBeenCalledWith(3)
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })
})

describe('LawLibraryView 批量导入', () => {
  it('未选择文件时导入按钮禁用', async () => {
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    await openModal(wrapper, 'Excel 批量导入')

    expect(bodyButton('开始导入').disabled).toBe(true)
    expect(mocks.importLaws).not.toHaveBeenCalled()
  })

  it('非法格式提示，合法格式展示文件名并可导入', async () => {
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    await openModal(wrapper, 'Excel 批量导入')

    const fileInput = document.body.querySelector('input[type="file"]') as HTMLInputElement
    Object.defineProperty(fileInput, 'files', { value: [new File(['x'], 'bad.txt')], configurable: true })
    fileInput.dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalled()

    Object.defineProperty(fileInput, 'files', { value: [new File(['x'], 'laws.xlsx')], configurable: true })
    fileInput.dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()
    expect(document.body.textContent ?? '').toContain('laws.xlsx')

    bodyButton('开始导入').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.importLaws).toHaveBeenCalled()
  })
})
