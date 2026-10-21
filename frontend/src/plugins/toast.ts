import { reactive } from 'vue'
import type { App } from 'vue'

export interface ToastItem {
  id: number
  type: 'success' | 'error' | 'info'
  message: string
}

export const toastState = reactive<{ items: ToastItem[] }>({ items: [] })

let seq = 0

function push(type: ToastItem['type'], message: string, duration = 2800) {
  const id = ++seq
  toastState.items.push({ id, type, message })
  setTimeout(() => {
    const idx = toastState.items.findIndex((t) => t.id === id)
    if (idx >= 0) toastState.items.splice(idx, 1)
  }, duration)
}

export default {
  install(app: App) {
    app.config.globalProperties.$toast = {
      success: (msg: string) => push('success', msg),
      error: (msg: string) => push('error', msg),
      info: (msg: string) => push('info', msg),
    }
  },
}

export function toastSuccess(msg: string) {
  push('success', msg)
}

export function toastError(msg: string) {
  push('error', msg)
}

export function toastInfo(msg: string) {
  push('info', msg)
}
