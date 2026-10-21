import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReviewTaskListView from '@/views/review/ReviewTaskListView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchTasks: vi.fn(),
  startReview: vi.fn(),
  fetchContracts: vi.fn(),
  fetchVersions: vi.fn(),
  fetchClauses: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/api/reviews', () => ({
  fetchTasks: (...a: unknown[]) => mocks.fetchTasks(...a),
  startReview: (...a: unknown[]) => mocks.startReview(...a),
}))

vi.mock('@/api/contracts', () => ({
  fetchContracts: (...a: unknown[]) => mocks.fetchContracts(...a),
  fetchVersions: (...a: unknown[]) => mocks.fetchVersions(...a),
  fetchClauses: (...a: unknown[]) => mocks.fetchClauses(...a),
}))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: vi.fn(),
}))

function task(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    contractTitle: '设备采购合同',
    taskType: 'full',
    status: 'completed',
    progress: 100,
    modelVersion: 'contract-review',
    promptVersion: 'v3',
    durationMs: 4200,
    createdAt: new Date(2026, 7, 28, 9, 0).toISOString(),
    ...over,
  }
}

async function openStartModal(wrapper: Awaited<ReturnType<typeof mountWithApp>>['wrapper']) {
  const btn = wrapper.findAll('button').find((b) => /新建|发起/.test(b.text()))
  await btn!.trigger('click')
  await flushPromises()
  await nextTick()
}

function submitButton(): HTMLButtonElement {
  return Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchTasks.mockResolvedValue([])
  mocks.startReview.mockResolvedValue({ id: 9 })
  mocks.fetchContracts.mockResolvedValue([
    { id: 1, contractNo: 'HT-1', title: '合同A', status: 'parsed' },
    { id: 2, contractNo: 'HT-2', title: '合同B', status: 'draft' },
  ])
  mocks.fetchVersions.mockResolvedValue([
    { id: 12, versionNo: 2, fileName: 'v2.pdf', parseStatus: 'parsed' },
    { id: 11, versionNo: 1, fileName: 'v1.pdf', parseStatus: 'parsed' },
  ])
  mocks.fetchClauses.mockResolvedValue([
    { id: 1, clauseNo: '3.2', clauseType: 'payment', content: '付款条款内容很长的文本片段用于展示' },
  ])
  document.body.innerHTML = ''
})

describe('ReviewTaskListView 任务列表', () => {
  it('无任务时展示空态', async () => {
    const { wrapper } = await mountWithApp(ReviewTaskListView)
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('完成/运行中/失败/待处理状态分别渲染操作列', async () => {
    mocks.fetchTasks.mockResolvedValue([
      task({ id: 1, status: 'completed' }),
      task({ id: 2, status: 'running', progress: 40 }),
      task({ id: 3, status: 'failed', errorMsg: '模型超时' }),
      task({ id: 4, status: 'pending' }),
      task({ id: 5, clauseNo: '3.2', taskType: 'clause' }),
    ])
    const { wrapper } = await mountWithApp(ReviewTaskListView)
    await flushPromises()

    expect(wrapper.text()).toContain('设备采购合同')
    expect(wrapper.text()).toContain('模型超时')
    expect(wrapper.text()).toContain('3.2')
  })

  it('失败任务点击查看详情弹出错误提示', async () => {
    mocks.fetchTasks.mockResolvedValue([task({ id: 3, status: 'failed', errorMsg: '模型超时' })])
    const { wrapper } = await mountWithApp(ReviewTaskListView)
    await flushPromises()
    const failBtn = wrapper.findAll('tbody button').at(-1)
    await failBtn?.trigger('click')
    expect(mocks.toastError).toHaveBeenCalled()
  })

  it('完成任务点击查看报告跳转详情', async () => {
    mocks.fetchTasks.mockResolvedValue([task({ id: 7, status: 'completed' })])
    const { wrapper, router } = await mountWithApp(ReviewTaskListView)
    await flushPromises()
    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    const reportBtn = wrapper.findAll('button').find((b) => /报告/.test(b.text()))
    await reportBtn!.trigger('click')
    expect(pushSpy).toHaveBeenCalledWith('/review/7')
  })
})

describe('ReviewTaskListView 新建审查弹窗', () => {
  it('打开弹窗后加载可选合同（仅已解析/已审状态）', async () => {
    const { wrapper } = await mountWithApp(ReviewTaskListView)
    await flushPromises()
    await openStartModal(wrapper)

    expect(mocks.fetchContracts).toHaveBeenCalled()
    const text = document.body.textContent ?? ''
    expect(text).toContain('HT-1')
    expect(text).not.toContain('HT-2')
  })

  it('未选择合同提交时提示', async () => {
    const { wrapper } = await mountWithApp(ReviewTaskListView)
    await flushPromises()
    await openStartModal(wrapper)

    submitButton().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.startReview).not.toHaveBeenCalled()
    expect(mocks.toastError).toHaveBeenCalled()
  })

  it('选择合同后加载版本，增量审查缺基准版本时提示', async () => {
    const { wrapper } = await mountWithApp(ReviewTaskListView)
    await flushPromises()
    await openStartModal(wrapper)

    const contractSelect = document.body.querySelector('select')!
    await new DOMWrapper(contractSelect).setValue('1')
    await flushPromises()
    expect(mocks.fetchVersions).toHaveBeenCalledWith(1)

    const typeButtons = document.body.querySelectorAll('.grid-cols-3 button')
    ;(typeButtons[2] as HTMLButtonElement).dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    await nextTick()

    submitButton().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalled()
  })

  it('单条款审查缺条款时提示，选中条款后显示内容片段', async () => {
    const { wrapper } = await mountWithApp(ReviewTaskListView)
    await flushPromises()
    await openStartModal(wrapper)

    await new DOMWrapper(document.body.querySelector('select')!).setValue('1')
    await flushPromises()
    expect(mocks.fetchClauses).toHaveBeenCalled()

    const typeButtons = document.body.querySelectorAll('.grid-cols-3 button')
    ;(typeButtons[1] as HTMLButtonElement).dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    await nextTick()

    submitButton().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalled()

    const clauseSelect = document.body.querySelectorAll('select')[1]
    await new DOMWrapper(clauseSelect).setValue('3.2')
    await flushPromises()
    expect(document.body.textContent ?? '').toContain('付款条款')
  })

  it('提交成功创建任务并跳转详情', async () => {
    const { wrapper, router } = await mountWithApp(ReviewTaskListView)
    await flushPromises()
    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    await openStartModal(wrapper)

    await new DOMWrapper(document.body.querySelector('select')!).setValue('1')
    await flushPromises()
    submitButton().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(mocks.startReview).toHaveBeenCalledWith(expect.objectContaining({ contractId: 1, taskType: 'full' }))
    expect(mocks.toastSuccess).toHaveBeenCalled()
    expect(pushSpy).toHaveBeenCalledWith('/review/9')
  })

  it('创建失败时提示错误信息', async () => {
    mocks.startReview.mockRejectedValue(new Error('工程已满'))
    const { wrapper } = await mountWithApp(ReviewTaskListView)
    await flushPromises()
    await openStartModal(wrapper)

    await new DOMWrapper(document.body.querySelector('select')!).setValue('1')
    await flushPromises()
    submitButton().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(mocks.toastError).toHaveBeenCalledWith('工程已满')
  })
})
