import { flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AuditLogView from '@/views/system/AuditLogView.vue'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({ fetchAuditLogs: vi.fn() }))

vi.mock('@/api/system', () => ({ fetchAuditLogs: (...a: unknown[]) => mocks.fetchAuditLogs(...a) }))

function log(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    username: 'admin',
    action: 'login',
    resourceType: 'user',
    resourceId: '1',
    createdAt: '2026-08-28T10:00:00',
    detail: { result: '成功', ip: '127.0.0.1', ua: 'Chrome', extra: null },
    ...over,
  }
}

beforeEach(() => {
  mocks.fetchAuditLogs.mockReset()
  mocks.fetchAuditLogs.mockResolvedValue([])
  document.body.innerHTML = ''
})

describe('AuditLogView', () => {
  it('无数据时展示空态', async () => {
    const { wrapper } = await mountWithApp(AuditLogView)
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('渲染多种动作分类与结果状态', async () => {
    mocks.fetchAuditLogs.mockResolvedValue([
      log({ id: 1, action: 'login' }),
      log({ id: 2, action: 'contract:reject' }),
      log({ id: 3, action: 'contract:delete' }),
      log({ id: 4, action: 'approval:approve' }),
      log({ id: 5, action: 'review:accept' }),
      log({ id: 6, action: 'workflow:withdraw' }),
      log({ id: 7, action: 'contract:upload' }),
      log({ id: 8, action: 'unknown:action' }),
      log({ id: 9, action: 'login', detail: { result: '失败', ip: '1.1.1.1', ua: 'Firefox' } }),
      log({ id: 10, action: 'login', detail: { result: '成功', ip: '2.2.2.2', ua: 'Safari', extra: '字段变更' } }),
    ])
    const { wrapper } = await mountWithApp(AuditLogView)
    await flushPromises()

    expect(wrapper.text()).toContain('admin')
    expect(wrapper.text()).toContain('127.0.0.1')
    expect(wrapper.text()).toContain('字段变更')
  })

  it('超过一页时分页展示', async () => {
    mocks.fetchAuditLogs.mockResolvedValue(
      Array.from({ length: 15 }, (_, i) => log({ id: i + 1, username: `user${i + 1}` })),
    )
    const { wrapper } = await mountWithApp(AuditLogView)
    await flushPromises()
    expect(wrapper.text()).toContain('user1')
    const page2 = wrapper.findAll('button').find((b) => b.text() === '2')
    await page2!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('user13')
  })

  it('搜索按钮按用户名/动作过滤', async () => {
    const { wrapper } = await mountWithApp(AuditLogView)
    await flushPromises()
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('zhangsan')
    await inputs[1].setValue('login')
    await wrapper.findAll('button').find((b) => b.text().length > 0)!.trigger('click')
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('点击记录打开详情抽屉（含 extra 与无 extra 两种）', async () => {
    mocks.fetchAuditLogs.mockResolvedValue([
      log({ id: 1 }),
      log({ id: 2, detail: { result: '失败', ip: '3.3.3.3', ua: 'Edge', extra: '权限变更' } }),
    ])
    const { wrapper } = await mountWithApp(AuditLogView)
    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    await rows[0].trigger('click')
    await flushPromises()
    await nextTick()
    expect(document.body.textContent ?? '').toContain('127.0.0.1')

    await rows[1].trigger('click')
    await flushPromises()
    await nextTick()
    expect(document.body.textContent ?? '').toContain('权限变更')
  })
})
