import { http } from '@/api/http'
import type { LoginPayload, User } from '@/types'

export interface AuthUser extends User {
  token: string
  roleName: string
}

export function passwordMeetsPolicy(password: string): boolean {
  return Array.from(password).length >= 12 && new TextEncoder().encode(password).length <= 72
}

/** Authenticate with enterprise credentials. */
export async function login(payload: LoginPayload): Promise<AuthUser> {
  return await http.post<AuthUser, AuthUser>('/auth/login', {
    username: payload.username,
    password: payload.password,
  })
}

/** Change the current user's password (verifies the old password; the new password is bcrypt-salted and hashed before storage) */
export async function changePassword(oldPassword: string, newPassword: string, token?: string): Promise<void> {
  await http.post('/auth/change-password', { oldPassword, newPassword },
    token ? { headers: { Authorization: `Bearer ${token}` } } : undefined)
}

export interface PresetAccount {
  username: string
  realName: string
  deptName: string
  title: string
  roleCode: string
  roleName: string
}

export interface PresetAccountInfo {
  /** True only in demo environments (PRESET_ACCOUNTS_ENABLED=true); when disabled, both the list and password are empty */
  enabled: boolean
  /** Shared password for preset accounts; null when enabled=false */
  password: string | null
  accounts: PresetAccount[]
}

/** Preset (demo) account list: accessible without login; always empty when the switch is off */
export async function fetchPresetAccounts(): Promise<PresetAccountInfo> {
  return await http.get<PresetAccountInfo, PresetAccountInfo>('/auth/preset-accounts')
}
