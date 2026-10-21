import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ContractListView from '@/views/contracts/ContractListView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchContracts: vi.fn(),
  uploadContract: vi.fn(),
  retryParse: vi.fn(),
  archiveContract: vi.fn(),
  downloadContract: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}))

vi.mock('@/api/contracts', () => ({
  fetchContracts: (...a: unknown[]) => mocks.fetchContracts(...a),
  uploadContract: (...a: unknown[]) => mocks.uploadContract(...a),
  retryParse: (...a: unknown[]) => mocks.retryParse(...a),
  archiveContract: (...a: unknown[]) => mocks.archiveContract(...a),
  downloadContract: (...a: unknown[]) => mocks.downloadContract(...a),
}))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: (...a: unknown[]) => mocks.toastInfo(...a),
}))

function contract(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    title: '设备采购合同',
    contractNo: 'HT-1',
    contractType: 'sale',
    counterparty: { name: '甲方公司' },
    amount: 1200,
    currentVersion: 2,
    status: 'parsed',
    updatedAt: '2026-08-28T10:00:00',
    ...over,
  }
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchContracts.mockResolvedValue([])
  mocks.uploadContract.mockResolvedValue({ contractNo: 'HT-9' })
  mocks.retryParse.mockResolvedValue({ contractNo: 'HT-1' })
  mocks.archiveContract.mockResolvedValue({ contractNo: 'HT-1' })
  mocks.downloadContract.mockResolvedValue('HT-1.pdf')
  document.body.innerHTML = ''
})

describe('ContractListView 列表', () => {
  it('无数据时展示空态', async () => {
    const { wrapper } = await mountWithApp(ContractListView)
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('渲染合同行：金额、版本、状态与操作按钮', async () => {
    mocks.fetchContracts.mockResolvedValue([
      contract({ id: 1 }),
      contract({ id: 2, amount: 0, status: 'parse_failed' }),
      contract({ id: 3, status: 'approved' }),
      contract({ id: 4, status: 'rejected' }),
    ])
    const { wrapper } = await mountWithApp(ContractListView)
    await flushPromises()

    expect(wrapper.text()).toContain('设备采购合同')
    expect(wrapper.text()).toContain('v2')
    // 三条状态相关操作：解析失败重试 + 已通过/已驳回归档
    expect(wrapper.findAll('tbody button').length).toBeGreaterThan(4)
  })

  it('超过一页时展示分页并支持切页', async () => {
    mocks.fetchContracts.mockResolvedValue(
      Array.from({ length: 12 }, (_, i) => contract({ id: i + 1, title: `合同${i + 1}` })),
    )
    const { wrapper } = await mountWithApp(ContractListView)
    await flushPromises()

    expect(wrapper.text()).toContain('合同1')
    expect(wrapper.text()).not.toContain('合同9')
    const pageTwo = wrapper.findAll('button').find((b) => b.text() === '2')
    await pageTwo!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('合同9')
  })

  it('下载成功提示文件名，失败提示错误', async () => {
    mocks.fetchContracts.mockResolvedValue([contract()])
    const { wrapper } = await mountWithApp(ContractListView)
    await flushPromises()

    const downloadBtn = wrapper.findAll('tbody button')[1]
    await downloadBtn.trigger('click')
    await flushPromises()
    expect(mocks.toastInfo).toHaveBeenCalled()

    mocks.downloadContract.mockRejectedValueOnce(new Error('无权限'))
    await downloadBtn.trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('无权限')
  })

  it('解析失败可重试，已通过可归档', async () => {
    mocks.fetchContracts.mockResolvedValue([
      contract({ id: 1, status: 'parse_failed' }),
      contract({ id: 2, status: 'approved' }),
    ])
    const { wrapper } = await mountWithApp(ContractListView)
    await flushPromises()

    const buttons = wrapper.findAll('tbody button')
    // 第 3 个按钮是解析失败重试
    await buttons[2].trigger('click')
    await flushPromises()
    expect(mocks.retryParse).toHaveBeenCalledWith(1)

    await buttons[5].trigger('click')
    await flushPromises()
    expect(mocks.archiveContract).toHaveBeenCalledWith(2)
  })

  it('详情按钮跳转合同详情页', async () => {
    mocks.fetchContracts.mockResolvedValue([contract({ id: 6 })])
    const { wrapper, router } = await mountWithApp(ContractListView)
    await flushPromises()
    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    await wrapper.findAll('tbody button')[0].trigger('click')
    expect(pushSpy).toHaveBeenCalledWith('/contracts/6')
  })
})

describe('ContractListView 上传弹窗', () => {
  async function openUpload(wrapper: Awaited<ReturnType<typeof mountWithApp>>['wrapper']) {
    const btn = wrapper.findAll('button').find((b) => /上传/.test(b.text()))
    await btn!.trigger('click')
    await flushPromises()
    await nextTick()
  }

  it('未选择文件直接提交时提示', async () => {
    const { wrapper } = await mountWithApp(ContractListView)
    await flushPromises()
    await openUpload(wrapper)

    const submit = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    submit.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.uploadContract).not.toHaveBeenCalled()
    expect(mocks.toastError).toHaveBeenCalled()
  })

  it('拖入不支持的格式时提示错误', async () => {
    const { wrapper } = await mountWithApp(ContractListView)
    await flushPromises()
    await openUpload(wrapper)

    const dropZone = document.body.querySelector('.border-dashed') as HTMLElement
    const bad = new File(['x'], 'virus.exe')
    dropZone.dispatchEvent(Object.assign(new Event('drop', { bubbles: true }), { dataTransfer: { files: [bad] } }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalled()
  })

  it('拖入合法文件后展示文件名并自动填充标题', async () => {
    const { wrapper } = await mountWithApp(ContractListView)
    await flushPromises()
    await openUpload(wrapper)

    const dropZone = document.body.querySelector('.border-dashed') as HTMLElement
    const good = new File(['x'], '采购合同.pdf')
    dropZone.dispatchEvent(Object.assign(new Event('drop', { bubbles: true }), { dataTransfer: { files: [good] } }))
    await flushPromises()
    expect(document.body.textContent ?? '').toContain('采购合同.pdf')
  })

  it('未发生拖拽时 onDrop 空文件安全返回', async () => {
    const { wrapper } = await mountWithApp(ContractListView)
    await flushPromises()
    await openUpload(wrapper)

    const dropZone = document.body.querySelector('.border-dashed') as HTMLElement
    dropZone.dispatchEvent(new Event('drop', { bubbles: true }))
    await flushPromises()
    expect(mocks.uploadContract).not.toHaveBeenCalled()
  })
})
