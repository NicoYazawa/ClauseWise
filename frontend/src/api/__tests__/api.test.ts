import { beforeEach, describe, expect, it, vi } from 'vitest'

const { httpMock, downloadBlobMock } = vi.hoisted(() => ({
  httpMock: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
  },
  downloadBlobMock: vi.fn(async () => 'contract.pdf'),
}))

vi.mock('@/api/http', () => ({
  http: httpMock,
  readToken: vi.fn(() => null),
  downloadBlob: (...args: unknown[]) => downloadBlobMock(...args),
  AUTH_STORAGE_KEY: 'cc_auth',
}))

import { listAgents, fetchAgentTrace, fetchRecentTraces } from '@/api/agents'
import { fetchPresetAccounts, login, passwordMeetsPolicy, changePassword as changePasswordAuth } from '@/api/auth'
import {
  archiveContract,
  downloadContract,
  fetchClauses,
  fetchContract,
  fetchContracts,
  fetchDiff,
  fetchVersions,
  retryParse,
  uploadContract,
  uploadContractVersion,
} from '@/api/contracts'
import {
  deleteTemplate,
  fetchLaws,
  fetchTemplates,
  importLaws,
  markExpired,
  saveLaw,
  saveTemplate,
} from '@/api/knowledge'
import { askQuestion } from '@/api/qa'
import { qk } from '@/api/queryKeys'
import {
  fetchFindings,
  fetchReport,
  fetchTask,
  fetchTaskProgress,
  fetchTasks,
  logReportExport,
  resolveFinding,
  startReview,
} from '@/api/reviews'
import {
  changePassword as changePasswordSystem,
  createUser,
  fetchAuditLogs,
  fetchModelVersions,
  fetchNotifications,
  fetchPrompts,
  fetchRoles,
  fetchRuntimeInfo,
  fetchUsers,
  markNotificationRead,
  resetPassword,
  activatePrompt,
  savePromptContent,
  setDefaultModel,
  toggleUser,
  updateRolePermissions,
  updateUserRoles,
} from '@/api/system'
import {
  actOnInstance,
  fetchDefinitions,
  fetchInstance,
  fetchInstances,
  saveDefinition,
  startApproval,
  toggleDefinition,
  urgeInstance,
  withdrawInstance,
} from '@/api/workflows'

beforeEach(() => {
  for (const fn of Object.values(httpMock)) fn.mockReset().mockResolvedValue(undefined)
  downloadBlobMock.mockReset().mockResolvedValue('contract.pdf')
})

describe('auth API', () => {
  it('密码策略：长度 >= 12 且 UTF-8 字节 <= 72', () => {
    expect(passwordMeetsPolicy('123456789012')).toBe(true)
    expect(passwordMeetsPolicy('12345678901')).toBe(false)
    expect(passwordMeetsPolicy('密'.repeat(24))).toBe(true) // 72 字节
    expect(passwordMeetsPolicy('密'.repeat(25))).toBe(false) // 75 字节
  })

  it('login 提交账号密码', async () => {
    await login({ username: 'u', password: 'p' } as never)
    expect(httpMock.post).toHaveBeenCalledWith('/auth/login', { username: 'u', password: 'p' })
  })

  it('changePassword 带/不带 token 两种请求头', async () => {
    await changePasswordAuth('old', 'new')
    expect(httpMock.post).toHaveBeenLastCalledWith('/auth/change-password', { oldPassword: 'old', newPassword: 'new' }, undefined)
    await changePasswordAuth('old', 'new', 'tok')
    expect(httpMock.post).toHaveBeenLastCalledWith('/auth/change-password', { oldPassword: 'old', newPassword: 'new' }, {
      headers: { Authorization: 'Bearer tok' },
    })
  })

  it('fetchPresetAccounts', async () => {
    await fetchPresetAccounts()
    expect(httpMock.get).toHaveBeenCalledWith('/auth/preset-accounts')
  })
})

