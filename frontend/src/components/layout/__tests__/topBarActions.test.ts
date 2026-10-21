import { DOMWrapper, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AppTopBar from '@/components/layout/AppTopBar.vue'
import { AUTH_STORAGE_KEY } from '@/api/http'
import { mountWithApp } from '@test/helpers'

const mocks = vi.hoisted(() => ({
  changePassword: vi.fn(),
  fetchRuntimeInfo: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/api/system', () => ({
  changePassword: (...a: unknown[]) => mocks.changePassword(...a),
  fetchRuntimeInfo: (...a: unknown[]) => mocks.fetchRuntimeInfo(...a),
}))

vi.mock('@/api/contracts', () => ({ fetchContracts: vi.fn(async () => []) }))
vi.mock('@/api/knowledge', () => ({
  fetchLaws: vi.fn(async () => []),
  fetchTemplates: vi.fn(async () => []),
}))

vi.mock('@/plugins/toast', () => ({
  toastSuccess: (...a: unknown[]) => mocks.toastSuccess(...a),
  toastError: (...a: unknown[]) => mocks.toastError(...a),
  toastInfo: vi.fn(),
  toastState: { items: [] },
  default: { install: vi.fn() },
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

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset())
  mocks.changePassword.mockResolvedValue(undefined)
  mocks.fetchRuntimeInfo.mockResolvedValue({
    llm: { provider: 'deepseek', model: 'm', configured: true, dimensions: null },
    embedding: { provider: 'dashscope', model: 'e', configured: true, dimensions: 1024 },
  })
  localStorage.clear()
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(admin))
  document.body.innerHTML = ''
})

/** 展开用户下拉菜单，返回菜单项（reka 的菜单在 portal 中懒渲染） */
async function openMenuItems() {
  const res = await mountWithApp(AppTopBar, { initialPath: '/dashboard' })
  await flushPromises()
  const trigger = res.wrapper.findAll('button').find((b) => b.attributes('aria-label') === '管理员')
  await trigger!.trigger('click')
  await flushPromises()
  await nextTick()
  return { ...res, items: Array.from(document.body.querySelectorAll('[role="menuitem"]')) as HTMLElement[] }
}

function pwdInputs(): NodeListOf<HTMLInputElement> {
  return document.body.querySelectorAll('input[type="password"]')
}

async function fillPwd(old: string, next: string, confirm: string) {
  const inputs = pwdInputs()
  await new DOMWrapper(inputs[0]).setValue(old)
  await new DOMWrapper(inputs[1]).setValue(next)
  await new DOMWrapper(inputs[2]).setValue(confirm)
}

function submitBtn(): HTMLButtonElement {
  return Array.from(document.body.querySelectorAll('.btn-primary')).at(-1) as HTMLButtonElement
}

describe('AppTopBar 用户菜单与改密', () => {
  it('菜单包含修改密码与退出登录两项', async () => {
    const { items } = await openMenuItems()
    expect(items.length).toBeGreaterThanOrEqual(2)
  })

  it('两次输入不一致时提示且不请求接口', async () => {
    const { items } = await openMenuItems()
    items[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    await nextTick()

    expect(pwdInputs().length).toBe(3)
    await fillPwd('old', '123456789012', '123456789013')
    submitBtn().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(mocks.changePassword).not.toHaveBeenCalled()
    expect(mocks.toastError).toHaveBeenCalled()
  })

  it('改密成功后提示', async () => {
    const { items } = await openMenuItems()
    items[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    await nextTick()

    await fillPwd('old', '123456789012', '123456789012')
    submitBtn().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(mocks.changePassword).toHaveBeenCalledWith('old', '123456789012')
    expect(mocks.toastSuccess).toHaveBeenCalled()
  })

  it('改密失败展示后端错误信息', async () => {
    mocks.changePassword.mockRejectedValue(new Error('旧密码不正确'))
    const { items } = await openMenuItems()
    items[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    await nextTick()

    await fillPwd('bad', '123456789012', '123456789012')
    submitBtn().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith('旧密码不正确')
  })

  it('退出登录清空会话并跳转登录页', async () => {
    const { items, router } = await openMenuItems()
    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined as never)
    items[1].dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull()
    expect(pushSpy).toHaveBeenCalledWith('/login')
  })
})
