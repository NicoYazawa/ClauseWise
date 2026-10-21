/**
 * axios instance: real backend integration (baseURL /api/v1, forwarded to 8000 by the vite proxy in dev)
 * - Request interceptor: inject the Bearer token (shares the localStorage key with the auth store)
 * - Response interceptor: return data directly; map backend error codes to i18n copy, attaching code/status
 * - 401: clear the local session and redirect to the login page
 */
import axios, { type AxiosRequestConfig } from 'axios'
import type { AuthUser } from '@/api/auth'
import { i18n } from '@/i18n'
import { queryClient } from '@/api/queryClient'

export const AUTH_STORAGE_KEY = 'cc_auth'

export function readToken(): string | null {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as AuthUser).token : null
  } catch {
    return null
  }
}

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 180_000,
})

http.interceptors.request.use((config) => {
  const token = readToken()
  if (token && !config.headers.Authorization) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (resp) => resp.data,
  (error) => {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail
    if (status === 401) {
      queryClient.clear()
      localStorage.removeItem(AUTH_STORAGE_KEY)
      if (!location.pathname.startsWith('/login')) {
        location.href = '/login'
      }
    }
    const code = typeof detail === 'object' ? detail?.code : undefined
    const raw = typeof detail === 'object' ? detail?.message : typeof detail === 'string' ? detail : ''
    let message: string
    if (code && i18n.global.te(`errors.${code}`)) {
      message = i18n.global.t(`errors.${code}`)
    } else {
      message = raw || error?.message || '请求失败，请稍后重试'
    }
    const err = new Error(message) as Error & { code?: string; status?: number }
    err.code = code
    err.status = status
    return Promise.reject(err)
  },
)

/** Download a blob (with auth); returns { filename } and triggers the browser save */
export async function downloadBlob(url: string, fallbackName: string, config?: AxiosRequestConfig): Promise<string> {
  const resp = await axios.get(url, {
    baseURL: '/api/v1',
    responseType: 'blob',
    timeout: 120_000,
    ...config,
    headers: {
      ...(config?.headers ?? {}),
      ...(readToken() ? { Authorization: `Bearer ${readToken()}` } : {}),
    },
  })
  const disposition: string = resp.headers?.['content-disposition'] ?? ''
  const match = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(disposition)
  const filename = match ? decodeURIComponent(match[1].replace(/"/g, '')) : fallbackName
  const blobUrl = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(blobUrl)
  return filename
}
