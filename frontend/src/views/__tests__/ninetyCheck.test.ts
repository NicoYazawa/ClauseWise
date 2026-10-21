import { flushPromises } from '@vue/test-utils'
import { computed } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AppLayout from '@/components/layout/AppLayout.vue'
import LoginView from '@/views/login/LoginView.vue'
import { AUTH_STORAGE_KEY } from '@/api/http'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  fetchPresetAccounts: vi.fn(),
  changePassword: vi.fn(),
  fetchRuntimeInfo: vi.fn(),
  fetchContracts: vi.fn(),
  fetchLaws: vi.fn(),
  fetchTemplates: vi.fn(),
  fetchNotifications: vi.fn(),
  changePasswordSystem: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/api/auth', async () => {
  const actual = await vi.importActual<typeof import('@/api/auth')>('@/api/auth')
  return {
    ...actual,
    login: (...a: unknown[]) => mocks.login(...a),
    fetchPresetAccounts: (...a: unknown[]) => mocks.fetchPresetAccounts(...a),
    changePassword: (...a: unknown[]) => mocks.changePassword(...a),
  }
})

vi.mock('@/api/system', () => ({
  fetchRuntimeInfo: (...a: unknown[]) => mocks.fetchRuntimeInfo(...a),
  changePassword: (...a: unknown[]) => mocks.changePasswordSystem(...a),
  fetchNotifications: (...a: unknown[]) => mocks.fetchNotifications(...a),
}))

vi.mock('@/api/contracts', () => ({ fetchContracts: (...a: unknown[]) => mocks.fetchContracts(...a) }))
vi.mock('@/api/knowledge', () => ({
  fetchLaws: (...a: unknown[]) => mocks.fetchLaws(...a),
  fetchTemplates: (...a: unknown[]) => mocks.fetchTemplates(...a),
}))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: vi.fn(),
  toastState: { items: [] },
  default: { install: vi.fn() },
}))

/** 固定为「减少动效」，覆盖 AppLayout 的瞬时过渡分支 */
vi.mock('@vueuse/core', async () => {
  const actual = await vi.importActual<typeof import('@vueuse/core')>('@vueuse/core')
  return {
    ...actual,
    usePreferredReducedMotion: () => computed(() => 'reduce' as const),
    useDebounceFn: (fn: (...a: unknown[]) => unknown) => fn,
  }
})

const admin = { id: 1, username: 'admin', realName: '管理员', deptName: '法务部', title: '经理', roleName: 'admin', roles: ['admin'], token: 't' }

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.login.mockResolvedValue({ id: 1, username: 'u', token: 't', roles: ['admin'], roleName: '管理员' })
  mocks.fetchPresetAccounts.mockResolvedValue({ enabled: true, password: null, accounts: [] })
  mocks.changePassword.mockResolvedValue(undefined)
  mocks.changePasswordSystem.mockResolvedValue(undefined)
  mocks.fetchRuntimeInfo.mockResolvedValue({
    llm: { provider: 'deepseek', model: 'm', configured: true, dimensions: null },
    embedding: { provider: 'dashscope', model: 'e', configured: true, dimensions: 1024 },
  })
  mocks.fetchContracts.mockResolvedValue([])
  mocks.fetchLaws.mockResolvedValue([])
  mocks.fetchTemplates.mockResolvedValue([])
  mocks.fetchNotifications.mockResolvedValue([])
  localStorage.clear()
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(admin))
  document.body.innerHTML = ''
})

describe('减少动效偏好下的布局', () => {
  it('AppLayout 使用瞬时过渡仍正常渲染外壳', async () => {
    const { wrapper } = await mountWithApp(AppLayout, { initialPath: '/dashboard' })
    await flushPromises()
    expect(wrapper.find('header').exists()).toBe(true)
    expect(wrapper.find('main').exists()).toBe(true)
  })
})

describe('LoginView 预设账号密码为空', () => {
  it('开关开启但共享密码为 null 时按空串处理', async () => {
    const { wrapper } = await mountWithApp(LoginView, { initialPath: '/login' })
    await flushPromises()
    expect(mocks.fetchPresetAccounts).toHaveBeenCalled()
    expect(wrapper.find('#username').exists()).toBe(true)
  })
})
