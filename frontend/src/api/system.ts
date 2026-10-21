import { http } from '@/api/http'
import type { User, TemporaryCredentialUser, RoleInfo, AuditLog, ModelVersion, PromptTemplate } from '@/types'

export async function fetchUsers(): Promise<User[]> {
  return await http.get<User[], User[]>('/users')
}

/** Create a user and return the generated temporary credential once. */
export async function createUser(input: {
  username: string
  realName: string
  deptName: string
  title: string
  phone: string
  roles: string[]
}): Promise<TemporaryCredentialUser> {
  return await http.post<TemporaryCredentialUser, TemporaryCredentialUser>('/users', input)
}

/** Reset credentials and return the generated temporary password once. */
export async function resetPassword(userId: number): Promise<TemporaryCredentialUser> {
  return await http.post<TemporaryCredentialUser, TemporaryCredentialUser>(`/users/${userId}/reset-password`)
}

/** Personal password change (verifies old password; new password stored as salted bcrypt hash) */
export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await http.post('/auth/change-password', { oldPassword, newPassword })
}

export async function toggleUser(userId: number): Promise<User> {
  return await http.post<User, User>(`/users/${userId}/toggle`)
}

export async function updateUserRoles(userId: number, newRoles: string[]): Promise<User> {
  return await http.put<User, User>(`/users/${userId}/roles`, { roles: newRoles })
}

export async function fetchRoles(): Promise<RoleInfo[]> {
  return await http.get<RoleInfo[], RoleInfo[]>('/roles')
}

export async function updateRolePermissions(code: string, permissions: string[]): Promise<RoleInfo> {
  return await http.put<RoleInfo, RoleInfo>(`/roles/${code}/permissions`, { permissions })
}

export interface AuditQuery {
  username?: string
  action?: string
}

export async function fetchAuditLogs(query: AuditQuery = {}): Promise<AuditLog[]> {
  const params: Record<string, string> = {}
  if (query.username) params.username = query.username
  if (query.action) params.action = query.action
  return await http.get<AuditLog[], AuditLog[]>('/audit-logs', { params })
}

// ===== In-app notifications (broadcast + targeted to self; click to mark one as read) =====

export interface AppNotification {
  id: number
  type: 'review_done' | 'approval_todo' | 'approval_timeout' | string
  title: string
  content: string
  read: boolean
  createdAt: string | null
}

export async function fetchNotifications(): Promise<AppNotification[]> {
  return await http.get<AppNotification[], AppNotification[]>('/notifications')
}

export async function markNotificationRead(id: number): Promise<void> {
  await http.post(`/notifications/${id}/read`)
}

// ===== Model & Prompt version management =====

export async function fetchModelVersions(): Promise<ModelVersion[]> {
  return await http.get<ModelVersion[], ModelVersion[]>('/model-versions')
}

/** Switch default model version: mutually exclusive per type; must pass the quality regression set first */
export async function setDefaultModel(id: number): Promise<ModelVersion> {
  return await http.post<ModelVersion, ModelVersion>(`/model-versions/${id}/default`)
}

// ===== Runtime model info (footer display: actually-active vendor & model) =====

export interface RuntimeModelInfo {
  provider: string
  model: string
  configured: boolean
  dimensions: number | null
  /** Real model behind a gateway alias (e.g. contract-review -> deepseek-v4-flash-vision-exp); absent when the gateway is unreachable */
  realModel?: string
  /** Real vendor behind a gateway alias (e.g. deepseek) */
  realProvider?: string
  /** Returned only when the model config is invalid */
  error?: string
}

export interface RuntimeInfo {
  llm: RuntimeModelInfo
  embedding: RuntimeModelInfo
}

/** Currently-active model vendor & model (requires login; no external probes, safe to call on page load) */
export async function fetchRuntimeInfo(): Promise<RuntimeInfo> {
  return await http.get<RuntimeInfo, RuntimeInfo>('/runtime-info')
}

export async function fetchPrompts(): Promise<PromptTemplate[]> {
  return await http.get<PromptTemplate[], PromptTemplate[]>('/prompts')
}

/** Save prompt: publish a new version (incremented) and activate it; older versions in the same scene auto-deactivate */
export async function savePromptContent(id: number, content: string): Promise<PromptTemplate> {
  return await http.put<PromptTemplate, PromptTemplate>(`/prompts/${id}/content`, { content })
}

/** Activate a historical prompt version (mutually exclusive within the same scene) */
export async function activatePrompt(id: number): Promise<PromptTemplate> {
  return await http.post<PromptTemplate, PromptTemplate>(`/prompts/${id}/activate`)
}
