import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LoginView from '@/views/login/LoginView.vue'
import { AUTH_STORAGE_KEY } from '@/api/http'
import { mountWithApp } from '@test/helpers'

const { loginMock, presetMock, changePwdMock, toastErrorMock } = vi.hoisted(() => ({
  loginMock: vi.fn(),
  presetMock: vi.fn(),
  changePwdMock: vi.fn(),
  toastErrorMock: vi.fn(),
}))

vi.mock('@/api/auth', async () => {
  const actual = await vi.importActual<typeof import('@/api/auth')>('@/api/auth')
  return {
    ...actual,
    login: (...args: unknown[]) => loginMock(...args),
    fetchPresetAccounts: (...args: unknown[]) => presetMock(...args),
    changePassword: (...args: unknown[]) => changePwdMock(...args),
  }
})

vi.mock('@/plugins/toast', () => ({
  toastError: (...args: unknown[]) => toastErrorMock(...args),
  toastSuccess: vi.fn(),
  toastInfo: vi.fn(),
}))

beforeEach(() => {
  localStorage.clear()
  loginMock.mockReset()
  presetMock.mockReset().mockResolvedValue({ enabled: false, password: null, accounts: [] })
  changePwdMock.mockReset().mockResolvedValue(undefined)
  toastErrorMock.mockReset()
})

async function mountLogin(path = '/login') {
  return mountWithApp(LoginView, { initialPath: path })
}

describe('LoginView 登录表单', () => {
  it('渲染品牌信息与登录表单', async () => {
    const { wrapper } = await mountLogin()
    expect(wrapper.find('#username').exists()).toBe(true)
    expect(wrapper.find('#password').exists()).toBe(true)
    expect(wrapper.text()).toContain('登录')
  })

  it('用户名或密码为空时提示必填', async () => {
    presetMock.mockResolvedValue({ enabled: false, password: null, accounts: [] })
    const { wrapper } = await mountLogin()
    await wrapper.find('form').trigger('submit')
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect(loginMock).not.toHaveBeenCalled()
  })

  it('登录成功后写入会话并跳转 redirect', async () => {
    loginMock.mockResolvedValue({ id: 1, username: 'u', realName: 'U', roles: ['admin'], token: 't', roleName: '管理员' })
    const { wrapper, router } = await mountLogin('/login?redirect=/review')
    await wrapper.find('#username').setValue('u')
    await wrapper.find('#password').setValue('p')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(loginMock).toHaveBeenCalledWith({ username: 'u', password: 'p' })
    expect(JSON.parse(localStorage.getItem(AUTH_STORAGE_KEY) ?? '{}').id).toBe(1)
    expect(router.currentRoute.value.path).toBe('/review')
  })

  it('无 redirect 时默认跳转 dashboard', async () => {
    loginMock.mockResolvedValue({ id: 1, username: 'u', realName: 'U', roles: ['admin'], token: 't', roleName: '管理员' })
    const { wrapper, router } = await mountLogin('/login')
    await wrapper.find('#username').setValue('u')
    await wrapper.find('#password').setValue('p')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/dashboard')
  })

  it('登录失败展示错误并弹出 toast', async () => {
    loginMock.mockRejectedValue(new Error('账号或密码错误'))
    const { wrapper } = await mountLogin()
    await wrapper.find('#username').setValue('u')
    await wrapper.find('#password').setValue('bad')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('账号或密码错误')
    expect(toastErrorMock).toHaveBeenCalledWith('账号或密码错误')
  })

  it('非 Error 异常回退到通用失败文案', async () => {
    loginMock.mockRejectedValue('weird')
    const { wrapper } = await mountLogin()
    await wrapper.find('#username').setValue('u')
    await wrapper.find('#password').setValue('p')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })
})

