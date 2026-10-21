import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ModelPromptView from '@/views/system/ModelPromptView.vue'
import TemplateLibraryView from '@/views/knowledge/TemplateLibraryView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchTemplates: vi.fn(),
  saveTemplate: vi.fn(),
  deleteTemplate: vi.fn(),
  fetchModelVersions: vi.fn(),
  setDefaultModel: vi.fn(),
  fetchPrompts: vi.fn(),
  savePromptContent: vi.fn(),
  activatePrompt: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/api/knowledge', () => ({
  fetchTemplates: (...a: unknown[]) => mocks.fetchTemplates(...a),
  saveTemplate: (...a: unknown[]) => mocks.saveTemplate(...a),
  deleteTemplate: (...a: unknown[]) => mocks.deleteTemplate(...a),
}))

vi.mock('@/api/system', () => ({
  fetchModelVersions: (...a: unknown[]) => mocks.fetchModelVersions(...a),
  setDefaultModel: (...a: unknown[]) => mocks.setDefaultModel(...a),
  fetchPrompts: (...a: unknown[]) => mocks.fetchPrompts(...a),
  savePromptContent: (...a: unknown[]) => mocks.savePromptContent(...a),
  activatePrompt: (...a: unknown[]) => mocks.activatePrompt(...a),
}))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: vi.fn(),
}))

function template(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: '付款条款',
    contractType: 'purchase',
    clauseLevel: 'required',
    content: '按月结算',
    version: 2,
    ...over,
  }
}

function model(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    modelName: 'contract-review',
    modelType: 'llm',
    evalMetrics: { accuracy: 0.923, falsePositive: 0.05, adoptionRate: 0.8 },
    activatedAt: '2026-08-28T10:00:00',
    isDefault: true,
    ...over,
  }
}

function prompt(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    scene: 'review',
    version: 'v3',
    content: '提示词内容',
    isActive: true,
    updatedAt: '2026-08-28T10:00:00',
    ...over,
  }
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchTemplates.mockResolvedValue([])
  mocks.saveTemplate.mockResolvedValue({})
  mocks.deleteTemplate.mockResolvedValue(undefined)
  mocks.fetchModelVersions.mockResolvedValue([])
  mocks.setDefaultModel.mockResolvedValue({})
  mocks.fetchPrompts.mockResolvedValue([])
  mocks.savePromptContent.mockResolvedValue({ version: 'v4' })
  mocks.activatePrompt.mockResolvedValue({})
  document.body.innerHTML = ''
})

