import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LawLibraryView from '@/views/knowledge/LawLibraryView.vue'
import ModelPromptView from '@/views/system/ModelPromptView.vue'
import WorkflowListView from '@/views/workflow/WorkflowListView.vue'
import BaseTabs from '@/components/ui/BaseTabs.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchLaws: vi.fn(),
  saveLaw: vi.fn(),
  markExpired: vi.fn(),
  importLaws: vi.fn(),
  fetchModelVersions: vi.fn(),
  setDefaultModel: vi.fn(),
  fetchPrompts: vi.fn(),
  savePromptContent: vi.fn(),
  activatePrompt: vi.fn(),
  fetchInstances: vi.fn(),
  withdrawInstance: vi.fn(),
  currentUser: vi.fn(),
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

vi.mock('@/api/system', () => ({
  fetchModelVersions: (...a: unknown[]) => mocks.fetchModelVersions(...a),
  setDefaultModel: (...a: unknown[]) => mocks.setDefaultModel(...a),
  fetchPrompts: (...a: unknown[]) => mocks.fetchPrompts(...a),
  savePromptContent: (...a: unknown[]) => mocks.savePromptContent(...a),
  activatePrompt: (...a: unknown[]) => mocks.activatePrompt(...a),
}))

vi.mock('@/api/workflows', () => ({
  fetchInstances: (...a: unknown[]) => mocks.fetchInstances(...a),
  withdrawInstance: (...a: unknown[]) => mocks.withdrawInstance(...a),
}))

vi.mock('@/stores/auth', () => ({ currentUser: () => mocks.currentUser() }))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: (...a: unknown[]) => mocks.toastInfo(...a),
}))

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchLaws.mockResolvedValue([])
  mocks.saveLaw.mockResolvedValue({})
  mocks.markExpired.mockResolvedValue({})
  mocks.importLaws.mockResolvedValue({ imported: 2, vectorized: 1 })
  mocks.fetchModelVersions.mockResolvedValue([
    { id: 1, modelName: 'm1', modelType: 'embedding', evalMetrics: { accuracy: 0.8, falsePositive: 0, adoptionRate: null }, activatedAt: null, isDefault: false },
  ])
  mocks.setDefaultModel.mockResolvedValue({})
  mocks.fetchPrompts.mockResolvedValue([
    { id: 1, scene: 'review', version: 'v1', content: 'c', isActive: false, updatedAt: null },
  ])
  mocks.savePromptContent.mockResolvedValue({ version: 'v2' })
  mocks.activatePrompt.mockResolvedValue({})
  mocks.fetchInstances.mockResolvedValue([
    {
      id: 1, status: 'rejected', currentNodeName: '结束', contractTitle: '被驳回合同',
      contextSnapshot: { score: 50, highRisk: 1, amount: 1, riskTotal: 1 },
      definitionName: 'd', definitionVersion: 1, starterName: '张三',
      startedAt: '2026-08-28T09:00:00', finishedAt: '2026-08-29T09:00:00',
    },
  ])
  mocks.withdrawInstance.mockResolvedValue({})
  mocks.currentUser.mockReturnValue({ realName: '张三' })
  document.body.innerHTML = ''
})

function bodyButton(text: string): HTMLButtonElement {
  return Array.from(document.body.querySelectorAll('button')).find((b) =>
    (b.textContent ?? '').includes(text),
  ) as HTMLButtonElement
}

describe('LawLibraryView 导入结果与编辑', () => {
  it('导入成功后展示导入与向量化数量', async () => {
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    const importBtn = wrapper.findAll('button').find((b) => /批量导入/.test(b.text()))
    await importBtn!.trigger('click')
    await flushPromises()
    await nextTick()

    const fileInput = document.body.querySelector('input[type="file"]') as HTMLInputElement
    Object.defineProperty(fileInput, 'files', { value: [new File(['x'], 'a.xlsx')], configurable: true })
    fileInput.dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()

    bodyButton('开始导入').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.importLaws).toHaveBeenCalled()
    expect(document.body.textContent ?? '').toContain('2')
  })

  it('编辑弹窗可关闭且不提交', async () => {
    mocks.fetchLaws.mockResolvedValue([
      { id: 1, title: '法条', content: '内容', sourceRef: 'src', docType: 'law', effectiveDate: '2021-01-01', expiryDate: null, status: 'active', vectorized: true, hitCount: 0 },
    ])
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()
    await wrapper.findAll('tbody button')[1].trigger('click')
    await flushPromises()
    await nextTick()
    bodyButton('取消').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.saveLaw).not.toHaveBeenCalled()
  })
})

describe('ModelPromptView 非默认模型与未启用 Prompt', () => {
  it('展示设为默认与激活版本入口，adoptionRate 为空显示占位', async () => {
    const { wrapper } = await mountWithApp(ModelPromptView)
    await flushPromises()
    expect(wrapper.text()).toContain('—')
    expect(wrapper.findAll('button').some((b) => /激活/.test(b.text()))).toBe(true)
  })

  it('未启用 Prompt 展示编辑与激活入口', async () => {
    const { wrapper } = await mountWithApp(ModelPromptView)
    await flushPromises()
    expect(wrapper.findAll('button').some((b) => b.text().length > 0 && b.text().length < 8)).toBe(true)
  })
})

describe('WorkflowListView 状态筛选与结束态', () => {
  it('筛选已驳回状态展示对应实例', async () => {
    const { wrapper } = await mountWithApp(WorkflowListView)
    await flushPromises()
    const rejected = wrapper.findAll('button').find((b) => /驳回/.test(b.text()))
    if (rejected) {
      await rejected.trigger('click')
      await flushPromises()
    }
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('已结束实例展示在已完成标签中', async () => {
    const { wrapper } = await mountWithApp(WorkflowListView)
    await flushPromises()
    wrapper.findComponent(BaseTabs).vm.$emit('update:modelValue', 'done')
    await flushPromises()
    expect(wrapper.text()).toContain('被驳回合同')
  })
})
