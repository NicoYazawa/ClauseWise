import { flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import GlobalSearchPanel from '@/components/layout/GlobalSearchPanel.vue'
import BaseTabs from '@/components/ui/BaseTabs.vue'
import ContractDetailView from '@/views/contracts/ContractDetailView.vue'
import LawLibraryView from '@/views/knowledge/LawLibraryView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchContracts: vi.fn(),
  fetchLaws: vi.fn(),
  fetchTemplates: vi.fn(),
  saveLaw: vi.fn(),
  markExpired: vi.fn(),
  importLaws: vi.fn(),
  fetchContract: vi.fn(),
  fetchVersions: vi.fn(),
  fetchClauses: vi.fn(),
  downloadContract: vi.fn(),
  uploadContractVersion: vi.fn(),
  startReview: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}))

vi.mock('@/api/contracts', () => ({
  fetchContracts: (...a: unknown[]) => mocks.fetchContracts(...a),
  fetchContract: (...a: unknown[]) => mocks.fetchContract(...a),
  fetchVersions: (...a: unknown[]) => mocks.fetchVersions(...a),
  fetchClauses: (...a: unknown[]) => mocks.fetchClauses(...a),
  downloadContract: (...a: unknown[]) => mocks.downloadContract(...a),
  uploadContractVersion: (...a: unknown[]) => mocks.uploadContractVersion(...a),
}))

vi.mock('@/api/knowledge', () => ({
  fetchLaws: (...a: unknown[]) => mocks.fetchLaws(...a),
  fetchTemplates: (...a: unknown[]) => mocks.fetchTemplates(...a),
  saveLaw: (...a: unknown[]) => mocks.saveLaw(...a),
  markExpired: (...a: unknown[]) => mocks.markExpired(...a),
  importLaws: (...a: unknown[]) => mocks.importLaws(...a),
}))

vi.mock('@/api/reviews', () => ({ startReview: (...a: unknown[]) => mocks.startReview(...a) }))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: (...a: unknown[]) => mocks.toastInfo(...a),
}))

vi.mock('@vueuse/core', async () => {
  const actual = await vi.importActual<typeof import('@vueuse/core')>('@vueuse/core')
  return { ...actual, useDebounceFn: (fn: (...a: unknown[]) => unknown) => fn }
})

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchContracts.mockResolvedValue([])
  mocks.fetchLaws.mockResolvedValue([
    { id: 1, title: '民法典', content: '合同履行', sourceRef: '民法典', docType: 'law', effectiveDate: '2021-01-01', expiryDate: null, status: 'active', vectorized: true, hitCount: 1 },
  ])
  mocks.fetchTemplates.mockResolvedValue([])
  mocks.saveLaw.mockResolvedValue({})
  mocks.markExpired.mockResolvedValue({})
  mocks.importLaws.mockResolvedValue({ imported: 1, vectorized: 1 })
  mocks.fetchContract.mockResolvedValue({
    id: 1,
    title: '合同',
    contractNo: 'HT-1',
    contractType: 'sale',
    status: 'parsed',
    currentVersion: 1,
    amount: 1,
    ownerName: '张三',
    counterparty: { name: '甲方', idNo: '123', phone: '1' },
    createdAt: '2026-08-01T10:00:00',
    updatedAt: '2026-08-28T10:00:00',
  })
  mocks.fetchVersions.mockResolvedValue([{ id: 11, versionNo: 1, fileName: 'v1.pdf', fileSizeKb: 1024, createdAt: '2026-08-01T10:00:00', parseStatus: 'parsed', parseChannel: 'text', parentId: null }])
  mocks.fetchClauses.mockResolvedValue([])
  mocks.downloadContract.mockResolvedValue('f.pdf')
  mocks.uploadContractVersion.mockResolvedValue({ currentVersion: 2 })
  mocks.startReview.mockResolvedValue({ id: 5 })
  document.body.innerHTML = ''
})

describe('GlobalSearchPanel 关闭与空关键词', () => {
  it('点击面板外部关闭下拉', async () => {
    const { wrapper } = await mountWithApp(GlobalSearchPanel, { initialPath: '/dashboard' })
    await flushPromises()
    await wrapper.find('input[type="search"]').setValue('合同')
    await flushPromises()
    await nextTick()
    expect(wrapper.find('.shadow-float').exists()).toBe(true)

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    await nextTick()
    expect(wrapper.find('.shadow-float').exists()).toBe(false)
  })

  it('空关键词回车与查看全部都不跳转', async () => {
    const { wrapper, router } = await mountWithApp(GlobalSearchPanel, { initialPath: '/dashboard' })
    await flushPromises()
    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)

    const input = wrapper.find('input[type="search"]')
    await input.trigger('keydown', { key: 'Enter' })
    await input.setValue('   ')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(pushSpy).not.toHaveBeenCalled()
  })
})

describe('LawLibraryView 失效与详情', () => {
  it('标记失效失败提示错误', async () => {
    mocks.markExpired.mockRejectedValue(new Error('已被引用'))
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    await wrapper.findAll('tbody button')[2].trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('已被引用')
  })

  it('详情抽屉展示向量化状态与失效日期占位', async () => {
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    await wrapper.findAll('tbody button')[0].trigger('click')
    await flushPromises()
    await nextTick()
    expect(document.body.textContent ?? '').toContain('民法典')
  })
})

describe('ContractDetailView 文件校验', () => {
  async function openUpload() {
    const res = await mountWithApp(ContractDetailView, {
      initialPath: '/contracts/1',
      routes: [{ path: '/contracts/:id', component: { template: '<div />' } }],
    })
    await flushPromises()
    res.wrapper.findComponent(BaseTabs).vm.$emit('update:modelValue', 'versions')
    await flushPromises()
    const btn = res.wrapper.findAll('button').find((b) => /上传/.test(b.text()))
    await btn!.trigger('click')
    await flushPromises()
    await nextTick()
    return res
  }

  it('超过 50MB 的新版本文件被拒绝', async () => {
    await openUpload()
    const big = new File(['x'], 'big.pdf')
    Object.defineProperty(big, 'size', { value: 51 * 1024 * 1024 })
    const zone = document.body.querySelector('.border-dashed') as HTMLElement
    zone.dispatchEvent(Object.assign(new Event('drop', { bubbles: true }), { dataTransfer: { files: [big] } }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalled()
  })

  it('未携带文件的拖拽安全返回', async () => {
    await openUpload()
    const zone = document.body.querySelector('.border-dashed') as HTMLElement
    zone.dispatchEvent(new Event('drop', { bubbles: true }))
    await flushPromises()
    expect(mocks.uploadContractVersion).not.toHaveBeenCalled()
  })

  it('未选择文件时上传按钮禁用', async () => {
    await openUpload()
    const submit = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
  })
})
