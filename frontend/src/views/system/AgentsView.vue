<script setup lang="ts">
import { computed } from 'vue'
import { listAgents, fetchRecentTraces } from '@/api/agents'
import { qk } from '@/api/queryKeys'
import { useApiList } from '@/composables/useApiQuery'
import type { AgentInfo, AgentTraceItem, AgentKind } from '@/types'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseTable from '@/components/ui/BaseTable.vue'
import Icon from '@/components/ui/Icon.vue'
import { useI18n } from 'vue-i18n'
import { translateData } from '@/utils/i18nData'

const { t } = useI18n()

/** Agent overview: registry list (LangGraph collaboration-graph roles) + recent collaboration traces */

// ===== Data layer: TanStack Query (two lists in parallel, auto-degrade to empty on failure) =====
const { list: agents, loading } = useApiList<AgentInfo>(qk.agents.registry(), () => listAgents(), { retry: false })
const { list: traces, loading: traceLoading } = useApiList<AgentTraceItem>(
  qk.agents.recentTraces(),
  () => fetchRecentTraces(60),
  { retry: false },
)

const GRAPH_META = computed<Record<string, { title: string; description: string; icon: string }>>(() => ({
  review_graph: {
    title: t('system.agents.graphReviewTitle'),
    description: t('system.agents.graphReviewDesc'),
    icon: 'sparkles',
  },
  qa_graph: {
    title: t('system.agents.graphQaTitle'),
    description: t('system.agents.graphQaDesc'),
    icon: 'book-open',
  },
}))

const KIND_BADGE = computed<Record<AgentKind, { label: string; tone: 'primary' | 'info' | 'slate' }>>(() => ({
  llm: { label: t('system.agents.kindLlm'), tone: 'primary' },
  structured: { label: t('system.agents.kindStructured'), tone: 'info' },
  deterministic: { label: t('system.agents.kindDeterministic'), tone: 'slate' },
}))

const grouped = computed<{ key: string; meta: { title: string; description: string; icon: string }; items: AgentInfo[] }[]>(() => {
  const byGraph = new Map<string, AgentInfo[]>()
  for (const a of agents.value) {
    if (!byGraph.has(a.graph)) byGraph.set(a.graph, [])
    byGraph.get(a.graph)!.push(a)
  }
  return [...byGraph.entries()].map(([key, items]) => ({
    key,
    meta: GRAPH_META.value[key] ?? { title: key, description: '', icon: 'cpu' },
    items,
  }))
})

const traceColumns = computed(() => [
  { key: 'time', label: t('system.agents.colTime'), width: '150px' },
  { key: 'task', label: t('system.agents.colTask'), width: '130px' },
  { key: 'agent', label: t('system.agents.colAgent') },
  { key: 'action', label: t('system.agents.colAction'), width: '110px' },
  { key: 'summary', label: t('system.agents.colSummary') },
  { key: 'cost', label: t('system.agents.colCost'), width: '130px', align: 'right' as const },
])

function traceSummary(item: AgentTraceItem): string {
  const p = item.payload ?? {}
  const str = (v: unknown): string => (typeof v === 'string' ? v : '')
  if (item.agentName === 'review_planner' || item.agentName === 'qa_planner') {
    const queries = (p.subQueries ?? (p.output as { focusPoints?: string[] } | undefined)?.focusPoints) as string[] | undefined
    return queries?.length ? t('system.agents.summaryPlanning', { items: queries.slice(0, 2).join(', ') }) : str(p.summary)
  }
  if (item.agentName === 'rule_auditor') {
    const findings = (p.findings as unknown[] | undefined) ?? []
    return t('system.agents.summaryRuleAudit', { n: findings.length })
  }
  if (item.agentName === 'clause_reviewer') {
    if (p.error) return t('system.agents.summaryClauseFailed')
    const tools = Array.isArray(p.tools) ? (p.tools as unknown[]).length : 0
    const clauseNo = typeof p.clauseNo === 'string' ? p.clauseNo : ''
    return t('system.agents.summaryClause', { clause: clauseNo, n: tools })
  }
  if (item.agentName === 'verifier') {
    if (p.error) return t('system.agents.summaryVerifierFailed')
    if (typeof p.candidates === 'number') {
      return t('system.agents.summaryVerifierDone', { candidates: p.candidates, merged: p.merged ?? p.candidates })
    }
    return str(p.summary) || t('system.agents.summaryVerifier', { n: p.candidates ?? 0 })
  }
  if (item.agentName === 'reporter') {
    const s = p.stats as { score?: number } | undefined
    return s ? t('system.agents.summaryOpinion', { score: s.score }) : str(p.opinion)
  }
  if (item.agentName === 'qa_router') return t('system.agents.summaryRoute', { intent: (p.route as { intent?: string } | undefined)?.intent ?? '' })
  if (item.agentName === 'retriever') return t('system.agents.summaryHits', { n: p.hits ?? 0 })
  if (item.agentName === 'qa_grader') return t('system.agents.summaryGrader', { relevant: p.relevant ?? 0, total: p.total ?? 0 })
  if (item.agentName === 'qa_reflector') {
    return t('system.agents.summaryReflector', {
      pass: p.passed ? t('system.agents.reflectorPass') : t('system.agents.reflectorFail'),
      regen: p.regen ? t('system.agents.reflectorRegen') : '',
    })
  }
  if (item.agentName === 'qa_answerer') {
    if (p.noHit) return t('system.agents.summaryNoHit')
    return t('system.agents.summaryAnswererCited', { n: p.citations ?? 0 })
  }
  if (item.agentName === 'qa_corrector') return t('system.agents.summaryCorrector')
  return str(p.summary) || str(p.opinion)
}

