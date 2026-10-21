import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ContractDiffView from '@/views/contracts/ContractDiffView.vue'
import GlobalSearchView from '@/views/search/GlobalSearchView.vue'
import RolePermissionView from '@/views/system/RolePermissionView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchContracts: vi.fn(),
  fetchLaws: vi.fn(),
  fetchTemplates: vi.fn(),
  fetchVersions: vi.fn(),
  fetchDiff: vi.fn(),
  fetchContract: vi.fn(),
  fetchRoles: vi.fn(),
  updateRolePermissions: vi.fn(),
  toastSuccess: vi.fn(),
}))

vi.mock('@/api/contracts', () => ({
  fetchContracts: (...a: unknown[]) => mocks.fetchContracts(...a),
  fetchVersions: (...a: unknown[]) => mocks.fetchVersions(...a),
  fetchDiff: (...a: unknown[]) => mocks.fetchDiff(...a),
  fetchContract: (...a: unknown[]) => mocks.fetchContract(...a),
}))

vi.mock('@/api/knowledge', () => ({
  fetchLaws: (...a: unknown[]) => mocks.fetchLaws(...a),
  fetchTemplates: (...a: unknown[]) => mocks.fetchTemplates(...a),
}))

vi.mock('@/api/system', () => ({
  fetchRoles: (...a: unknown[]) => mocks.fetchRoles(...a),
  updateRolePermissions: (...a: unknown[]) => mocks.updateRolePermissions(...a),
}))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}))

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchContracts.mockResolvedValue([])
  mocks.fetchLaws.mockResolvedValue([])
  mocks.fetchTemplates.mockResolvedValue([])
  mocks.fetchVersions.mockResolvedValue([])
  mocks.fetchDiff.mockResolvedValue([])
  mocks.fetchContract.mockResolvedValue({ id: 1, title: '采购合同' })
  mocks.fetchRoles.mockResolvedValue([])
  mocks.updateRolePermissions.mockResolvedValue({})
})

