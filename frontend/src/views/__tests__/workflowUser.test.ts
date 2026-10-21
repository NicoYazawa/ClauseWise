import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import UserManagementView from '@/views/system/UserManagementView.vue'
import WorkflowDetailView from '@/views/workflow/WorkflowDetailView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchInstance: vi.fn(),
  fetchDefinitions: vi.fn(),
  actOnInstance: vi.fn(),
  urgeInstance: vi.fn(),
  fetchContract: vi.fn(),
  fetchUsers: vi.fn(),
  fetchRoles: vi.fn(),
  toggleUser: vi.fn(),
  updateUserRoles: vi.fn(),
  createUser: vi.fn(),
  resetPassword: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/api/workflows', () => ({
  fetchInstance: (...a: unknown[]) => mocks.fetchInstance(...a),
  fetchDefinitions: (...a: unknown[]) => mocks.fetchDefinitions(...a),
  actOnInstance: (...a: unknown[]) => mocks.actOnInstance(...a),
  urgeInstance: (...a: unknown[]) => mocks.urgeInstance(...a),
}))

vi.mock('@/api/contracts', () => ({ fetchContract: (...a: unknown[]) => mocks.fetchContract(...a) }))

vi.mock('@/api/system', () => ({
  fetchUsers: (...a: unknown[]) => mocks.fetchUsers(...a),
  fetchRoles: (...a: unknown[]) => mocks.fetchRoles(...a),
  toggleUser: (...a: unknown[]) => mocks.toggleUser(...a),
  updateUserRoles: (...a: unknown[]) => mocks.updateUserRoles(...a),
  createUser: (...a: unknown[]) => mocks.createUser(...a),
  resetPassword: (...a: unknown[]) => mocks.resetPassword(...a),
}))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: vi.fn(),
}))

function instance(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    contractId: 9,
    contractTitle: '设备采购合同',
    status: 'running',
    currentNodeId: 'n1',
    currentNodeName: '部门经理审批',
    definitionId: 3,
    definitionName: '标准合同审批流',
    definitionVersion: 2,
    starterName: '张三',
    startedAt: '2026-08-28T09:00:00',
    finishedAt: null,
    contextSnapshot: { score: 90, amount: 12000, riskTotal: 3, highRisk: 1 },
    records: [
      { nodeName: '提交申请', action: 'submit', operatorName: '张三', comment: '提交', createdAt: '2026-08-28T09:00:00' },
      { nodeName: '部门经理审批', action: 'approve', operatorName: '李四', comment: '同意', createdAt: '2026-08-28T10:00:00' },
    ],
    ...over,
  }
}

function definition() {
  return {
    id: 3,
    nodes: [
      { id: 'start', type: 'start', name: '开始' },
      { id: 'n1', type: 'approval', name: '部门经理审批', signMode: 'or', assignees: ['a'] },
      { id: 'n2', type: 'condition', name: '金额判断' },
      { id: 'n3', type: 'cc', name: '抄送法务' },
      { id: 'end', type: 'end', name: '结束' },
    ],
  }
}

function user(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    username: 'zhangsan',
    realName: '张三',
    deptName: '法务部',
    title: '专员',
    phone: '13812345678',
    roles: ['reviewer'],
    isActive: true,
    lastLoginAt: '2026-08-28T10:00:00',
    ...over,
  }
}

const wfRoutes = [{ path: '/workflow/:id', component: { template: '<div />' } }]

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchInstance.mockResolvedValue(instance())
  mocks.fetchDefinitions.mockResolvedValue([definition()])
  mocks.actOnInstance.mockResolvedValue({})
  mocks.urgeInstance.mockResolvedValue({})
  mocks.fetchContract.mockResolvedValue({
    id: 9,
    contractNo: 'HT-9',
    status: 'under_review',
    currentVersion: 2,
    counterparty: { name: '甲方' },
    ownerName: '张三',
  })
  mocks.fetchUsers.mockResolvedValue([])
  mocks.fetchRoles.mockResolvedValue([])
  mocks.toggleUser.mockResolvedValue({})
  mocks.updateUserRoles.mockResolvedValue({})
  mocks.createUser.mockResolvedValue({ username: 'newuser' })
  mocks.resetPassword.mockResolvedValue({ username: 'zhangsan' })
  document.body.innerHTML = ''
})

