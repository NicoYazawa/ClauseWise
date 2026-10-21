import { beforeEach, describe, expect, it, vi } from 'vitest'

const { currentUserMock, stubModule } = vi.hoisted(() => ({
  currentUserMock: vi.fn(),
  stubModule: () => ({ default: { template: '<div />' } }),
}))

vi.mock('@/stores/auth', () => ({ currentUser: () => currentUserMock() }))

vi.mock('@/views/login/LoginView.vue', stubModule)
vi.mock('@/views/dashboard/DashboardView.vue', stubModule)
vi.mock('@/views/contracts/ContractListView.vue', stubModule)
vi.mock('@/views/contracts/ContractDetailView.vue', stubModule)
vi.mock('@/views/contracts/ContractDiffView.vue', stubModule)
vi.mock('@/views/review/ReviewTaskListView.vue', stubModule)
vi.mock('@/views/review/ReviewReportView.vue', stubModule)
vi.mock('@/views/search/GlobalSearchView.vue', stubModule)
vi.mock('@/views/workflow/WorkflowListView.vue', stubModule)
vi.mock('@/views/workflow/WorkflowDefinitionsView.vue', stubModule)
vi.mock('@/views/workflow/WorkflowDetailView.vue', stubModule)
vi.mock('@/views/knowledge/LawLibraryView.vue', stubModule)
vi.mock('@/views/knowledge/TemplateLibraryView.vue', stubModule)
vi.mock('@/views/knowledge/QaAssistantView.vue', stubModule)
vi.mock('@/views/system/UserManagementView.vue', stubModule)
vi.mock('@/views/system/RolePermissionView.vue', stubModule)
vi.mock('@/views/system/AuditLogView.vue', stubModule)
vi.mock('@/views/system/ModelPromptView.vue', stubModule)
vi.mock('@/views/system/AgentsView.vue', stubModule)
vi.mock('@/components/layout/AppLayout.vue', stubModule)

const user = { id: 1, realName: '张三', roles: ['reviewer'], token: 't' }

async function loadRouter() {
  vi.resetModules()
  const mod = await import('@/router')
  return mod.default
}

beforeEach(() => {
  currentUserMock.mockReset()
  document.title = ''
})

describe('router 全局守卫', () => {
  it('未登录访问受保护页面重定向到登录并带 redirect', async () => {
    currentUserMock.mockReturnValue(null)
    const router = await loadRouter()

    await router.push('/contracts').catch(() => undefined)
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/contracts')
  })

  it('强制改密用户同样被送去登录页', async () => {
    currentUserMock.mockReturnValue({ ...user, mustChangePassword: true })
    const router = await loadRouter()

    await router.push('/dashboard').catch(() => undefined)
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('已登录访问登录页重定向到仪表盘', async () => {
    currentUserMock.mockReturnValue(user)
    const router = await loadRouter()

    await router.push('/login').catch(() => undefined)
    expect(router.currentRoute.value.name).toBe('dashboard')
  })

  it('非管理员访问系统管理页被拦截回仪表盘', async () => {
    currentUserMock.mockReturnValue(user)
    const router = await loadRouter()

    await router.push('/system/users').catch(() => undefined)
    expect(router.currentRoute.value.name).toBe('dashboard')
  })

  it('管理员可正常进入系统管理页', async () => {
    currentUserMock.mockReturnValue({ ...user, roles: ['admin'] })
    const router = await loadRouter()

    await router.push('/system/users').catch(() => undefined)
    expect(router.currentRoute.value.name).toBe('system-users')
  })

  it('未知路径重定向到仪表盘', async () => {
    currentUserMock.mockReturnValue(user)
    const router = await loadRouter()

    await router.push('/not-exist-page').catch(() => undefined)
    expect(router.currentRoute.value.name).toBe('dashboard')
  })

  it('导航后更新 document.title 为「页面名 - 应用名」', async () => {
    currentUserMock.mockReturnValue(user)
    const router = await loadRouter()

    await router.push('/contracts').catch(() => undefined)
    expect(document.title).toContain(' - ')
  })

  it('根路径重定向到仪表盘', async () => {
    currentUserMock.mockReturnValue(user)
    const router = await loadRouter()

    await router.push('/').catch(() => undefined)
    expect(router.currentRoute.value.path).toBe('/dashboard')
  })
})