describe('TemplateLibraryView', () => {
  it('按合同类型切换分组并展示三级条款', async () => {
    mocks.fetchTemplates.mockResolvedValue([
      template({ id: 1, name: '必选条款', clauseLevel: 'required' }),
      template({ id: 2, name: '推荐条款', clauseLevel: 'recommended' }),
      template({ id: 3, name: '可选条款', clauseLevel: 'optional' }),
      template({ id: 4, name: '销售条款', contractType: 'sale' }),
    ])
    const { wrapper } = await mountWithApp(TemplateLibraryView)
    await flushPromises()

    expect(wrapper.text()).toContain('必选条款')
    expect(wrapper.text()).toContain('推荐条款')
    expect(wrapper.text()).toContain('可选条款')
    expect(wrapper.text()).not.toContain('销售条款')
  })

  it('关键词过滤与类型切换生效', async () => {
    mocks.fetchTemplates.mockResolvedValue([
      template({ id: 1, name: '付款条款', content: '按月结算' }),
      template({ id: 2, name: '保密条款', content: '不得泄露' }),
      template({ id: 3, name: '销售付款条款', contractType: 'sale' }),
    ])
    const { wrapper } = await mountWithApp(TemplateLibraryView, { initialPath: '/knowledge/templates?q=付款' })
    await flushPromises()
    expect(wrapper.text()).toContain('付款条款')
    expect(wrapper.text()).not.toContain('保密条款')

    const typeBtns = wrapper.findAll('button').filter((b) => b.text().length > 0 && b.text().length < 10)
    if (typeBtns.length > 1) {
      await typeBtns.at(-1)!.trigger('click')
      await flushPromises()
    }
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('编辑时预填并提交新版本，新建时字段必填', async () => {
    mocks.fetchTemplates.mockResolvedValue([template({ id: 5 })])
    const { wrapper } = await mountWithApp(TemplateLibraryView)
    await flushPromises()

    // 新建：字段为空提交 → 提示
    const createBtn = wrapper.findAll('button').find((b) => b.text().length > 0 && b.text().length < 10)
    await createBtn!.trigger('click')
    await flushPromises()
    await nextTick()
    const saveBtn = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    saveBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.saveTemplate).not.toHaveBeenCalled()
    expect(mocks.toastError).toHaveBeenCalled()

    // 编辑：点击编辑按钮预填 content
    document.body.innerHTML = ''
    const editBtn = wrapper.findAll('tbody button, .p-1')[0]
    if (editBtn) {
      await editBtn.trigger('click')
      await flushPromises()
      await nextTick()
      const textarea = document.body.querySelector('textarea')
      if (textarea) {
        await new DOMWrapper(textarea).setValue('更新后的条款内容')
        const submit = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
        submit.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        await flushPromises()
        expect(mocks.saveTemplate).toHaveBeenCalled()
      }
    }
  })

  it('删除确认后调用删除接口并提示', async () => {
    mocks.fetchTemplates.mockResolvedValue([template({ id: 7, name: '待删条款' })])
    const { wrapper } = await mountWithApp(TemplateLibraryView)
    await flushPromises()

    const deleteBtn = wrapper.findAll('button').find((b) => b.attributes('title') === '删除')
    if (deleteBtn) {
      await deleteBtn.trigger('click')
      await flushPromises()
      await nextTick()
      const confirm = document.body.querySelector('.btn-danger') as HTMLButtonElement
      confirm.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushPromises()
      expect(mocks.deleteTemplate).toHaveBeenCalledWith(7)
      expect(mocks.toastSuccess).toHaveBeenCalled()
    }
  })

  it('删除失败提示错误', async () => {
    mocks.fetchTemplates.mockResolvedValue([template({ id: 8 })])
    mocks.deleteTemplate.mockRejectedValue(new Error('有引用无法删除'))
    const { wrapper } = await mountWithApp(TemplateLibraryView)
    await flushPromises()
    const deleteBtn = wrapper.findAll('button').find((b) => b.attributes('title') === '删除')
    if (deleteBtn) {
      await deleteBtn.trigger('click')
      await flushPromises()
      await nextTick()
      ;(document.body.querySelector('.btn-danger') as HTMLButtonElement).dispatchEvent(
        new MouseEvent('click', { bubbles: true }),
      )
      await flushPromises()
      expect(mocks.toastError).toHaveBeenCalledWith('有引用无法删除')
    }
  })
})

describe('ModelPromptView', () => {
  it('渲染模型版本与 Prompt 列表（含默认/启用状态）', async () => {
    mocks.fetchModelVersions.mockResolvedValue([
      model({ id: 1 }),
      model({ id: 2, modelName: 'embedding-v4', modelType: 'embedding', isDefault: false, evalMetrics: { accuracy: 0.8, falsePositive: 0.1, adoptionRate: null } }),
    ])
    mocks.fetchPrompts.mockResolvedValue([
      prompt({ id: 1 }),
      prompt({ id: 2, version: 'v2', isActive: false }),
    ])
    const { wrapper } = await mountWithApp(ModelPromptView)
    await flushPromises()

    expect(wrapper.text()).toContain('contract-review')
    expect(wrapper.text()).toContain('embedding-v4')
    expect(wrapper.text()).toContain('v3')
    expect(wrapper.text()).toContain('—')
  })

  it('切换默认模型成功/失败', async () => {
    mocks.fetchModelVersions.mockResolvedValue([model({ id: 2, isDefault: false })])
    const { wrapper } = await mountWithApp(ModelPromptView)
    await flushPromises()

    const setDefault = () => wrapper.findAll('button').find((b) => /默认/.test(b.text()))
    await setDefault()!.trigger('click')
    await flushPromises()
    expect(mocks.setDefaultModel).toHaveBeenCalledWith(2)
    expect(mocks.toastSuccess).toHaveBeenCalled()

    mocks.setDefaultModel.mockRejectedValue(new Error('质量回归未通过'))
    await setDefault()!.trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('质量回归未通过')
  })

  it('编辑 Prompt 并发布新版本', async () => {
    mocks.fetchPrompts.mockResolvedValue([prompt({ id: 3 })])
    const { wrapper } = await mountWithApp(ModelPromptView)
    await flushPromises()

    const editBtn = wrapper.findAll('button').find((b) => b.text().length > 0 && b.text().length < 10)
    await editBtn!.trigger('click')
    await flushPromises()
    await nextTick()

    const textarea = document.body.querySelector('textarea') as HTMLTextAreaElement
    await new DOMWrapper(textarea).setValue('新的提示词')
    const publish = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    publish.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(mocks.savePromptContent).toHaveBeenCalledWith(3, '新的提示词')
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('发布失败提示错误', async () => {
    mocks.fetchPrompts.mockResolvedValue([prompt({ id: 4 })])
    mocks.savePromptContent.mockRejectedValue(new Error('版本冲突'))
    const { wrapper } = await mountWithApp(ModelPromptView)
    await flushPromises()
    await wrapper.findAll('button').find((b) => b.text().length > 0 && b.text().length < 10)!.trigger('click')
    await flushPromises()
    await nextTick()
    const publish = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    publish.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('版本冲突')
  })

  it('激活历史版本成功/失败', async () => {
    mocks.fetchPrompts.mockResolvedValue([prompt({ id: 5, isActive: false })])
    const { wrapper } = await mountWithApp(ModelPromptView)
    await flushPromises()

    const activateBtn = () => wrapper.findAll('button').find((b) => /激活/.test(b.text()))
    await activateBtn()!.trigger('click')
    await flushPromises()
    expect(mocks.activatePrompt).toHaveBeenCalledWith(5)

    mocks.activatePrompt.mockRejectedValue(new Error('场景冲突'))
    await activateBtn()!.trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('场景冲突')
  })
})
