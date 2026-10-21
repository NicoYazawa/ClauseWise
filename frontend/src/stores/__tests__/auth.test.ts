import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AUTH_STORAGE_KEY } from '@/api/http'
import { queryClient } from '@/api/queryClient'
import { currentUser, useAuthStore } from '@/stores/auth'
import type { AuthUser } from '@/api/auth'

const user: AuthUser = {
  id: 1,
  username: 'zhangsan',
  realName: '张三',
  roleName: 'contract_manager',
  roles: ['contract_manager'],
  token: 'token-1',
} as unknown as AuthUser

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('useAuthStore 会话恢复', () => {
  it('无缓存时初始为未登录', () => {
    const store = useAuthStore()
    expect(store.state.user).toBeNull()
  })

  it('从 localStorage 恢复登录态', () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(user))
    setActivePinia(createPinia())
    const store = useAuthStore()
    expect(store.state.user).toEqual(user)
  })

  it('缓存损坏时安全降级为未登录', () => {
    localStorage.setItem(AUTH_STORAGE_KEY, '{bad-json')
    setActivePinia(createPinia())
    const store = useAuthStore()
    expect(store.state.user).toBeNull()
  })
})

describe('setUser 状态与持久化', () => {
  it('普通用户写入 localStorage', () => {
    const store = useAuthStore()
    store.setUser(user)
    expect(store.state.user?.id).toBe(1)
    expect(JSON.parse(localStorage.getItem(AUTH_STORAGE_KEY) ?? '{}').id).toBe(1)
  })

  it('强制改密用户不写入持久化', () => {
    const store = useAuthStore()
    store.setUser({ ...user, mustChangePassword: true } as AuthUser)
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull()
  })

  it('登出清空状态与缓存', () => {
    const store = useAuthStore()
    store.setUser(user)
    store.logout()
    expect(store.state.user).toBeNull()
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull()
  })

  it('切换用户时清空查询缓存，同一用户则保留', () => {
    const clear = vi.spyOn(queryClient, 'clear').mockImplementation(() => undefined)
    const store = useAuthStore()
    store.setUser(user)
    clear.mockClear()
    // 同一用户 id 不清理
    store.setUser({ ...user, token: 'token-2' } as AuthUser)
    expect(clear).not.toHaveBeenCalled()
    // 不同用户 id 清理
    store.setUser({ ...user, id: 2 } as AuthUser)
    expect(clear).toHaveBeenCalledTimes(1)
    // 登出也清理
    store.logout()
    expect(clear).toHaveBeenCalledTimes(2)
  })
})

describe('roleDisplayName / isAdmin', () => {
  it('优先翻译角色名', () => {
    const store = useAuthStore()
    store.setUser({ ...user, roleName: 'contract_manager' } as AuthUser)
    expect(store.roleDisplayName()).toBeTruthy()
  })

  it('无法翻译时回退到首个角色码，再回退到破折号', () => {
    const store = useAuthStore()
    store.setUser({ ...user, roleName: '', roles: ['reviewer'] } as AuthUser)
    expect(store.roleDisplayName()).toBe('reviewer')

    store.setUser({ ...user, roleName: '', roles: [] } as AuthUser)
    expect(store.roleDisplayName()).toBe('-')

    store.logout()
    expect(store.roleDisplayName()).toBe('-')
  })

  it('isAdmin 依据 roles 判定', () => {
    const store = useAuthStore()
    store.setUser({ ...user, roles: ['admin'] } as AuthUser)
    expect(store.isAdmin()).toBe(true)
    store.setUser({ ...user, roles: ['reviewer'] } as AuthUser)
    expect(store.isAdmin()).toBe(false)
    store.logout()
    expect(store.isAdmin()).toBe(false)
  })
})

describe('currentUser 非 setup 上下文读取', () => {
  it('有缓存返回用户，无缓存返回 null', () => {
    expect(currentUser()).toBeNull()
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(user))
    expect(currentUser()?.id).toBe(1)
  })

  it('缓存损坏时返回 null', () => {
    localStorage.setItem(AUTH_STORAGE_KEY, 'not-json')
    expect(currentUser()).toBeNull()
  })
})