describe('LoginView 强制改密流程', () => {
  it('登录返回 mustChangePassword 时进入改密态', async () => {
    loginMock.mockResolvedValue({ id: 1, username: 'u', token: 't', mustChangePassword: true })
    const { wrapper } = await mountLogin()
    await wrapper.find('#username').setValue('u')
    await wrapper.find('#password').setValue('p')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('#new-password').exists()).toBe(true)
    expect(wrapper.find('#confirm-password').exists()).toBe(true)
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull()
  })

  it('新密码不符合策略时提示要求', async () => {
    loginMock.mockResolvedValue({ id: 1, username: 'u', token: 't', mustChangePassword: true })
    const { wrapper } = await mountLogin()
    await wrapper.find('#username').setValue('u')
    await wrapper.find('#password').setValue('p')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    await wrapper.find('#new-password').setValue('short')
    await wrapper.find('#confirm-password').setValue('short')
    await wrapper.find('form').trigger('submit')
    expect(changePwdMock).not.toHaveBeenCalled()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })

  it('两次输入不一致时提示不匹配', async () => {
    loginMock.mockResolvedValue({ id: 1, username: 'u', token: 't', mustChangePassword: true })
    const { wrapper } = await mountLogin()
    await wrapper.find('#username').setValue('u')
    await wrapper.find('#password').setValue('p')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    await wrapper.find('#new-password').setValue('123456789012')
    await wrapper.find('#confirm-password').setValue('123456789013')
    await wrapper.find('form').trigger('submit')
    expect(changePwdMock).not.toHaveBeenCalled()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })

  it('改密成功后回到登录态并显示成功提示', async () => {
    loginMock.mockResolvedValue({ id: 1, username: 'u', token: 't', mustChangePassword: true })
    const { wrapper } = await mountLogin('/login')
    await wrapper.find('#username').setValue('u')
    await wrapper.find('#password').setValue('p')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    await wrapper.find('#new-password').setValue('123456789012')
    await wrapper.find('#confirm-password').setValue('123456789012')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(changePwdMock).toHaveBeenCalled()
    expect(wrapper.find('[role="status"]').exists()).toBe(true)
    expect(wrapper.find('#username').exists()).toBe(true)
  })

  it('改密失败展示后端错误', async () => {
    loginMock.mockResolvedValue({ id: 1, username: 'u', token: 't', mustChangePassword: true })
    changePwdMock.mockRejectedValue(new Error('旧密码错误'))
    const { wrapper } = await mountLogin()
    await wrapper.find('#username').setValue('u')
    await wrapper.find('#password').setValue('p')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    await wrapper.find('#new-password').setValue('123456789012')
    await wrapper.find('#confirm-password').setValue('123456789012')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('旧密码错误')
  })

  it('可返回登录页清空改密状态', async () => {
    loginMock.mockResolvedValue({ id: 1, username: 'u', token: 't', mustChangePassword: true })
    const { wrapper } = await mountLogin()
    await wrapper.find('#username').setValue('u')
    await wrapper.find('#password').setValue('p')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const back = wrapper.findAll('button').find((b) => b.attributes('type') === 'button')
    expect(back).toBeTruthy()
    await back?.trigger('click')
    expect(wrapper.find('#new-password').exists()).toBe(false)
  })
})

describe('LoginView 预设账号与初始态', () => {
  it('开关开启时展示预设账号并可一键填充', async () => {
    presetMock.mockResolvedValue({
      enabled: true,
      password: 'Demo@123456',
      accounts: [{ username: 'demo', realName: '演示账号', deptName: 'd', title: 't', roleCode: 'r', roleName: 'reviewer' }],
    })
    const { wrapper } = await mountLogin()
    await flushPromises()

    const presetButton = wrapper.findAll('button').find((b) => b.text().includes('演示账号'))
    expect(presetButton).toBeTruthy()
    await presetButton?.trigger('click')

    expect((wrapper.find('#username').element as HTMLInputElement).value).toBe('demo')
    expect((wrapper.find('#password').element as HTMLInputElement).value).toBe('Demo@123456')
  })

  it('预设账号接口失败不影响正常登录', async () => {
    presetMock.mockRejectedValue(new Error('offline'))
    const { wrapper } = await mountLogin()
    await flushPromises()
    expect(wrapper.findAll('button').some((b) => b.text().includes('演示账号'))).toBe(false)
    expect(wrapper.find('#username').exists()).toBe(true)
  })

  it('已持久化的强制改密账号会被清出本地会话', async () => {
    localStorage.setItem(
      AUTH_STORAGE_KEY,
      JSON.stringify({ id: 9, username: 'x', token: 't', mustChangePassword: true }),
    )
    await mountLogin()
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull()
  })
})