describe('contracts API', () => {
  it('fetchContracts 仅在传入时拼接筛选参数', async () => {
    await fetchContracts()
    expect(httpMock.get).toHaveBeenLastCalledWith('/contracts', { params: {} })
    await fetchContracts({ keyword: 'k', contractType: 'sale', status: 'draft' })
    expect(httpMock.get).toHaveBeenLastCalledWith('/contracts', {
      params: { keyword: 'k', contractType: 'sale', status: 'draft' },
    })
  })

  it('详情/版本/条款/差异接口路径正确', async () => {
    await fetchContract(1)
    expect(httpMock.get).toHaveBeenLastCalledWith('/contracts/1')
    await fetchVersions(1)
    expect(httpMock.get).toHaveBeenLastCalledWith('/contracts/1/versions')
    await fetchClauses(2, 1)
    expect(httpMock.get).toHaveBeenLastCalledWith('/contracts/versions/2/clauses')
    await fetchDiff(1, 1, 2)
    expect(httpMock.get).toHaveBeenLastCalledWith('/contracts/1/versions/diff', {
      params: { base: 1, target: 2 },
    })
  })

  it('上传合同以 FormData 提交', async () => {
    const file = new File(['x'], 'a.pdf')
    await uploadContract({ file, title: 't', contractType: 'sale', counterpartyName: 'c', amount: 10 })
    const [url, body] = httpMock.post.mock.calls.at(-1) as [string, FormData]
    expect(url).toBe('/contracts/upload')
    expect(body instanceof FormData).toBe(true)
    expect(body.get('title')).toBe('t')
    expect(body.get('amount')).toBe('10')
  })

  it('上传新版本 / 重试解析 / 归档', async () => {
    await uploadContractVersion(3, { file: new File(['x'], 'b.pdf') })
    expect(httpMock.post).toHaveBeenLastCalledWith('/contracts/3/versions', expect.any(FormData))
    await retryParse(3)
    expect(httpMock.post).toHaveBeenLastCalledWith('/contracts/3/retry-parse')
    await archiveContract(3)
    expect(httpMock.post).toHaveBeenLastCalledWith('/contracts/3/archive')
  })

  it('downloadContract 先取合同编号再下载', async () => {
    httpMock.get.mockResolvedValueOnce({ contractNo: 'HT-9' })
    const name = await downloadContract(3)
    expect(downloadBlobMock).toHaveBeenCalledWith('/contracts/3/download', 'HT-9.pdf')
    expect(name).toBe('contract.pdf')
  })
})

describe('knowledge API', () => {
  it('法条读取/保存/过期/批量导入', async () => {
    await fetchLaws()
    expect(httpMock.get).toHaveBeenLastCalledWith('/laws')
    await saveLaw({} as never)
    expect(httpMock.post).toHaveBeenLastCalledWith('/laws', {})
    await markExpired(2)
    expect(httpMock.post).toHaveBeenLastCalledWith('/laws/2/expire')
    await importLaws(new File(['x'], 'laws.xlsx'))
    expect(httpMock.post).toHaveBeenLastCalledWith('/laws/import', expect.any(FormData))
  })

  it('模板读取/保存/删除', async () => {
    await fetchTemplates()
    expect(httpMock.get).toHaveBeenLastCalledWith('/templates')
    await saveTemplate({ name: 'n', contractType: 'sale', clauseLevel: 'core', content: 'c' } as never)
    expect(httpMock.post).toHaveBeenLastCalledWith('/templates', expect.objectContaining({ name: 'n' }))
    await deleteTemplate(5)
    expect(httpMock.delete).toHaveBeenLastCalledWith('/templates/5')
  })
})

describe('reviews API', () => {
  it('任务列表/详情/进度/报告', async () => {
    await fetchTasks()
    expect(httpMock.get).toHaveBeenLastCalledWith('/review-tasks')
    await fetchTask(1)
    expect(httpMock.get).toHaveBeenLastCalledWith('/review-tasks/1')
    await fetchTaskProgress(1)
    expect(httpMock.get).toHaveBeenLastCalledWith('/review-tasks/1/progress')
    await fetchReport(1)
    expect(httpMock.get).toHaveBeenLastCalledWith('/review-tasks/1/report')
  })

  it('发起审查 / 处置发现 / 导出留痕 / 发现列表', async () => {
    await startReview({ contractId: 1, taskType: 'full' })
    expect(httpMock.post).toHaveBeenLastCalledWith('/review-tasks', { contractId: 1, taskType: 'full' })
    await resolveFinding(9, 'accepted' as never)
    expect(httpMock.put).toHaveBeenLastCalledWith('/findings/9/status', { status: 'accepted' })
    await logReportExport(1, 'pdf')
    expect(httpMock.post).toHaveBeenLastCalledWith('/review-tasks/1/export', { format: 'pdf' })
    await fetchFindings()
    expect(httpMock.get).toHaveBeenLastCalledWith('/findings')
  })
})