function taskLabel(item: AgentTraceItem): string {
  return item.taskType === 'review' ? t('system.agents.taskReview', { id: item.refId }) : t('system.agents.taskQa')
}
</script>

<template>
  <div>
    <PageHeader
      :title="t('system.agents.title')"
      :description="t('system.agents.description')"
    >
      <template #actions>
        <span class="flex items-center gap-1.5 text-xs text-ink-faint">
          <Icon name="cpu" :size="13" />
          {{ t('system.agents.registryCount', { n: agents.length }) }}
        </span>
      </template>
    </PageHeader>

    <!-- Registry: grouped by collaboration graph -->
    <div v-if="loading" class="card p-20 text-center">
      <Icon name="refresh" :size="30" class="inline-block animate-spin text-ink-faint" />
      <p class="mt-3 text-sm text-ink-muted">{{ t('system.agents.loading') }}</p>
    </div>

    <template v-else>
      <BaseCard v-for="group in grouped" :key="group.key" :title="group.meta.title" :subtitle="group.meta.description" class="mb-4">
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          <div
            v-for="a in group.items"
            :key="a.name"
            class="rounded-lg border border-line p-3.5 hover:border-accent-track transition-colors"
          >
            <div class="flex items-center gap-2">
              <span class="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-accent-soft text-accent shrink-0">
                <Icon name="cpu" :size="14" />
              </span>
              <div class="min-w-0">
                <p class="text-sm font-semibold text-ink truncate">{{ translateData(a.role) }}</p>
                <p class="text-[11px] font-mono text-ink-faint truncate">{{ a.name }}</p>
              </div>
              <BaseBadge class="ml-auto shrink-0" :tone="KIND_BADGE[a.kind].tone">{{ KIND_BADGE[a.kind].label }}</BaseBadge>
            </div>
            <p class="mt-2 text-xs text-ink-muted leading-relaxed">{{ a.descKey ? t(a.descKey) : a.description }}</p>
            <div v-if="a.tools.length > 0" class="mt-2 flex flex-wrap gap-1">
              <span
                v-for="tool in a.tools"
                :key="tool"
                class="inline-flex items-center gap-0.5 rounded bg-line-rule border border-line px-1.5 py-0.5 text-[10px] font-mono text-ink-muted"
              >
                <Icon name="wrench" :size="9" class="text-accent" />
                {{ tool }}
              </span>
            </div>
          </div>
        </div>
      </BaseCard>
    </template>

    <!-- Recent collaboration traces -->
    <BaseCard :title="t('system.agents.traceTitle')" :subtitle="t('system.agents.traceSubtitle')">
      <BaseTable :columns="traceColumns" :loading="traceLoading" :empty="traces.length === 0" :empty-text="t('system.agents.traceEmpty')">
        <tr v-for="item in traces" :key="item.id" class="hover:bg-raised">
          <td class="table-td text-xs text-ink-faint">{{ (item.createdAt ?? '').replace('T', ' ') }}</td>
          <td class="table-td">
            <BaseBadge :tone="item.taskType === 'review' ? 'primary' : 'info'">{{ taskLabel(item) }}</BaseBadge>
          </td>
          <td class="table-td">
            <span class="text-sm font-medium text-ink">{{ translateData(item.role) }}</span>
            <span class="ml-1.5 text-[10px] font-mono text-ink-faint">{{ item.agentName }}</span>
          </td>
          <td class="table-td text-xs text-ink-muted">{{ item.action }}</td>
          <td class="table-td">
            <span class="text-xs text-ink-muted" :class="item.error ? 'text-danger-600' : ''">
              {{ item.error ? t('system.agents.traceError', { error: item.error.slice(0, 60) }) : traceSummary(item) }}
            </span>
          </td>
          <td class="table-td text-right text-xs text-ink-faint tabular-nums">
            {{ item.latencyMs }}ms<template v-if="item.tokens"> · {{ item.tokens.toLocaleString() }} tk</template>
          </td>
        </tr>
      </BaseTable>
    </BaseCard>
  </div>
</template>
