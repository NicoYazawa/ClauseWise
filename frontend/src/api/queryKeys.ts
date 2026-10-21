/**
 * Unified query-key factory (TanStack Query).
 *
 * Convention: all invalidation goes through the qk.* prefix for prefix-matched
 * invalidation, e.g. invalidating all contract caches -> queryClient.invalidateQueries({ queryKey: qk.contracts.all })
 */
export const qk = {
  contracts: {
    all: ['contracts'] as const,
    list: (params: Record<string, unknown>) => ['contracts', 'list', params] as const,
    detail: (id: number) => ['contracts', 'detail', id] as const,
    versions: (id: number) => ['contracts', 'versions', id] as const,
    clauses: (versionId: number) => ['contracts', 'clauses', versionId] as const,
    diff: (id: number, base: number, target: number) => ['contracts', 'diff', id, base, target] as const,
  },
  review: {
    all: ['review'] as const,
    tasks: () => ['review', 'tasks'] as const,
    task: (id: number) => ['review', 'task', id] as const,
    progress: (id: number) => ['review', 'progress', id] as const,
    report: (id: number) => ['review', 'report', id] as const,
    findings: () => ['review', 'findings'] as const,
  },
  knowledge: {
    all: ['knowledge'] as const,
    laws: () => ['knowledge', 'laws'] as const,
    templates: () => ['knowledge', 'templates'] as const,
  },
  system: {
    all: ['system'] as const,
    users: () => ['system', 'users'] as const,
    roles: () => ['system', 'roles'] as const,
    notifications: () => ['system', 'notifications'] as const,
    auditLogs: () => ['system', 'audit-logs'] as const,
    auditLogsFiltered: (params: Record<string, unknown>) => ['system', 'audit-logs', params] as const,
    models: () => ['system', 'models'] as const,
    runtimeInfo: () => ['system', 'runtime-info'] as const,
    prompts: () => ['system', 'prompts'] as const,
  },
  workflow: {
    all: ['workflow'] as const,
    definitions: () => ['workflow', 'definitions'] as const,
    instances: () => ['workflow', 'instances'] as const,
    detail: (id: number) => ['workflow', 'detail', id] as const,
  },
  agents: {
    all: ['agents'] as const,
    registry: () => ['agents', 'registry'] as const,
    trace: (id: number) => ['agents', 'trace', id] as const,
    recentTraces: () => ['agents', 'trace', 'recent'] as const,
  },
  dashboard: () => ['dashboard'] as const,
}