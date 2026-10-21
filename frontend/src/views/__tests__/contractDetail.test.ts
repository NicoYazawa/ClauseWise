import { flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ContractDetailView from '@/views/contracts/ContractDetailView.vue'
import BaseTabs from '@/components/ui/BaseTabs.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchContract: vi.fn(),
  fetchVersions: vi.fn(),
  fetchClauses: vi.fn(),
  downloadContract: vi.fn(),
  uploadContractVersion: vi.fn(),
  startReview: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}))

vi.mock('@/api/contracts', () => ({
  fetchContract: (...a: unknown[]) => mocks.fetchContract(...a),
  fetchVersions: (...a: unknown[]) => mocks.fetchVersions(...a),
  fetchClauses: (...a: unknown[]) => mocks.fetchClauses(...a),
  downloadContract: (...a: unknown[]) => mocks.downloadContract(...a),
  uploadContractVersion: (...a: unknown[]) => mocks.uploadContractVersion(...a),
}))

vi.mock('@/api/reviews', () => ({ startReview: (...a: unknown[]) => mocks.startReview(...a) }))

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
    status: 'parsed',
    currentVersion: 1,
    amount: 1200,
    ownerName: '张三',
    counterparty: { name: '甲方公司', idNo: '91110100MA00X0Y0Z0', phone: '13812345678' },
    createdAt: '2026-08-01T10:00:00',
    updatedAt: '2026-08-28T10:00:00',
    ...over,
  }
}

function version(over: Record<string, unknown> = {}) {
  return {
    id: 11,
    versionNo: 1,
    fileName: 'v1.pdf',
    fileSizeKb: 2048,
    createdAt: '2026-08-01T10:00:00',
    parseStatus: 'parsed',
    parseChannel: 'text',
    parentId: null,
    ...over,
  }
}

const routes = [{ path: '/contracts/:id', component: { template: '<div />' } }]

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchContract.mockResolvedValue(contract())
  mocks.fetchVersions.mockResolvedValue([version()])
  mocks.fetchClauses.mockResolvedValue([])
  mocks.downloadContract.mockResolvedValue('HT-1.pdf')
  mocks.uploadContractVersion.mockResolvedValue({ currentVersion: 2 })
  mocks.startReview.mockResolvedValue({ id: 5 })
  document.body.innerHTML = ''
})

async function mountDetail() {
  const res = await mountWithApp(ContractDetailView, { initialPath: '/contracts/1', routes })
  await flushPromises()
  return res
}

describe('ContractDetailView 基本信息', () => {
  it('加载中展示转圈，加载后展示合同信息', async () => {
    const { wrapper } = await mountDetail()
    expect(wrapper.text()).toContain('设备采购合同')
    expect(wrapper.text()).toContain('甲方公司')
    expect(wrapper.text()).toContain('v1')
  })

  it('金额为 0 时展示破折号，脱敏展示证件与手机号', async () => {
    mocks.fetchContract.mockResolvedValue(contract({ amount: 0 }))
    const { wrapper } = await mountDetail()
    expect(wrapper.text()).toContain('—')
    expect(wrapper.text()).toContain('138****5678')
    expect(wrapper.text()).toContain('*')
  })

  it('条款为空时展示空态，有条款时展示条款内容', async () => {
    const { wrapper } = await mountDetail()
    expect(wrapper.text().length).toBeGreaterThan(0)

    mocks.fetchClauses.mockResolvedValue([
      { id: 1, clauseNo: '3.2', clauseType: 'payment', content: '按月结算货款', pageNo: 2 },
    ])
    const { wrapper: withClauses } = await mountDetail()
    expect(withClauses.text()).toContain('3.2')
    expect(withClauses.text()).toContain('按月结算货款')
  })

  it('可发起审查的状态才展示发起按钮；多版本时展示增量审查', async () => {
    const { wrapper } = await mountDetail()
    expect(wrapper.findAll('button').some((b) => /审查/.test(b.text()))).toBe(true)

    mocks.fetchContract.mockResolvedValue(contract({ status: 'draft' }))
    const { wrapper: draft } = await mountDetail()
    expect(draft.findAll('button').some((b) => /审查/.test(b.text()))).toBe(false)
  })
})

