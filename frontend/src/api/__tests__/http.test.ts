import axios from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AUTH_STORAGE_KEY, downloadBlob, http, readToken } from '@/api/http'
import { i18n } from '@/i18n'
import { queryClient } from '@/api/queryClient'

const requestHandler = (http.interceptors.request as unknown as { handlers: { fulfilled: (c: never) => never }[] })
  .handlers[0].fulfilled
const responseFulfilled = (http.interceptors.response as unknown as { handlers: { fulfilled: (r: never) => never }[] })
  .handlers[0].fulfilled
const responseRejected = (
  http.interceptors.response as unknown as { handlers: { rejected: (e: never) => Promise<never> }[] }
).handlers[0].rejected

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('readToken', () => {
  it('无缓存返回 null', () => {
    expect(readToken()).toBeNull()
  })

  it('有缓存返回 token', () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ token: 'abc' }))
    expect(readToken()).toBe('abc')
  })

  it('缓存损坏返回 null（catch 分支）', () => {
    localStorage.setItem(AUTH_STORAGE_KEY, '{bad')
    expect(readToken()).toBeNull()
  })
})

describe('请求拦截器', () => {
  it('有 token 时注入 Authorization', () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ token: 'abc' }))
    const config = requestHandler({ headers: {} } as never) as unknown as { headers: Record<string, string> }
    expect(config.headers.Authorization).toBe('Bearer abc')
  })

  it('无 token 不注入', () => {
    const config = requestHandler({ headers: {} } as never) as unknown as { headers: Record<string, string> }
    expect(config.headers.Authorization).toBeUndefined()
  })

  it('已显式设置 Authorization 时不覆盖', () => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ token: 'abc' }))
    const config = requestHandler({ headers: { Authorization: 'Bearer explicit' } } as never) as unknown as {
      headers: Record<string, string>
    }
    expect(config.headers.Authorization).toBe('Bearer explicit')
  })
})

describe('响应拦截器（成功）', () => {
  it('直接返回 data', () => {
    expect(responseFulfilled({ data: { ok: 1 } } as never)).toEqual({ ok: 1 })
  })
})

describe('响应拦截器（失败归一化）', () => {
  function errorOf(detail: unknown, status = 400, message = 'axios message') {
    return { response: { status, data: { detail } }, message }
  }

  it('已知错误码翻译为 i18n 文案', async () => {
    const messages = (i18n.global.messages as unknown as { value: Record<string, { errors?: Record<string, unknown> }> })
      .value
    const errors = messages['zh-CN']?.errors ?? {}
    const knownCode = Object.keys(errors).find((k) => typeof errors[k] === 'string')
    if (!knownCode) return // 词条结构变化时跳过，避免误报
    await expect(responseRejected(errorOf({ code: knownCode, message: 'raw' }) as never)).rejects.toMatchObject({
      code: knownCode,
      status: 400,
    })
    expect(i18n.global.te(`errors.${knownCode}`)).toBe(true)
  })

  it('未知错误码回退 detail.message', async () => {
    await expect(responseRejected(errorOf({ code: 'NOT_A_REAL_CODE', message: '后端原文' }) as never)).rejects.toThrow(
      '后端原文',
    )
  })

  it('detail 为字符串时直接使用', async () => {
    await expect(responseRejected(errorOf('字符串错误') as never)).rejects.toThrow('字符串错误')
  })

  it('detail 缺失时回退 axios message', async () => {
    await expect(responseRejected(errorOf(undefined) as never)).rejects.toThrow('axios message')
  })

  it('全部缺失时使用默认中文兜底', async () => {
    const err = { response: { status: 500, data: {} } }
    await expect(responseRejected(err as never)).rejects.toThrow('请求失败，请稍后重试')
  })

  it('非 401 不清除会话', async () => {
    const clear = vi.spyOn(queryClient, 'clear')
    await expect(responseRejected(errorOf('x', 500) as never)).rejects.toThrow('x')
    expect(clear).not.toHaveBeenCalled()
  })

  it('401 清除缓存与本地会话；非登录页跳转登录', async () => {
    const clear = vi.spyOn(queryClient, 'clear').mockImplementation(() => undefined)
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ token: 'abc' }))
    const loc = { pathname: '/dashboard', href: '' }
    vi.stubGlobal('location', loc)

    await expect(responseRejected(errorOf('未登录', 401) as never)).rejects.toThrow('未登录')
    expect(clear).toHaveBeenCalled()
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull()
    expect(loc.href).toBe('/login')
  })

  it('已在登录页时 401 不重复跳转', async () => {
    vi.spyOn(queryClient, 'clear').mockImplementation(() => undefined)
    const loc = { pathname: '/login', href: '' }
    vi.stubGlobal('location', loc)
    await expect(responseRejected(errorOf('未登录', 401) as never)).rejects.toThrow('未登录')
    expect(loc.href).toBe('')
  })
})

describe('downloadBlob 附件下载', () => {
  function setup() {
    Object.defineProperty(URL, 'createObjectURL', { value: vi.fn(() => 'blob:x'), configurable: true, writable: true })
    Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), configurable: true, writable: true })
    const anchor = { href: '', download: '', click: vi.fn(), remove: vi.fn() }
    vi.spyOn(document, 'createElement').mockReturnValue(anchor as unknown as HTMLElement)
    vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n)
    return anchor
  }

  it('解析 RFC 5987 filename* 并触发保存', async () => {
    const anchor = setup()
    vi.spyOn(axios, 'get').mockResolvedValue({
      headers: { 'content-disposition': "attachment; filename*=UTF-8''%E6%8A%A5%E5%91%8A.pdf" },
      data: new Blob(['x']),
    } as never)
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ token: 'abc' }))

    const name = await downloadBlob('/contracts/1/download', 'fallback.pdf')
    expect(name).toBe('报告.pdf')
    expect(anchor.download).toBe('报告.pdf')
    expect(anchor.click).toHaveBeenCalled()
    expect(anchor.remove).toHaveBeenCalled()
  })

  it('解析带引号的 filename 并去掉引号', async () => {
    setup()
    vi.spyOn(axios, 'get').mockResolvedValue({
      headers: { 'content-disposition': 'attachment; filename="simple.pdf"' },
      data: new Blob(['x']),
    } as never)
    expect(await downloadBlob('/x', 'fallback.pdf')).toBe('simple.pdf')
  })

  it('无 disposition 时使用回退文件名', async () => {
    setup()
    vi.spyOn(axios, 'get').mockResolvedValue({ headers: {}, data: new Blob(['x']) } as never)
    expect(await downloadBlob('/x', 'fallback.pdf')).toBe('fallback.pdf')
  })

  it('无 token 时不带 Authorization 头', async () => {
    setup()
    const get = vi.spyOn(axios, 'get').mockResolvedValue({ headers: {}, data: new Blob(['x']) } as never)
    await downloadBlob('/x', 'f.pdf')
    const config = get.mock.calls[0][1] as { headers: Record<string, string> }
    expect(config.headers.Authorization).toBeUndefined()
  })
})
