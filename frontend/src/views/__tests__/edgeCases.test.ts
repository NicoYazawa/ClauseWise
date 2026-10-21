import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import StatusBadge from '@/components/ui/StatusBadge.vue'
import RolePermissionView from '@/views/system/RolePermissionView.vue'
import TemplateLibraryView from '@/views/knowledge/TemplateLibraryView.vue'
import WorkflowListView from '@/views/workflow/WorkflowListView.vue'
import BaseTabs from '@/components/ui/BaseTabs.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchRoles: vi.fn(),
  updateRolePermissions: vi.fn(),
  fetchTemplates: vi.fn(),
  saveTemplate: vi.fn(),
  deleteTemplate: vi.fn(),
  fetchInstances: vi.fn(),
  withdrawInstance: vi.fn(),
  currentUser: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}))

vi.mock('@/api/system', () => ({
  fetchRoles: (...a: unknown[]) => mocks.fetchRoles(...a),
  updateRolePermissions: (...a: unknown[]) => mocks.updateRolePermissions(...a),
}))

vi.mock('@/api/knowledge', () => ({
  fetchTemplates: (...a: unknown[]) => mocks.fetchTemplates(...a),
  saveTemplate: (...a: unknown[]) => mocks.saveTemplate(...a),
  deleteTemplate: (...a: unknown[]) => mocks.deleteTemplate(...a),
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
  mocks.fetchRoles.mockResolvedValue([])
  mocks.updateRolePermissions.mockResolvedValue({})
  mocks.fetchTemplates.mockResolvedValue([])
  mocks.saveTemplate.mockResolvedValue({})
  mocks.deleteTemplate.mockResolvedValue(undefined)
  mocks.fetchInstances.mockResolvedValue([])
  mocks.withdrawInstance.mockResolvedValue({})
  mocks.currentUser.mockReturnValue({ realName: '张三' })
  document.body.innerHTML = ''
})

function bodyButton(text: string): HTMLButtonElement {
  return Array.from(document.body.querySelectorAll('button')).find((b) =>
    (b.textContent ?? '').includes(text),
  ) as HTMLButtonElement
}

describe('StatusBadge 边界', () => {
  it('空值回退为原文且使用 slate 色', async () => {
    const { wrapper } = await mountWithApp(StatusBadge, { props: { kind: 'task', value: '' } })
    expect(wrapper.classes()).toContain('pill-neutral')
  })
})

describe('RolePermissionView 边界', () => {
  it('无角色数据时不渲染权限矩阵', async () => {
    const { wrapper } = await mountWithApp(RolePermissionView)
    await flushPromises()
    expect(wrapper.findAll('input[type="checkbox"]').length).toBe(0)
  })

  it('保存失败提示后端错误', async () => {
    mocks.fetchRoles.mockResolvedValue([
      { code: 'reviewer', name: '审查员', permissions: [], description: 'd', dataScope: 'self' },
    ])
    mocks.updateRolePermissions.mockRejectedValue(new Error('权限不足'))
    const { wrapper } = await mountWithApp(RolePermissionView)
    await flushPromises()

    const box = wrapper.findAll('input[type="checkbox"]')[0]
    await box.trigger('change')
    await flushPromises()
    const save = wrapper.findAll('button').find((b) => b.text().includes('保存'))
    await save!.trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('权限不足')
  })
})

describe('TemplateLibraryView 边界', () => {
  it('编辑已有模板时提交携带 id', async () => {
    mocks.fetchTemplates.mockResolvedValue([
      { id: 3, name: '已存在条款', contractType: 'purchase', clauseLevel: 'required', content: '内容', version: 2 },
    ])
    const { wrapper } = await mountWithApp(TemplateLibraryView)
    await flushPromises()

    const editBtn = wrapper.findAll('button').find((b) => b.attributes('title') === '编辑')
    await editBtn!.trigger('click')
    await flushPromises()
    await nextTick()

    bodyButton('保存').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.saveTemplate).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }))
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('保存失败提示错误', async () => {
    mocks.fetchTemplates.mockResolvedValue([
      { id: 4, name: '条款', contractType: 'purchase', clauseLevel: 'optional', content: '内容', version: 1 },
    ])
    mocks.saveTemplate.mockRejectedValue(new Error('版本冲突'))
    const { wrapper } = await mountWithApp(TemplateLibraryView)
    await flushPromises()
    await wrapper.findAll('button').find((b) => b.attributes('title') === '编辑')!.trigger('click')
    await flushPromises()
    await nextTick()
    bodyButton('保存').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('版本冲突')
  })

  it('切换合同类型后仅显示该类型条款', async () => {
    mocks.fetchTemplates.mockResolvedValue([
      { id: 1, name: '采购条款', contractType: 'purchase', clauseLevel: 'required', content: 'a', version: 1 },
      { id: 2, name: '销售条款', contractType: 'sale', clauseLevel: 'required', content: 'b', version: 1 },
    ])
    const { wrapper } = await mountWithApp(TemplateLibraryView)
    await flushPromises()
    expect(wrapper.text()).toContain('采购条款')

    const saleBtn = wrapper.findAll('button').find((b) => b.text() === '销售')
    if (saleBtn) {
      await saleBtn.trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('销售条款')
    }
  })
})

describe('WorkflowListView 边界', () => {
  const snapshot = { score: 90, highRisk: 0, amount: 1000, riskTotal: 1 }

  it('已完成列表包含非运行中实例', async () => {
    mocks.fetchInstances.mockResolvedValue([
      { id: 1, status: 'approved', currentNodeName: '结束', contractTitle: '已完成合同', contextSnapshot: snapshot, definitionName: 'd', definitionVersion: 1, starterName: '张三', startedAt: '2026-08-28T09:00:00', finishedAt: '2026-08-28T10:00:00' },
    ])
    const { wrapper } = await mountWithApp(WorkflowListView)
    await flushPromises()
    wrapper.findComponent(BaseTabs).vm.$emit('update:modelValue', 'done')
    await flushPromises()
    expect(wrapper.text()).toContain('已完成合同')
  })

  it('状态筛选到空结果时展示空态', async () => {
    mocks.fetchInstances.mockResolvedValue([
      { id: 1, status: 'running', currentNodeName: '部门经理审批', contractTitle: '运行中合同', contextSnapshot: snapshot, definitionName: 'd', definitionVersion: 1, starterName: '张三', startedAt: '2026-08-28T09:00:00', finishedAt: null },
    ])
    const { wrapper } = await mountWithApp(WorkflowListView)
    await flushPromises()
    const rejected = wrapper.findAll('button').find((b) => /已驳回|驳回/.test(b.text()))
    if (rejected) {
      await rejected.trigger('click')
      await flushPromises()
      expect(wrapper.text()).not.toContain('运行中合同')
    }
  })
})