describe('system API', () => {
  it('用户与角色管理', async () => {
    await fetchUsers()
    expect(httpMock.get).toHaveBeenLastCalledWith('/users')
    await createUser({ username: 'u', realName: 'n', deptName: 'd', title: 't', phone: 'p', roles: ['r'] })
    expect(httpMock.post).toHaveBeenLastCalledWith('/users', expect.objectContaining({ username: 'u' }))
    await resetPassword(1)
    expect(httpMock.post).toHaveBeenLastCalledWith('/users/1/reset-password')
    await changePasswordSystem('o', 'n')
    expect(httpMock.post).toHaveBeenLastCalledWith('/auth/change-password', { oldPassword: 'o', newPassword: 'n' })
    await toggleUser(1)
    expect(httpMock.post).toHaveBeenLastCalledWith('/users/1/toggle')
    await updateUserRoles(1, ['admin'])
    expect(httpMock.put).toHaveBeenLastCalledWith('/users/1/roles', { roles: ['admin'] })
    await fetchRoles()
    expect(httpMock.get).toHaveBeenLastCalledWith('/roles')
    await updateRolePermissions('admin', ['x'])
    expect(httpMock.put).toHaveBeenLastCalledWith('/roles/admin/permissions', { permissions: ['x'] })
  })

  it('审计日志按条件拼接参数', async () => {
    await fetchAuditLogs()
    expect(httpMock.get).toHaveBeenLastCalledWith('/audit-logs', { params: {} })
    await fetchAuditLogs({ username: 'u', action: 'login' })
    expect(httpMock.get).toHaveBeenLastCalledWith('/audit-logs', { params: { username: 'u', action: 'login' } })
  })

  it('通知 / 模型 / 运行时 / Prompt', async () => {
    await fetchNotifications()
    expect(httpMock.get).toHaveBeenLastCalledWith('/notifications')
    await markNotificationRead(2)
    expect(httpMock.post).toHaveBeenLastCalledWith('/notifications/2/read')
    await fetchModelVersions()
    expect(httpMock.get).toHaveBeenLastCalledWith('/model-versions')
    await setDefaultModel(3)
    expect(httpMock.post).toHaveBeenLastCalledWith('/model-versions/3/default')
    await fetchRuntimeInfo()
    expect(httpMock.get).toHaveBeenLastCalledWith('/runtime-info')
    await fetchPrompts()
    expect(httpMock.get).toHaveBeenLastCalledWith('/prompts')
    await savePromptContent(1, 'c')
    expect(httpMock.put).toHaveBeenLastCalledWith('/prompts/1/content', { content: 'c' })
    await activatePrompt(1)
    expect(httpMock.post).toHaveBeenLastCalledWith('/prompts/1/activate')
  })
})

describe('workflows API', () => {
  it('实例/定义读取', async () => {
    await fetchInstances()
    expect(httpMock.get).toHaveBeenLastCalledWith('/workflow/instances')
    await fetchInstance(1)
    expect(httpMock.get).toHaveBeenLastCalledWith('/workflow/instances/1')
    await fetchDefinitions()
    expect(httpMock.get).toHaveBeenLastCalledWith('/workflow/definitions')
  })

  it('审批动作携带 expectedNodeId 防并发覆盖', async () => {
    await actOnInstance(1, 'approve' as never, 'ok', 'n1')
    expect(httpMock.post).toHaveBeenLastCalledWith('/workflow/instances/1/actions', {
      action: 'approve',
      expectedNodeId: 'n1',
      comment: 'ok',
    })
  })

  it('撤回 / 发起 / 催办 / 保存定义 / 启停定义', async () => {
    await withdrawInstance(1, '原因')
    expect(httpMock.post).toHaveBeenLastCalledWith('/workflow/instances/1/withdraw', { reason: '原因' })
    await startApproval({ contractId: 1, contractTitle: 't', score: 90, amount: 1, highRisk: 0, riskTotal: 0 })
    expect(httpMock.post).toHaveBeenLastCalledWith('/workflow/instances', expect.objectContaining({ score: 90 }))
    await urgeInstance(1)
    expect(httpMock.post).toHaveBeenLastCalledWith('/workflow/instances/1/urge')
    await saveDefinition({ name: 'n', contractTypes: ['sale'], nodes: [] })
    expect(httpMock.post).toHaveBeenLastCalledWith('/workflow/definitions', expect.objectContaining({ name: 'n' }))
    await toggleDefinition(2)
    expect(httpMock.post).toHaveBeenLastCalledWith('/workflow/definitions/2/toggle')
  })
})

