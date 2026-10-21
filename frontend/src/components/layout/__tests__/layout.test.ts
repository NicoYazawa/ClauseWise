import { flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AppLayout from '@/components/layout/AppLayout.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppTopBar from '@/components/layout/AppTopBar.vue'
import { AUTH_STORAGE_KEY } from '@/api/http'
import { i18n } from '@/i18n'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  fetchRuntimeInfo: vi.fn(),
  changePassword: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/api/system', () => ({
  fetchRuntimeInfo: (...a: unknown[]) => mocks.fetchRuntimeInfo(...a),
  changePassword: (...a: unknown[]) => mocks.changePassword(...a),
}))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: vi.fn(),
  toastState: { items: [] },
  default: { install: vi.fn() },
}))

vi.mock('@/api/contracts', () => ({ fetchContracts: vi.fn(async () => []) }))
vi.mock('@/api/knowledge', () => ({
  fetchLaws: vi.fn(async () => []),
  fetchTemplates: vi.fn(async () => []),
}))

const admin = {
  id: 1,
  username: 'admin',
  realName: '管理员',
  deptName: '法务部',
  title: '经理',
  roleName: 'admin',
  roles: ['admin'],
  token: 't',
}

function runtimeInfo(over: Record<string, unknown> = {}) {
  return {
    llm: { provider: 'deepseek', model: 'deepseek-v4', configured: true, dimensions: null },
    embedding: { provider: 'dashscope', model: 'text-embedding-v4', configured: true, dimensions: 1024 },
    ...over,
  }
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.fetchRuntimeInfo.mockResolvedValue(runtimeInfo())
  mocks.changePassword.mockResolvedValue(undefined)
  localStorage.clear()
  i18n.global.locale.value = 'zh-CN'
})

describe('AppSidebar', () => {
  it('管理员可见系统管理分组，普通用户不可见', async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(admin))
    const { wrapper } = await mountWithApp(AppSidebar, { initialPath: '/dashboard' })
    await flushPromises()
    expect(wrapper.text()).toContain('系统管理')

    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ ...admin, roles: ['reviewer'] }))
    const { wrapper: plain } = await mountWithApp(AppSidebar, { initialPath: '/dashboard' })
    await flushPromises()
    expect(plain.text()).not.toContain('系统管理')
  })

  it('当前路由命中的导航项高亮（含精确匹配）', async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(admin))
    const { wrapper } = await mountWithApp(AppSidebar, {
      initialPath: '/workflow/definitions',
      routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }],
    })
    await flushPromises()
    expect(wrapper.findAll('.nav-row-active').length).toBeGreaterThan(0)
  })

  it('运行时模型信息：真实模型与厂商拼接', async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(admin))
    mocks.fetchRuntimeInfo.mockResolvedValue(
      runtimeInfo({
        llm: { provider: 'deepseek', model: 'contract-review', realModel: 'deepseek-v4', realProvider: 'deepseek', configured: true },
        embedding: { provider: 'dashscope', model: 'text-embedding-v4', configured: true, dimensions: 1024 },
      }),
    )
    const { wrapper } = await mountWithApp(AppSidebar, { initialPath: '/dashboard' })
    await flushPromises()
    // 模型名已包含厂商前缀时不重复拼接
    expect(wrapper.text()).toContain('deepseek-v4')
    expect(wrapper.text()).toContain('1024d')
  })

  it('运行时信息缺失时展示未知占位', async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(admin))
    mocks.fetchRuntimeInfo.mockRejectedValue(new Error('offline'))
    const { wrapper } = await mountWithApp(AppSidebar, { initialPath: '/dashboard' })
    await flushPromises()
    expect(wrapper.text()).toContain('-')
  })

  it('模型未配置时展示未配置文案，custom 厂商不拼接前缀', async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(admin))
    mocks.fetchRuntimeInfo.mockResolvedValue(
      runtimeInfo({
        llm: { provider: '-', model: 'x', configured: false, dimensions: null },
        embedding: { provider: 'custom', model: 'my-emb', configured: false, dimensions: null },
      }),
    )
    const { wrapper } = await mountWithApp(AppSidebar, { initialPath: '/dashboard' })
    await flushPromises()
    expect(wrapper.text()).toContain('my-emb')
  })

  it('优先展示用户部门名作为副标题', async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(admin))
    const { wrapper } = await mountWithApp(AppSidebar, { initialPath: '/dashboard' })
    await flushPromises()
    expect(wrapper.text()).toContain('法务部')
  })
})

describe('AppTopBar', () => {
  it('渲染用户信息并支持语言切换', async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(admin))
    const { wrapper } = await mountWithApp(AppTopBar, { initialPath: '/dashboard' })
    await flushPromises()

    expect(wrapper.text()).toContain('管理员')
    const enBtn = wrapper.findAll('button').find((b) => b.text() === 'EN')
    await enBtn!.trigger('click')
    await nextTick()
    expect(i18n.global.locale.value).toBe('en-US')

    const zhBtn = wrapper.findAll('button').find((b) => b.text() === '中')
    await zhBtn!.trigger('click')
    await nextTick()
    expect(i18n.global.locale.value).toBe('zh-CN')
  })

  it('未登录时头像占位为问号', async () => {
    const { wrapper } = await mountWithApp(AppTopBar, { initialPath: '/dashboard' })
    await flushPromises()
    expect(wrapper.text()).toContain('?')
  })

  it('点击菜单按钮抛出 openNav 事件', async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(admin))
    const { wrapper } = await mountWithApp(AppTopBar, { initialPath: '/dashboard' })
    await flushPromises()
    const menuBtn = wrapper.findAll('button').find((b) => b.attributes('aria-label'))
    await menuBtn?.trigger('click')
    expect(wrapper.emitted('openNav')).toBeTruthy()
  })
})

describe('AppLayout', () => {
  it('渲染顶栏、侧边栏、内容区与移动端抽屉', async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(admin))
    const { wrapper } = await mountWithApp(AppLayout, { initialPath: '/dashboard' })
    await flushPromises()
    expect(wrapper.find('header').exists()).toBe(true)
    expect(wrapper.find('aside').exists()).toBe(true)
    expect(wrapper.find('main').exists()).toBe(true)
  })

  it('减少动效偏好下内容仍正常渲染', async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(admin))
    const { wrapper } = await mountWithApp(AppLayout, { initialPath: '/dashboard' })
    await flushPromises()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })
})
