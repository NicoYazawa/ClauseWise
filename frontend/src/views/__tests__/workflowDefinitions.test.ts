import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WorkflowDefinitionsView from '@/views/workflow/WorkflowDefinitionsView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchDefinitions: vi.fn(),
  saveDefinition: vi.fn(),
  toggleDefinition: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/api/workflows', () => ({
  fetchDefinitions: (...a: unknown[]) => mocks.fetchDefinitions(...a),
  saveDefinition: (...a: unknown[]) => mocks.saveDefinition(...a),
  toggleDefinition: (...a: unknown[]) => mocks.toggleDefinition(...a),
}))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: vi.fn(),
}))

function definition(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: '标准合同审批流',
    version: 2,
    enabled: true,
    contractTypes: ['sale', 'purchase'],
    updatedAt: '2026-08-28T10:00:00',
    nodes: [
      { id: 'start', type: 'start', name: '开始' },
      { id: 'n1', type: 'approval', name: '部门经理审批', signMode: 'or', assignees: ['role:dept_manager'], timeoutHours: 24 },
      { id: 'n2', type: 'condition', name: '金额判断', rules: [{ when: 'risk_score < 85 and amount >= 1000000', goto: 'n3' }] },
      { id: 'end', type: 'end', name: '结束' },
    ],
    ...over,
  }
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchDefinitions.mockResolvedValue([definition()])
  mocks.saveDefinition.mockResolvedValue({ id: 1, name: '标准合同审批流', version: 3 })
  mocks.toggleDefinition.mockResolvedValue({ id: 1, name: '标准合同审批流', enabled: false })
  document.body.innerHTML = ''
})

function bodyButton(text: string): HTMLButtonElement {
  return Array.from(document.body.querySelectorAll('button')).find((b) =>
    (b.textContent ?? '').includes(text),
  ) as HTMLButtonElement
}

async function openCreate(wrapper: Awaited<ReturnType<typeof mountWithApp>>['wrapper']) {
  const btn = wrapper.findAll('button').find((b) => /新建|创建/.test(b.text()))
  await btn!.trigger('click')
  await flushPromises()
  await nextTick()
}

describe('WorkflowDefinitionsView 列表', () => {
  it('渲染定义、适用类型与节点明细', async () => {
    const { wrapper } = await mountWithApp(WorkflowDefinitionsView)
    await flushPromises()

    expect(wrapper.text()).toContain('标准合同审批流')
    expect(wrapper.text()).toContain('n1')
    expect(wrapper.text()).toContain('24h')
    // condition 节点展示规则表达式
    expect(wrapper.text()).toContain('risk_score < 85')
  })

  it('停用定义调用接口并提示', async () => {
    const { wrapper } = await mountWithApp(WorkflowDefinitionsView)
    await flushPromises()
    const toggleBtn = wrapper.findAll('button').find((b) => /停用|启用/.test(b.text()))
    await toggleBtn!.trigger('click')
    await flushPromises()
    expect(mocks.toggleDefinition).toHaveBeenCalledWith(1)
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('启用定义成功提示启用', async () => {
    mocks.fetchDefinitions.mockResolvedValue([definition({ enabled: false })])
    mocks.toggleDefinition.mockResolvedValue({ id: 1, name: '标准合同审批流', enabled: true })
    const { wrapper } = await mountWithApp(WorkflowDefinitionsView)
    await flushPromises()
    await wrapper.findAll('button').find((b) => /启用/.test(b.text()))!.trigger('click')
    await flushPromises()
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('切换定义失败提示错误', async () => {
    mocks.toggleDefinition.mockRejectedValue(new Error('存在运行中实例'))
    const { wrapper } = await mountWithApp(WorkflowDefinitionsView)
    await flushPromises()
    await wrapper.findAll('button').find((b) => /停用|启用/.test(b.text()))!.trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('存在运行中实例')
  })
})

describe('WorkflowDefinitionsView 编排弹窗', () => {
  it('名称必填校验', async () => {
    const { wrapper } = await mountWithApp(WorkflowDefinitionsView)
    await flushPromises()
    await openCreate(wrapper)

    bodyButton('创建').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.saveDefinition).not.toHaveBeenCalled()
    expect(mocks.toastError).toHaveBeenCalled()
  })

  it('新建提交成功并提示', async () => {
    const { wrapper } = await mountWithApp(WorkflowDefinitionsView)
    await flushPromises()
    await openCreate(wrapper)

    const nameInput = document.body.querySelector('input.input') as HTMLInputElement
    await new DOMWrapper(nameInput).setValue('新审批流')
    bodyButton('创建').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(mocks.saveDefinition).toHaveBeenCalledWith(expect.objectContaining({ name: '新审批流' }))
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('编辑定义时预填并发布新版本', async () => {
    const { wrapper } = await mountWithApp(WorkflowDefinitionsView)
    await flushPromises()
    const editBtn = wrapper.findAll('button').find((b) => /编辑|新版本/.test(b.text()))
    await editBtn!.trigger('click')
    await flushPromises()
    await nextTick()

    // 编辑态应解析出 risk 阈值与金额阈值
    expect(document.body.textContent ?? '').toContain('85')
    bodyButton('发布').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.saveDefinition).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }))
  })

  it('保存失败提示错误', async () => {
    mocks.saveDefinition.mockRejectedValue(new Error('名称重复'))
    const { wrapper } = await mountWithApp(WorkflowDefinitionsView)
    await flushPromises()
    await openCreate(wrapper)
    const nameInput = document.body.querySelector('input.input') as HTMLInputElement
    await new DOMWrapper(nameInput).setValue('重复流程')
    bodyButton('创建').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('名称重复')
  })
})