describe('agents API 与 queryKeys', () => {
  it('注册表 / 留痕 / 最近留痕', async () => {
    await listAgents()
    expect(httpMock.get).toHaveBeenLastCalledWith('/agents')
    await fetchAgentTrace('review', 5)
    expect(httpMock.get).toHaveBeenLastCalledWith('/agents/trace', { params: { task_type: 'review', ref_id: 5 } })
    await fetchRecentTraces()
    expect(httpMock.get).toHaveBeenLastCalledWith('/agents/trace/recent', { params: { limit: 60 } })
    await fetchRecentTraces(10)
    expect(httpMock.get).toHaveBeenLastCalledWith('/agents/trace/recent', { params: { limit: 10 } })
  })

  it('qk 工厂生成稳定前缀键', () => {
    expect(qk.contracts.all).toEqual(['contracts'])
    expect(qk.contracts.list({ page: 1 })).toEqual(['contracts', 'list', { page: 1 }])
    expect(qk.contracts.detail(1)).toEqual(['contracts', 'detail', 1])
    expect(qk.contracts.versions(1)).toEqual(['contracts', 'versions', 1])
    expect(qk.contracts.clauses(2)).toEqual(['contracts', 'clauses', 2])
    expect(qk.contracts.diff(1, 1, 2)).toEqual(['contracts', 'diff', 1, 1, 2])
    expect(qk.review.tasks()).toEqual(['review', 'tasks'])
    expect(qk.review.task(1)).toEqual(['review', 'task', 1])
    expect(qk.review.progress(1)).toEqual(['review', 'progress', 1])
    expect(qk.review.report(1)).toEqual(['review', 'report', 1])
    expect(qk.review.findings()).toEqual(['review', 'findings'])
    expect(qk.knowledge.laws()).toEqual(['knowledge', 'laws'])
    expect(qk.knowledge.templates()).toEqual(['knowledge', 'templates'])
    expect(qk.system.users()).toEqual(['system', 'users'])
    expect(qk.system.roles()).toEqual(['system', 'roles'])
    expect(qk.system.notifications()).toEqual(['system', 'notifications'])
    expect(qk.system.auditLogs()).toEqual(['system', 'audit-logs'])
    expect(qk.system.auditLogsFiltered({ a: 1 })).toEqual(['system', 'audit-logs', { a: 1 }])
    expect(qk.system.models()).toEqual(['system', 'models'])
    expect(qk.system.runtimeInfo()).toEqual(['system', 'runtime-info'])
    expect(qk.system.prompts()).toEqual(['system', 'prompts'])
    expect(qk.workflow.definitions()).toEqual(['workflow', 'definitions'])
    expect(qk.workflow.instances()).toEqual(['workflow', 'instances'])
    expect(qk.workflow.detail(1)).toEqual(['workflow', 'detail', 1])
    expect(qk.agents.registry()).toEqual(['agents', 'registry'])
    expect(qk.agents.trace(1)).toEqual(['agents', 'trace', 1])
    expect(qk.agents.recentTraces()).toEqual(['agents', 'trace', 'recent'])
    expect(qk.dashboard()).toEqual(['dashboard'])
  })

  it('askQuestion 提交问题', async () => {
    await askQuestion('合同有效吗')
    expect(httpMock.post).toHaveBeenLastCalledWith('/qa/ask', { question: '合同有效吗' })
  })
})
