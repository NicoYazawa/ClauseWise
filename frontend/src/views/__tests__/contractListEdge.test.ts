import { flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BaseInput from '@/components/ui/BaseInput.vue'
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

const contract = {
  id: 1,
  title: '设备采购合同',
  contractNo: 'HT-1',
  contractType: 'sale',
  counterparty: { name: '甲方' },
  amount: 1200,
  currentVersion: 2,
  status: 'parsed',
  updatedAt: '2026-08-28T10:00:00',
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchContracts.mockResolvedValue([contract])
  mocks.uploadContract.mockResolvedValue({ contractNo: 'HT-9' })
  mocks.retryParse.mockResolvedValue({ contractNo: 'HT-1' })
  mocks.archiveContract.mockResolvedValue({ contractNo: 'HT-1' })
  mocks.downloadContract.mockResolvedValue('HT-1.pdf')
  document.body.innerHTML = ''
})

async function openUpload() {
  const res = await mountWithApp(ContractListView)
  await flushPromises()
  const btn = res.wrapper.findAll('button').find((b) => /上传/.test(b.text()))
  await btn!.trigger('click')
  await flushPromises()
  await nextTick()
  return res
}

function dropFile(file: File) {
  const zone = document.body.querySelector('.border-dashed') as HTMLElement
  zone.dispatchEvent(Object.assign(new Event('drop', { bubbles: true }), { dataTransfer: { files: [file] } }))
}

function submitBtn(): HTMLButtonElement {
  return Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
}

describe('ContractListView 上传校验与提交', () => {
  it('超过 50MB 的文件被拒绝', async () => {
    await openUpload()
    const big = new File(['x'], 'big.pdf')
    Object.defineProperty(big, 'size', { value: 51 * 1024 * 1024 })
    dropFile(big)
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalled()
  })

  it('已选文件但标题为空时提示', async () => {
    const { wrapper } = await openUpload()
    dropFile(new File(['x'], '合同.pdf'))
    await flushPromises()

    const inputs = wrapper.findAllComponents(BaseInput)
    inputs[0].vm.$emit('update:modelValue', '')
    await flushPromises()
    submitBtn().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.uploadContract).not.toHaveBeenCalled()
    expect(mocks.toastError).toHaveBeenCalled()
  })

  it('完整填写后上传成功并提示', async () => {
    const { wrapper } = await openUpload()
    dropFile(new File(['x'], '采购合同.pdf'))
    await flushPromises()

    const inputs = wrapper.findAllComponents(BaseInput)
    inputs[0].vm.$emit('update:modelValue', '采购合同')
    inputs[1].vm.$emit('update:modelValue', '12000')
    inputs[2].vm.$emit('update:modelValue', '甲方公司')
    await flushPromises()

    submitBtn().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('上传失败提示后端错误', async () => {
    mocks.uploadContract.mockRejectedValue(new Error('文件解析失败'))
    const { wrapper } = await openUpload()
    dropFile(new File(['x'], '合同.pdf'))
    await flushPromises()

    const inputs = wrapper.findAllComponents(BaseInput)
    inputs[2].vm.$emit('update:modelValue', '甲方')
    await flushPromises()
    submitBtn().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('文件解析失败')
  })

  it('重试解析失败与归档失败分别提示', async () => {
    mocks.fetchContracts.mockResolvedValue([
      { ...contract, id: 1, status: 'parse_failed' },
      { ...contract, id: 2, status: 'approved' },
    ])
    mocks.retryParse.mockRejectedValue(new Error('重试失败'))
    mocks.archiveContract.mockRejectedValue(new Error('归档失败'))
    const { wrapper } = await mountWithApp(ContractListView)
    await flushPromises()

    const buttons = wrapper.findAll('tbody button')
    await buttons[2].trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('重试失败')

    await buttons[5].trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('归档失败')
  })
})