describe('WorkflowDetailView', () => {
  it('运行中实例展示节点流程、上下文与审批区', async () => {
    const { wrapper } = await mountWithApp(WorkflowDetailView, { initialPath: '/workflow/1', routes: wfRoutes })
    await flushPromises()

    expect(wrapper.text()).toContain('设备采购合同')
    expect(wrapper.text()).toContain('12,000')
    expect(wrapper.text()).toContain('HT-9')
  })

  it('已结束实例展示结果说明而非审批区', async () => {
    for (const status of ['approved', 'rejected', 'withdrawn'] as const) {
      mocks.fetchInstance.mockResolvedValue(
        instance({ status, finishedAt: '2026-08-29T10:00:00' }),
      )
      const { wrapper } = await mountWithApp(WorkflowDetailView, { initialPath: '/workflow/1', routes: wfRoutes })
      await flushPromises()
      expect(wrapper.find('textarea').exists()).toBe(false)
      wrapper.unmount()
    }
  })

  it('同意动作可直接提交，驳回必须填写意见', async () => {
    const { wrapper } = await mountWithApp(WorkflowDetailView, { initialPath: '/workflow/1', routes: wfRoutes })
    await flushPromises()

    // 默认同意，直接点击确认提交
    const confirm = () => wrapper.findAll('button').find((b) => /确认/.test(b.text()))
    await confirm()!.trigger('click')
    await flushPromises()
    expect(mocks.actOnInstance).toHaveBeenCalled()

    // 切到驳回且不填意见 → 提示
    const rejectBtn = wrapper.findAll('button').find((b) => /驳回/.test(b.text()))
    if (rejectBtn) {
      await rejectBtn.trigger('click')
      await confirm()!.trigger('click')
      await flushPromises()
      expect(mocks.toastError).toHaveBeenCalled()
    }
  })

  it('填写意见后驳回提交成功', async () => {
    const { wrapper } = await mountWithApp(WorkflowDetailView, { initialPath: '/workflow/1', routes: wfRoutes })
    await flushPromises()

    const rejectBtn = wrapper.findAll('button').find((b) => /驳回/.test(b.text()))
    await rejectBtn!.trigger('click')
    await wrapper.find('textarea').setValue('条款风险过高')
    const submit = wrapper.findAll('button').at(-1)
    await submit!.trigger('click')
    await flushPromises()

    expect(mocks.actOnInstance).toHaveBeenCalledWith(1, 'reject', '条款风险过高', 'n1')
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('催办成功/失败均有提示', async () => {
    const { wrapper } = await mountWithApp(WorkflowDetailView, { initialPath: '/workflow/1', routes: wfRoutes })
    await flushPromises()

    const urge = () => wrapper.findAll('button').find((b) => /催办/.test(b.text()))
    await urge()!.trigger('click')
    await flushPromises()
    expect(mocks.urgeInstance).toHaveBeenCalledWith(1)

    mocks.urgeInstance.mockRejectedValue(new Error('节点已处理'))
    await urge()!.trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('节点已处理')
  })

  it('审批动作失败提示错误', async () => {
    mocks.actOnInstance.mockRejectedValue(new Error('实例已被他人处理'))
    const { wrapper } = await mountWithApp(WorkflowDetailView, { initialPath: '/workflow/1', routes: wfRoutes })
    await flushPromises()
    const confirm = wrapper.findAll('button').find((b) => /确认/.test(b.text()))
    await confirm!.trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('实例已被他人处理')
  })
})

describe('UserManagementView', () => {
  const roles = [
    { code: 'reviewer', name: '审查员', description: '审查合同' },
    { code: 'admin', name: '管理员', description: '全部权限' },
  ]

  it('渲染用户列表：角色、状态、脱敏手机号', async () => {
    mocks.fetchUsers.mockResolvedValue([user({ id: 1 }), user({ id: 2, username: 'lisi', realName: '李四', isActive: false })])
    mocks.fetchRoles.mockResolvedValue(roles)
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()

    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('李四')
    expect(wrapper.text()).toContain('138****5678')
    expect(wrapper.text()).toContain('审查员')
  })

  it('关键词过滤用户名/姓名/部门', async () => {
    mocks.fetchUsers.mockResolvedValue([
      user({ id: 1, realName: '张三', username: 'zhangsan', deptName: '法务部' }),
      user({ id: 2, realName: '李四', username: 'lisi', deptName: '采购部' }),
    ])
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()
    await wrapper.find('input').setValue('采购')
    await flushPromises()
    expect(wrapper.text()).toContain('李四')
    expect(wrapper.text()).not.toContain('张三')
  })

  it('启用/停用账号调用接口并提示', async () => {
    mocks.fetchUsers.mockResolvedValue([user({ id: 1, isActive: true })])
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()
    const toggleBtn = wrapper.findAll('tbody button').at(-1)
    await toggleBtn!.trigger('click')
    await flushPromises()
    expect(mocks.toggleUser).toHaveBeenCalledWith(1)
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('分配角色弹窗可勾选并保存', async () => {
    mocks.fetchUsers.mockResolvedValue([user({ id: 1 })])
    mocks.fetchRoles.mockResolvedValue(roles)
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()

    const assignBtn = wrapper.findAll('tbody button').find((b) => b.text().length > 0 && b.text().length < 8)
    await assignBtn!.trigger('click')
    await flushPromises()
    await nextTick()

    const boxes = document.body.querySelectorAll('input[type="checkbox"]')
    expect(boxes.length).toBeGreaterThan(0)
    ;(boxes[1] as HTMLInputElement).dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()

    const save = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    save.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.updateUserRoles).toHaveBeenCalled()
  })

  it('创建用户：切换角色并提交', async () => {
    mocks.fetchUsers.mockResolvedValue([])
    mocks.fetchRoles.mockResolvedValue(roles)
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()

    const createBtn = wrapper.findAll('button').find((b) => b.text().length > 0 && b.text().length < 8)
    await createBtn!.trigger('click')
    await flushPromises()
    await nextTick()

    const inputs = document.body.querySelectorAll('input:not([type="checkbox"])')
    await new DOMWrapper(inputs[0]).setValue('newuser')
    await new DOMWrapper(inputs[1]).setValue('新用户')
    const roleBtn = Array.from(document.body.querySelectorAll('button')).find((b) => /审查员/.test(b.textContent ?? ''))
    roleBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    const submit = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    submit.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.createUser).toHaveBeenCalledWith(expect.objectContaining({ username: 'newuser', roles: ['reviewer'] }))
  })

  it('重置密码确认后调用接口', async () => {
    mocks.fetchUsers.mockResolvedValue([user({ id: 1 })])
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()

    const resetBtn = wrapper.findAll('tbody button').at(-2)
    await resetBtn!.trigger('click')
    await flushPromises()
    await nextTick()

    const confirm = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    confirm.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.resetPassword).toHaveBeenCalledWith(1)
  })

  it('创建用户失败提示错误', async () => {
    mocks.fetchUsers.mockResolvedValue([])
    mocks.fetchRoles.mockResolvedValue(roles)
    mocks.createUser.mockRejectedValue(new Error('用户名已存在'))
    const { wrapper } = await mountWithApp(UserManagementView)
    await flushPromises()
    const createBtn = wrapper.findAll('button').find((b) => b.text().length > 0 && b.text().length < 8)
    await createBtn!.trigger('click')
    await flushPromises()
    await nextTick()
    const submit = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    submit.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('用户名已存在')
  })
})
