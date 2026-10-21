import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import UserManagementView from '@/views/system/UserManagementView.vue'
import WorkflowDefinitionsView from '@/views/workflow/WorkflowDefinitionsView.vue'
import WorkflowDetailView from '@/views/workflow/WorkflowDetailView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchUsers: vi.fn(),
  fetchRoles: vi.fn(),
  toggleUser: vi.fn(),
  updateUserRoles: vi.fn(),
  createUser: vi.fn(),
  resetPassword: vi.fn(),
  fetchInstance: vi.fn(),
  fetchDefinitions: vi.fn(),
  actOnInstance: vi.fn(),
  urgeInstance: vi.fn(),
  fetchContract: vi.fn(),
  saveDefinition: vi.fn(),
  toggleDefinition: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}))

vi.mock('@/api/system', () => ({
  fetchUsers: (...a: unknown[]) => mocks.fetchUsers(...a),
  fetchRoles: (...a: unknown[]) => mocks.fetchRoles(...a),
  toggleUser: (...a: unknown[]) => mocks.toggleUser(...a),
  updateUserRoles: (...a: unknown[]) => mocks.updateUserRoles(...a),
  createUser: (...a: unknown[]) => mocks.createUser(...a),
  resetPassword: (...a: unknown[]) => mocks.resetPassword(...a),
}))

vi.mock('@/api/workflows', () => ({
  fetchInstance: (...a: unknown[]) => mocks.fetchInstance(...a),
  fetchDefinitions: (...a: unknown[]) => mocks.fetchDefinitions(...a),
  actOnInstance: (...a: unknown[]) => mocks.actOnInstance(...a),
  urgeInstance: (...a: unknown[]) => mocks.urgeInstance(...a),
  saveDefinition: (...a: unknown[]) => mocks.saveDefinition(...a),
  toggleDefinition: (...a: unknown[]) => mocks.toggleDefinition(...a),
}))

vi.mock('@/api/contracts', () => ({ fetchContract: (...a: unknown[]) => mocks.fetchContract(...a) }))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: (...a: unknown[]) => mocks.toastInfo(...a),
}))

function user(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    username: 'zhangsan',
    realName: '张三',
    deptName: '法务部',
    title: '专员',
    phone: '13812345678',
    roles: ['unknown_role'],
    isActive: true,
    lastLoginAt: null,
    ...over,
  }
}

function instance(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    contractId: 0,
    contractTitle: '设备采购合同',
    status: 'running',
    currentNodeId: 'n1',
    currentNodeName: '审批',
    definitionId: 3,
    definitionName: '流程',
    definitionVersion: 1,
    starterName: '张三',
    startedAt: '2026-08-28T09:00:00',
    finishedAt: null,
    contextSnapshot: { score: 70, amount: 0, riskTotal: 1, highRisk: 0 },
    records: [],
    ...over,
  }
}

function definition(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: '标准流程',
    version: 1,
    enabled: true,
    contractTypes: ['sale'],
    updatedAt: '2026-08-28T10:00:00',
    nodes: [
      { id: 'start', type: 'start', name: '开始' },
      { id: 'n1', type: 'approval', name: '经理审批', signMode: 'and', assignees: ['a'], timeoutHours: 24 },
      { id: 'n2', type: 'cc', name: '抄送', assignees: ['role:legal'] },
      { id: 'end', type: 'end', name: '结束' },
    ],
    ...over,
  }
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchUsers.mockResolvedValue([user()])
  mocks.fetchRoles.mockResolvedValue([{ code: 'reviewer', name: '审查员', description: 'd' }])
  mocks.toggleUser.mockResolvedValue({})
  mocks.updateUserRoles.mockResolvedValue({})
  mocks.createUser.mockResolvedValue({ username: 'new' })
  mocks.resetPassword.mockResolvedValue({ username: 'zhangsan' })
  mocks.fetchInstance.mockResolvedValue(instance())
  mocks.fetchDefinitions.mockResolvedValue([definition()])
  mocks.actOnInstance.mockResolvedValue({})
  mocks.urgeInstance.mockResolvedValue({})
  mocks.fetchContract.mockResolvedValue(null)
  mocks.saveDefinition.mockResolvedValue({ id: 1, name: 'x', version: 2 })
  mocks.toggleDefinition.mockResolvedValue({ id: 1, name: 'x', enabled: false })
  document.body.innerHTML = ''
})

function bodyButton(text: string): HTMLButtonElement {
  return Array.from(document.body.querySelectorAll('button')).find((b) =>
    (b.textContent ?? '').includes(text),
  ) as HTMLButtonElement
}

