import { createRouter, createWebHistory } from 'vue-router'
import { currentUser } from '@/stores/auth'
import { i18n } from '@/i18n'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/login/LoginView.vue'),
      meta: { public: true, titleKey: 'common.login' },
    },
    {
      path: '/',
      component: () => import('@/components/layout/AppLayout.vue'),
      children: [
        { path: '', redirect: '/dashboard' },
        { path: 'dashboard', name: 'dashboard', component: () => import('@/views/dashboard/DashboardView.vue'), meta: { titleKey: 'menu.dashboard' } },
        { path: 'contracts', name: 'contracts', component: () => import('@/views/contracts/ContractListView.vue'), meta: { titleKey: 'menu.contracts' } },
        { path: 'contracts/:id', name: 'contract-detail', component: () => import('@/views/contracts/ContractDetailView.vue'), meta: { titleKey: 'menu.contracts' } },
        { path: 'contracts/:id/diff', name: 'contract-diff', component: () => import('@/views/contracts/ContractDiffView.vue'), meta: { titleKey: 'menu.contracts' } },
        { path: 'review', name: 'review', component: () => import('@/views/review/ReviewTaskListView.vue'), meta: { titleKey: 'menu.review' } },
        { path: 'review/:taskId', name: 'review-report', component: () => import('@/views/review/ReviewReportView.vue'), meta: { titleKey: 'menu.review' } },
        { path: 'search', name: 'global-search', component: () => import('@/views/search/GlobalSearchView.vue'), meta: { titleKey: 'search.title' } },
        { path: 'workflow', name: 'workflow', component: () => import('@/views/workflow/WorkflowListView.vue'), meta: { titleKey: 'menu.workflow' } },
        { path: 'workflow/definitions', name: 'workflow-definitions', component: () => import('@/views/workflow/WorkflowDefinitionsView.vue'), meta: { titleKey: 'menu.workflowDefinitions' } },
        { path: 'workflow/:id', name: 'workflow-detail', component: () => import('@/views/workflow/WorkflowDetailView.vue'), meta: { titleKey: 'menu.workflow' } },
        { path: 'knowledge/laws', name: 'knowledge-laws', component: () => import('@/views/knowledge/LawLibraryView.vue'), meta: { titleKey: 'menu.laws' } },
        { path: 'knowledge/templates', name: 'knowledge-templates', component: () => import('@/views/knowledge/TemplateLibraryView.vue'), meta: { titleKey: 'menu.templates' } },
        { path: 'knowledge/qa', name: 'knowledge-qa', component: () => import('@/views/knowledge/QaAssistantView.vue'), meta: { titleKey: 'menu.qa' } },
        { path: 'system/users', name: 'system-users', component: () => import('@/views/system/UserManagementView.vue'), meta: { titleKey: 'menu.users', adminOnly: true } },
        { path: 'system/roles', name: 'system-roles', component: () => import('@/views/system/RolePermissionView.vue'), meta: { titleKey: 'menu.roles', adminOnly: true } },
        { path: 'system/audit-logs', name: 'system-audit', component: () => import('@/views/system/AuditLogView.vue'), meta: { titleKey: 'menu.audit', adminOnly: true } },
        { path: 'system/models', name: 'system-models', component: () => import('@/views/system/ModelPromptView.vue'), meta: { titleKey: 'menu.models', adminOnly: true } },
        { path: 'system/agents', name: 'system-agents', component: () => import('@/views/system/AgentsView.vue'), meta: { titleKey: 'menu.agents', adminOnly: true } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.beforeEach((to) => {
  const user = currentUser()
  if (!to.meta.public && (!user || user.mustChangePassword)) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && user && !user.mustChangePassword) {
    return { name: 'dashboard' }
  }
  // Simple RBAC: system management is admin-only
  if (to.meta.adminOnly && !user?.roles?.includes('admin')) {
    return { name: 'dashboard' }
  }
  const titleKey = (to.meta.titleKey as string) ?? 'app.name'
  document.title = `${i18n.global.t(titleKey)} - ${i18n.global.t('app.name')}`
})

export default router
