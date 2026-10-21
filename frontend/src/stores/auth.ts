import { reactive } from 'vue'
import { defineStore } from 'pinia'
import type { AuthUser } from '@/api/auth'
import { AUTH_STORAGE_KEY } from '@/api/http'
import { queryClient } from '@/api/queryClient'
import { translateData } from '@/utils/i18nData'

const STORAGE_KEY = AUTH_STORAGE_KEY

function restore(): { user: AuthUser | null } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return { user: JSON.parse(raw) as AuthUser }
  } catch {
    /* ignore */
  }
  return { user: null }
}

export const useAuthStore = defineStore('auth', () => {
  const state = reactive(restore())

  function setUser(user: AuthUser | null) {
    if (!user || state.user?.id !== user.id) queryClient.clear()
    state.user = user
    if (user && !user.mustChangePassword) localStorage.setItem(STORAGE_KEY, JSON.stringify(user))
    else localStorage.removeItem(STORAGE_KEY)
  }

  function logout() {
    setUser(null)
  }

  /** Display name of the current user's role (the backend returns a Chinese roleName on login; rendered in the current language) */
  function roleDisplayName(): string {
    return translateData(state.user?.roleName) || state.user?.roles?.[0] || '-'
  }

  /** Simple RBAC: whether the user is a system administrator (controls "System Management" menu visibility) */
  function isAdmin(): boolean {
    return state.user?.roles?.includes('admin') ?? false
  }

  return { state, setUser, logout, roleDisplayName, isAdmin }
})

/** Read the current logged-in user outside setup contexts (e.g. the api layer) */
export function currentUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}