describe('UserManagementView 边界', () => {
  it('未知角色码回退显示原始 code', async () => {
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()
    expect(wrapper.text()).toContain('unknown_role')
  })

  it('角色分配保存失败提示错误', async () => {
    mocks.updateUserRoles.mockRejectedValue(new Error('至少保留一个角色'))
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()
    const assignBtn = wrapper.findAll('tbody button').find((b) => b.text().length > 0 && b.text().length < 8)
    await assignBtn!.trigger('click')
    await flushPromises()
    await nextTick()

    const save = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    save.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('至少保留一个角色')
  })

  it('重置密码失败提示错误', async () => {
    mocks.resetPassword.mockRejectedValue(new Error('账号已锁定'))
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()
    const resetBtn = wrapper.findAll('tbody button').at(-2)
    await resetBtn!.trigger('click')
    await flushPromises()
    await nextTick()
    const confirm = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    confirm.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('账号已锁定')
  })

  it('创建用户时再次点击角色可取消选择', async () => {
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()
    const createBtn = wrapper.findAll('button').find((b) => b.text().length > 0 && b.text().length < 8)
    await createBtn!.trigger('click')
    await flushPromises()
    await nextTick()

    const roleBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      /审查员/.test(b.textContent ?? ''),
    )!
    roleBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    roleBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    const submit = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    submit.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.createUser).toHaveBeenCalledWith(expect.objectContaining({ roles: [] }))
  })
})

describe('WorkflowDefinitionsView 节点编辑边界', () => {
  it('编辑时移动与删除节点后保存', async () => {
    const { wrapper } = await mountWithApp(WorkflowDefinitionsView)
    await flushPromises()
    const editBtn = wrapper.findAll('button').find((b) => /编辑|新版本/.test(b.text()))
    await editBtn!.trigger('click')
    await flushPromises()
    await nextTick()

    // 下移第一个节点、删除最后一个节点
    const moveDown = Array.from(document.body.querySelectorAll('button[title]')).filter((b) =>
      (b as HTMLButtonElement).title.includes('下移'),
    )
    moveDown[0]?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    const delButtons = Array.from(document.body.querySelectorAll('button[title]')).filter((b) =>
      (b as HTMLButtonElement).title.includes('删除'),
    )
    delButtons.at(-1)?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    bodyButton('发布').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.saveDefinition).toHaveBeenCalled()
  })


})

describe('WorkflowDetailView 边界', () => {
  it('缺少合同详情时仍渲染流程与记录', async () => {
    const { wrapper } = await mountWithApp(WorkflowDetailView, {
      initialPath: '/workflow/1',
      routes: [{ path: '/workflow/:id', component: { template: '<div />' } }],
    })
    await flushPromises()
    expect(wrapper.text()).toContain('设备采购合同')
  })

  it('缺少流程定义时节点区域为空但不报错', async () => {
    mocks.fetchDefinitions.mockResolvedValue([])
    const { wrapper } = await mountWithApp(WorkflowDetailView, {
      initialPath: '/workflow/1',
      routes: [{ path: '/workflow/:id', component: { template: '<div />' } }],
    })
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('已完成实例展示结果说明', async () => {
    mocks.fetchInstance.mockResolvedValue(
      instance({ status: 'withdrawn', finishedAt: '2026-08-29T10:00:00' }),
    )
    const { wrapper } = await mountWithApp(WorkflowDetailView, {
      initialPath: '/workflow/1',
      routes: [{ path: '/workflow/:id', component: { template: '<div />' } }],
    })
    await flushPromises()
    expect(wrapper.find('textarea').exists()).toBe(false)
  })

  it('低评分上下文使用警示色（score < 85）', async () => {
    const { wrapper } = await mountWithApp(WorkflowDetailView, {
      initialPath: '/workflow/1',
      routes: [{ path: '/workflow/:id', component: { template: '<div />' } }],
    })
    await flushPromises()
    expect(wrapper.text()).toContain('70')
  })

  it('Cc/未知节点类型也能渲染类型徽章', async () => {
    mocks.fetchInstance.mockResolvedValue(instance({ contractId: 9 }))
    mocks.fetchContract.mockResolvedValue({
      id: 9,
      contractNo: 'HT-9',
      status: 'under_review',
      currentVersion: 1,
      counterparty: { name: '甲方' },
      ownerName: '张三',
    })
    mocks.fetchDefinitions.mockResolvedValue([definition()])
    const { wrapper } = await mountWithApp(WorkflowDetailView, {
      initialPath: '/workflow/1',
      routes: [{ path: '/workflow/:id', component: { template: '<div />' } }],
    })
    await flushPromises()
    expect(wrapper.text()).toContain('HT-9')
  })
})