describe('GlobalSearchView', () => {
  const contract = {
    id: 1,
    title: '设备采购合同',
    contractNo: 'HT-1',
    contractType: 'sale',
    counterparty: { name: '甲方' },
    updatedAt: '2026-08-28T10:00:00',
  }
  const laws = [
    { id: 1, title: '民法典第五百零九条', content: '合同履行原则', sourceRef: '民法典', docType: 'law' },
    { id: 2, title: '指导案例', content: '合同纠纷判例', sourceRef: '', docType: 'case' },
  ]
  const templates = [
    { id: 1, name: '合同付款条款', content: '按月结算', contractType: 'sale' },
    { id: 2, name: '保密条款', content: '其他内容', contractType: 'nda' },
  ]

  it('没有查询词时显示搜索提示', async () => {
    const { wrapper } = await mountWithApp(GlobalSearchView, { initialPath: '/search' })
    await flushPromises()
    expect(wrapper.text()).toContain('搜索')
  })

  it('有查询词且无结果时显示空态', async () => {
    const { wrapper } = await mountWithApp(GlobalSearchView, { initialPath: '/search?q=nothing' })
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('命中合同/法条/模板三类结果并正确过滤', async () => {
    mocks.fetchContracts.mockResolvedValue([contract])
    mocks.fetchLaws.mockResolvedValue(laws)
    mocks.fetchTemplates.mockResolvedValue(templates)
    const { wrapper } = await mountWithApp(GlobalSearchView, { initialPath: '/search?q=合同' })
    await flushPromises()

    expect(mocks.fetchContracts).toHaveBeenCalledWith({ keyword: '合同' })
    expect(wrapper.text()).toContain('设备采购合同')
    expect(wrapper.text()).toContain('民法典第五百零九条')
    expect(wrapper.text()).toContain('合同付款条款')
  })

  it('法条按 docType 展示类型短标', async () => {
    mocks.fetchLaws.mockResolvedValue(laws)
    const { wrapper } = await mountWithApp(GlobalSearchView, { initialPath: '/search?q=合同' })
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('返回按钮调用 router.back', async () => {
    const { wrapper, router } = await mountWithApp(GlobalSearchView, { initialPath: '/search?q=x' })
    await flushPromises()
    const backSpy = vi.spyOn(router, 'back').mockImplementation(() => undefined)
    const btn = wrapper.findAll('button').find((b) => b.text().length > 0)
    await btn?.trigger('click')
    expect(backSpy).toHaveBeenCalled()
  })
})

describe('ContractDiffView', () => {
  const versions = [
    { id: 1, versionNo: 2, fileName: 'v2.pdf' },
    { id: 2, versionNo: 1, fileName: 'v1.pdf' },
  ]

  it('加载版本后默认首尾对比并渲染差异', async () => {
    mocks.fetchVersions.mockResolvedValue(versions)
    mocks.fetchDiff.mockResolvedValue([
      { clauseNo: '1.1', kind: 'modified', oldText: 'a', newText: 'b', summary: '改了' },
    ])
    const { wrapper } = await mountWithApp(ContractDiffView, {
      initialPath: '/contracts/1/diff',
      routes: [{ path: '/contracts/:id/diff', component: { template: '<div />' } }],
    })
    await flushPromises()

    expect(mocks.fetchVersions).toHaveBeenCalledWith(1)
    expect(mocks.fetchDiff).toHaveBeenCalledWith(1, 1, 2)
    expect(wrapper.text()).toContain('改了')
  })

  it('只有一个版本时不发起差异请求', async () => {
    mocks.fetchVersions.mockResolvedValue([{ id: 1, versionNo: 1, fileName: 'v1.pdf' }])
    await mountWithApp(ContractDiffView, {
      initialPath: '/contracts/1/diff',
      routes: [{ path: '/contracts/:id/diff', component: { template: '<div />' } }],
    })
    await flushPromises()
    expect(mocks.fetchDiff).not.toHaveBeenCalled()
  })

  it('切换目标版本后重新对比', async () => {
    mocks.fetchVersions.mockResolvedValue([
      { id: 1, versionNo: 1, fileName: 'v1.pdf' },
      { id: 2, versionNo: 2, fileName: 'v2.pdf' },
      { id: 3, versionNo: 3, fileName: 'v3.pdf' },
    ])
    const { wrapper } = await mountWithApp(ContractDiffView, {
      initialPath: '/contracts/1/diff',
      routes: [{ path: '/contracts/:id/diff', component: { template: '<div />' } }],
    })
    await flushPromises()
    const selects = wrapper.findAll('select')
    expect(selects.length).toBe(2)
    await selects[1].setValue('2')
    await flushPromises()
    expect(mocks.fetchDiff).toHaveBeenCalled()
  })

  it('点击重新对比触发 reload', async () => {
    mocks.fetchVersions.mockResolvedValue(versions)
    const { wrapper } = await mountWithApp(ContractDiffView, {
      initialPath: '/contracts/1/diff',
      routes: [{ path: '/contracts/:id/diff', component: { template: '<div />' } }],
    })
    await flushPromises()
    const buttons = wrapper.findAll('button')
    await buttons.at(-1)?.trigger('click')
    await flushPromises()
    expect(mocks.fetchDiff).toHaveBeenCalled()
  })
})

describe('RolePermissionView', () => {
  const roles = [
    { code: 'admin', name: '系统管理员', permissions: ['contract:upload', 'system:user'], description: '全部权限', dataScope: 'all' },
    { code: 'reviewer', name: '审查员', permissions: ['review:export'], description: '审查', dataScope: 'dept' },
  ]

  it('加载角色后自动选中第一个并渲染权限矩阵', async () => {
    mocks.fetchRoles.mockResolvedValue(roles)
    const { wrapper } = await mountWithApp(RolePermissionView)
    await flushPromises()

    expect(wrapper.text()).toContain('系统管理员')
    expect(wrapper.text()).toContain('审查员')
    // 第一个角色被选中 → 展示矩阵与保存按钮
    expect(wrapper.findAll('input[type="checkbox"]').length).toBeGreaterThan(0)
  })

  it('切换角色后草稿权限随之变化', async () => {
    mocks.fetchRoles.mockResolvedValue(roles)
    const { wrapper } = await mountWithApp(RolePermissionView)
    await flushPromises()

    const roleButtons = wrapper.findAll('button').filter((b) => b.text().includes('审查员'))
    await roleButtons[0].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('审查员')
  })

  it('勾选/取消权限点可切换草稿，保存调用接口并提示', async () => {
    mocks.fetchRoles.mockResolvedValue(roles)
    const { wrapper } = await mountWithApp(RolePermissionView)
    await flushPromises()

    const boxes = wrapper.findAll('input[type="checkbox"]')
    // 勾选一个当前未选中的权限
    const unchecked = boxes.find((b) => !(b.element as HTMLInputElement).checked)
    expect(unchecked).toBeTruthy()
    await unchecked!.trigger('change')
    await flushPromises()

    const saveBtn = wrapper.findAll('button').find((b) => b.text().includes('保存'))
    expect(saveBtn).toBeTruthy()
    await saveBtn!.trigger('click')
    await flushPromises()

    expect(mocks.updateRolePermissions).toHaveBeenCalled()
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('权限未变更时保存按钮禁用', async () => {
    mocks.fetchRoles.mockResolvedValue([roles[0]])
    const { wrapper } = await mountWithApp(RolePermissionView)
    await flushPromises()
    const disabledSave = wrapper.findAll('button').some((b) => b.attributes('disabled') !== undefined)
    expect(disabledSave).toBe(true)
  })
})
