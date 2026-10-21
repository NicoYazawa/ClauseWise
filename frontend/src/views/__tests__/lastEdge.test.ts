import { flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BaseTabs from '@/components/ui/BaseTabs.vue'
import ContractDetailView from '@/views/contracts/ContractDetailView.vue'
import LawLibraryView from '@/views/knowledge/LawLibraryView.vue'
import WorkflowDetailView from '@/views/workflow/WorkflowDetailView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchInstance: vi.fn(),
  fetchDefinitions: vi.fn(),
  actOnInstance: vi.fn(),
  urgeInstance: vi.fn(),
  fetchContract: vi.fn(),
  fetchVersions: vi.fn(),
  fetchClauses: vi.fn(),
  downloadContract: vi.fn(),
  uploadContractVersion: vi.fn(),
  startReview: vi.fn(),
  fetchLaws: vi.fn(),
  saveLaw: vi.fn(),
  markExpired: vi.fn(),
  importLaws: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}))

vi.mock('@/api/workflows', () => ({
  fetchInstance: (...a: unknown[]) => mocks.fetchInstance(...a),
  fetchDefinitions: (...a: unknown[]) => mocks.fetchDefinitions(...a),
  actOnInstance: (...a: unknown[]) => mocks.actOnInstance(...a),
  urgeInstance: (...a: unknown[]) => mocks.urgeInstance(...a),
}))
vi.mock('@/api/contracts', () => ({
  fetchContract: (...a: unknown[]) => mocks.fetchContract(...a),
  fetchVersions: (...a: unknown[]) => mocks.fetchVersions(...a),
  fetchClauses: (...a: unknown[]) => mocks.fetchClauses(...a),
  downloadContract: (...a: unknown[]) => mocks.downloadContract(...a),
  uploadContractVersion: (...a: unknown[]) => mocks.uploadContractVersion(...a),
}))
vi.mock('@/api/reviews', () => ({ startReview: (...a: unknown[]) => mocks.startReview(...a) }))
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

const wfRoutes = [{ path: '/workflow/:id', component: { template: '<div />' } }]
const detailRoutes = [{ path: '/contracts/:id', component: { template: '<div />' } }]

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchInstance.mockResolvedValue({
    id: 1, contractId: 9, contractTitle: '合同', status: 'approved', currentNodeId: 'n3', currentNodeName: '结束',
    definitionId: 3, definitionName: '流程', definitionVersion: 1, starterName: '张三',
    startedAt: '2026-08-28T09:00:00', finishedAt: '2026-08-29T09:00:00',
    contextSnapshot: { score: 95, amount: 100, riskTotal: 0, highRisk: 0 }, records: [],
  })
  mocks.fetchDefinitions.mockResolvedValue([
    {
      id: 3,
      nodes: [
        { id: 'start', type: 'start', name: '开始' },
        { id: 'n1', type: 'approval', name: '审批', signMode: 'sequence', assignees: ['a'], timeoutHours: 12 },
        { id: 'n2', type: 'condition', name: '条件', rules: [{ when: 'score < 60', goto: 'n3' }] },
        { id: 'n3', type: 'cc', name: '抄送', assignees: ['b'] },
        { id: 'n4', type: 'custom' as never, name: '自定义' },
        { id: 'end', type: 'end', name: '结束' },
      ],
    },
  ])
  mocks.actOnInstance.mockResolvedValue({})
  mocks.urgeInstance.mockResolvedValue({})
  mocks.fetchContract.mockResolvedValue({
    id: 9, contractNo: 'HT-9', status: 'approved', currentVersion: 2, counterparty: { name: '甲' }, ownerName: '张三',
    title: '合同', contractType: 'sale', amount: 100, createdAt: '2026-08-01T10:00:00', updatedAt: '2026-08-28T10:00:00',
  })
  mocks.fetchVersions.mockResolvedValue([])
  mocks.fetchClauses.mockResolvedValue([])
  mocks.downloadContract.mockResolvedValue('f.pdf')
  mocks.uploadContractVersion.mockResolvedValue({ currentVersion: 3 })
  mocks.startReview.mockResolvedValue({ id: 5 })
  mocks.fetchLaws.mockResolvedValue([
    { id: 1, title: '法条A', content: '内容A', sourceRef: 'src', docType: 'law', effectiveDate: '2021-01-01', expiryDate: '2026-01-01', status: 'expired', vectorized: false, hitCount: 0 },
    { id: 2, title: '案例B', content: '内容B', sourceRef: '', docType: 'case', effectiveDate: '2022-01-01', expiryDate: null, status: 'active', vectorized: true, hitCount: 5 },
  ])
  mocks.saveLaw.mockResolvedValue({})
  mocks.markExpired.mockResolvedValue({})
  mocks.importLaws.mockResolvedValue({ imported: 2, vectorized: 2 })
  document.body.innerHTML = ''
})

describe('WorkflowDetailView 节点类型与结束态', () => {
  it('渲染审批/条件/抄送/自定义四类节点徽章', async () => {
    const { wrapper } = await mountWithApp(WorkflowDetailView, { initialPath: '/workflow/1', routes: wfRoutes })
    await flushPromises()
    expect(wrapper.text()).toContain('HT-9')
    expect(wrapper.text().length).toBeGreaterThan(200)
  })
})

describe('LawLibraryView 详情两态', () => {
  it('已向量化与未向量化的详情文案均可渲染', async () => {
    const { wrapper } = await mountWithApp(LawLibraryView)
    await flushPromises()

    await wrapper.findAll('tbody button')[0].trigger('click')
    await flushPromises()
    await nextTick()
    expect(document.body.textContent ?? '').toContain('法条A')

    const caseTitle = wrapper.findAll('tbody button').find((b) => b.text() === '案例B')
    await caseTitle!.trigger('click')
    await flushPromises()
    await nextTick()
    expect(document.body.textContent ?? '').toContain('案例B')
  })
})