describe('ContractDetailView 版本与下载', () => {
  it('切换版本标签展示版本链、解析渠道与修订来源', async () => {
    mocks.fetchVersions.mockResolvedValue([
      version({ id: 12, versionNo: 2, fileName: 'v2.pdf', parentId: 11 }),
      version({ id: 11, versionNo: 1, parseChannel: null }),
    ])
    mocks.fetchContract.mockResolvedValue(contract({ currentVersion: 2 }))
    const { wrapper } = await mountDetail()

    wrapper.findComponent(BaseTabs).vm.$emit('update:modelValue', 'versions')
    await flushPromises()

    expect(wrapper.text()).toContain('v2.pdf')
    expect(wrapper.text()).toContain('2.0 MB')
    expect(wrapper.text()).toContain('v1.pdf')
  })

  it('多版本时展示版本差异入口，点击跳转', async () => {
    mocks.fetchVersions.mockResolvedValue([version({ id: 12, versionNo: 2 }), version()])
    const { wrapper, router } = await mountDetail()
    wrapper.findComponent(BaseTabs).vm.$emit('update:modelValue', 'versions')
    await flushPromises()

    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    const diffBtn = wrapper.findAll('button').find((b) => /差异|对比/.test(b.text()))
    expect(diffBtn).toBeTruthy()
    await diffBtn!.trigger('click')
    expect(pushSpy).toHaveBeenCalledWith('/contracts/1/diff')
  })

  it('点击版本项切换当前版本', async () => {
    mocks.fetchVersions.mockResolvedValue([version({ id: 12, versionNo: 2 }), version()])
    const { wrapper } = await mountDetail()
    wrapper.findComponent(BaseTabs).vm.$emit('update:modelValue', 'versions')
    await flushPromises()

    const rows = wrapper.findAll('.cursor-pointer')
    await rows.at(-1)?.trigger('click')
    await flushPromises()
    expect(mocks.fetchClauses).toHaveBeenCalled()
  })

  it('下载原件成功后提示文件名', async () => {
    const { wrapper } = await mountDetail()
    const downloadBtn = wrapper.findAll('button').find((b) => /下载/.test(b.text()))
    await downloadBtn!.trigger('click')
    await flushPromises()
    expect(mocks.downloadContract).toHaveBeenCalledWith(1)
    expect(mocks.toastInfo).toHaveBeenCalled()
  })
})

describe('ContractDetailView 发起审查', () => {
  it('单版本发起全文审查并跳转报告', async () => {
    const { wrapper, router } = await mountDetail()
    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    const reviewBtn = wrapper.findAll('button').find((b) => /审查/.test(b.text()))
    await reviewBtn!.trigger('click')
    await flushPromises()

    expect(mocks.startReview).toHaveBeenCalledWith({ contractId: 1, taskType: 'full' })
    expect(pushSpy).toHaveBeenCalledWith('/review/5')
  })

  it('发起失败提示错误', async () => {
    mocks.startReview.mockRejectedValue(new Error('报告过期'))
    const { wrapper } = await mountDetail()
    await wrapper.findAll('button').find((b) => /审查/.test(b.text()))!.trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('报告过期')
  })
})

describe('ContractDetailView 上传新版本', () => {
  async function openUpload(wrapper: Awaited<ReturnType<typeof mountDetail>>['wrapper']) {
    wrapper.findComponent(BaseTabs).vm.$emit('update:modelValue', 'versions')
    await flushPromises()
    const uploadBtn = wrapper.findAll('button').find((b) => /上传/.test(b.text()))
    await uploadBtn!.trigger('click')
    await flushPromises()
    await nextTick()
  }

  it('非法格式提示错误，合法文件展示文件名', async () => {
    const { wrapper } = await mountDetail()
    await openUpload(wrapper)

    const dropZone = document.body.querySelector('.border-dashed') as HTMLElement
    dropZone.dispatchEvent(Object.assign(new Event('drop', { bubbles: true }), { dataTransfer: { files: [new File(['x'], 'a.exe')] } }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalled()

    dropZone.dispatchEvent(
      Object.assign(new Event('drop', { bubbles: true }), { dataTransfer: { files: [new File(['x'], '新版合同.pdf')] } }),
    )
    await flushPromises()
    expect(document.body.textContent ?? '').toContain('新版合同.pdf')
  })

  it('上传成功后提示并切回版本标签', async () => {
    const { wrapper } = await mountDetail()
    await openUpload(wrapper)

    const dropZone = document.body.querySelector('.border-dashed') as HTMLElement
    dropZone.dispatchEvent(
      Object.assign(new Event('drop', { bubbles: true }), { dataTransfer: { files: [new File(['x'], 'v2.pdf')] } }),
    )
    await flushPromises()

    const submit = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    submit.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(mocks.uploadContractVersion).toHaveBeenCalledWith(1, expect.any(Object))
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('上传失败提示错误', async () => {
    mocks.uploadContractVersion.mockRejectedValue(new Error('版本冲突'))
    const { wrapper } = await mountDetail()
    await openUpload(wrapper)

    const dropZone = document.body.querySelector('.border-dashed') as HTMLElement
    dropZone.dispatchEvent(
      Object.assign(new Event('drop', { bubbles: true }), { dataTransfer: { files: [new File(['x'], 'v2.pdf')] } }),
    )
    await flushPromises()
    const submit = Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
    submit.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('版本冲突')
  })
})
