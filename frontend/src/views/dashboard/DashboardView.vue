<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { fetchContracts } from '@/api/contracts'
import { fetchTasks, fetchReport, fetchFindings } from '@/api/reviews'
import { fetchInstances } from '@/api/workflows'
import { fetchNotifications, markNotificationRead, type AppNotification } from '@/api/system'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiMutation } from '@/composables/useApiQuery'
import { contractTypeLabels, formatDateTime, fromNow } from '@/utils/format'
import { translateData } from '@/utils/i18nData'
import PageHeader from '@/components/ui/PageHeader.vue'
import StatCard from '@/components/ui/StatCard.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseTable from '@/components/ui/BaseTable.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import Icon from '@/components/ui/Icon.vue'
import { useECharts } from '@/composables/useECharts'
import { chartBase, chartTokens } from '@/theme/chart'

const router = useRouter()
const { t, locale } = useI18n()

// ===== Data layer: TanStack Query (auto cache / dedup / invalidation refresh) =====
const { list: contracts, loading: loadingContracts, reload: reloadContracts } = useApiList(
  qk.contracts.list({ scope: 'dashboard' }),
  () => fetchContracts(),
)
const { list: tasks, reload: reloadTasks } = useApiList(qk.review.tasks(), () => fetchTasks())
const { list: instances, reload: reloadInstances } = useApiList(qk.workflow.instances(), () => fetchInstances())
const { list: findings, reload: reloadFindings } = useApiList(qk.review.findings(), () => fetchFindings())
const { list: notificationsRaw, reload: reloadNotifications } = useApiList(qk.system.notifications(), () => fetchNotifications())

const notifications = computed(() => notificationsRaw.value.slice(0, 6))
const loading = computed(() => loadingContracts.value)

const stats = computed(() => ({
  total: contracts.value.length,
  reviewing: tasks.value.filter((t) => t.status === 'running' || t.status === 'pending').length,
  approving: instances.value.filter((i) => i.status === 'running').length,
  risks: findings.value.length,
}))

const recentContracts = computed(() => contracts.value.slice(0, 6))

const todos = computed(() => {
  const list: Array<{ title: string; desc: string; tag: string; to: string }> = []
  for (const tk of tasks.value) {
    if (tk.status === 'running') list.push({ title: t('dashboard.todosReviewing', { title: tk.contractTitle }), desc: t('dashboard.todosProgress', { progress: tk.progress, time: fromNow(tk.createdAt) }), tag: t('dashboard.todosReviewTag'), to: '/review' })
    if (tk.status === 'pending') list.push({ title: t('dashboard.todosPending', { title: tk.contractTitle }), desc: t('dashboard.todosQueue', { id: tk.id }), tag: t('dashboard.todosReviewTag'), to: '/review' })
  }
  for (const i of instances.value) {
    if (i.status === 'running') list.push({ title: t('dashboard.todosApproval', { title: i.contractTitle }), desc: t('dashboard.todosNode', { node: translateData(i.currentNodeName), time: fromNow(i.startedAt) }), tag: t('dashboard.todosApprovalTag'), to: `/workflow/${i.id}` })
  }
  return list.slice(0, 6)
})

/** Manual refresh (toolbar button) */
async function load() {
  await Promise.all([
    reloadContracts(),
    reloadTasks(),
    reloadInstances(),
    reloadFindings(),
    reloadNotifications(),
  ])
  await renderCharts()
}

// ===== In-app notifications (review done / approval todo / timeout urge; click one to mark as read) =====
const readMutation = useApiMutation(
  (id: number) => markNotificationRead(id),
  {
    invalidate: qk.system.notifications(),
    onError: () => {
      /* Roll back the local read state on failure */
      void reloadNotifications()
    },
  },
)

async function onReadNotification(n: AppNotification) {
  if (n.read) return
  n.read = true
  try {
    await readMutation.mutateAsync(n.id)
  } catch {
    n.read = false
  }
}

const notifDot: Record<string, string> = {
  review_done: 'bg-accent',
  approval_todo: 'bg-warn-500',
  approval_timeout: 'bg-danger-500',
}

// ===== Charts =====
const trendEl = ref<HTMLElement | null>(null)
const riskEl = ref<HTMLElement | null>(null)
const { render: renderTrend } = useECharts(trendEl)
const { render: renderRisk } = useECharts(riskEl)

async function renderCharts() {
  const c = chartTokens()
  const base = chartBase(c)

  // Score trend (last 8 completed reports): straight segments, no points, single accent color, flat area fill within 14%
  const completed = tasks.value.filter((t) => t.status === 'completed').slice(0, 8)
  const scores: number[] = []
  for (const t of [...completed].reverse()) {
    const r = await fetchReport(t.id)
    if (r) scores.push(r.summary.score)
  }
  renderTrend({
    ...base,
    xAxis: {
      type: 'category',
      data: scores.map((_, i) => `#${completed.length - i}`),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: c.axis, fontSize: 12 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      interval: 25,
      splitLine: { lineStyle: { color: c.grid } },
      axisLine: { show: false },
      axisLabel: { color: c.axis, fontSize: 12 },
    },
    series: [
      {
        type: 'line',
        data: scores,
        smooth: false,
        symbol: 'none',
        lineStyle: { color: c.accent, width: 2 },
        itemStyle: { color: c.accent },
        areaStyle: { color: 'rgba(15, 118, 110, 0.12)' },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: c.warning, type: 'dashed', width: 1 },
          label: { formatter: t('dashboard.chart.approvalLine'), color: c.warning, fontSize: 11, position: 'end' },
          data: [{ yAxis: 85 }],
        },
      },
    ],
  })

  // Risk distribution: thin ring, no labels on the ring, status colors only for the high/medium risks that need judgement
  const high = findings.value.filter((f) => f.riskLevel === 'high').length
  const medium = findings.value.filter((f) => f.riskLevel === 'medium').length
  const low = findings.value.filter((f) => f.riskLevel === 'low').length
  renderRisk({
    textStyle: base.textStyle,
    tooltip: {
      trigger: 'item',
      backgroundColor: c.surface,
      borderColor: '#e5e7eb',
      borderWidth: 1,
      textStyle: { color: c.text, fontSize: 12 },
    },
    legend: {
      bottom: 0,
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
      textStyle: { color: c.axis, fontSize: 12 },
    },
    series: [
      {
        type: 'pie',
        radius: ['62%', '76%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        itemStyle: { borderWidth: 2, borderColor: c.surface },
        label: { show: false },
        data: [
          { value: high, name: t('dashboard.chart.highRisk', { n: high }), itemStyle: { color: c.negative } },
          { value: medium, name: t('dashboard.chart.mediumRisk', { n: medium }), itemStyle: { color: c.warning } },
          { value: low, name: t('dashboard.chart.lowRisk', { n: low }), itemStyle: { color: c.neutral } },
        ],
      },
    ],
  })
}

// Charts depend on tasks / findings; redraw after data arrives, on refresh, or on language switch
onMounted(() => {
  void renderCharts()
})
watch([tasks, findings, locale], () => {
  void renderCharts()
})
</script>

<template>
  <div>
    <PageHeader :title="t('dashboard.title')" :description="t('dashboard.description')">
      <template #actions>
        <button class="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-accent" @click="load">
          <Icon name="refresh" :size="14" :class="loading && 'animate-spin'" /> {{ t('common.refresh') }}
        </button>
      </template>
    </PageHeader>

    <!-- Stat cards -->
    <div class="grid grid-cols-2 xl:grid-cols-4 gap-4 mb-5">
      <StatCard :label="t('dashboard.statContracts')" :value="stats.total" icon="file-text" tone="primary" :trend="t('dashboard.statContractsTrend')" :link-text="t('dashboard.linkContracts')" @action="router.push('/contracts')" />
      <StatCard :label="t('dashboard.statReviewing')" :value="stats.reviewing" icon="sparkles" tone="warn" :trend="t('dashboard.statReviewingTrend')" :link-text="t('dashboard.linkReview')" @action="router.push('/review')" />
      <StatCard :label="t('dashboard.statApproving')" :value="stats.approving" icon="check-circle" tone="info" :trend="t('dashboard.statApprovingTrend')" :link-text="t('dashboard.linkApproval')" @action="router.push('/workflow')" />
      <StatCard :label="t('dashboard.statRisks')" :value="stats.risks" icon="alert-triangle" tone="danger" :trend="t('dashboard.statRisksTrend', { n: findings.filter((f) => f.riskLevel === 'high').length })" :link-text="t('dashboard.linkReport')" @action="router.push('/review')" />
    </div>

    <!-- Charts row -->
    <div class="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-5">
      <BaseCard :title="t('dashboard.trendTitle')" :subtitle="t('dashboard.trendSubtitle')" class="xl:col-span-2">
        <div ref="trendEl" class="h-64" />
      </BaseCard>
      <BaseCard :title="t('dashboard.riskTitle')" :subtitle="t('dashboard.riskSubtitle')">
        <div ref="riskEl" class="h-64" />
      </BaseCard>
    </div>

    <!-- Lists row -->
    <div class="grid grid-cols-1 xl:grid-cols-3 gap-4">
      <BaseCard :title="t('dashboard.recentContracts')" class="xl:col-span-2" padding="pb-2">
        <BaseTable
          :columns="[
            { key: 'title', label: t('dashboard.table.title') },
            { key: 'type', label: t('dashboard.table.type'), width: '110px' },
            { key: 'status', label: t('dashboard.table.status'), width: '110px' },
            { key: 'time', label: t('dashboard.table.time'), width: '150px' },
          ]"
          :loading="loading"
          :empty="recentContracts.length === 0"
        >
          <tr v-for="c in recentContracts" :key="c.id" class="hover:bg-raised cursor-pointer" @click="router.push(`/contracts/${c.id}`)">
            <td class="table-td">
              <p class="font-medium text-ink">{{ c.title }}</p>
              <p class="mt-0.5 text-xs text-ink-faint font-mono">{{ c.contractNo }}</p>
            </td>
            <td class="table-td">{{ contractTypeLabels[c.contractType] }}</td>
            <td class="table-td"><StatusBadge kind="contract" :value="c.status" /></td>
            <td class="table-td text-ink-muted">{{ formatDateTime(c.updatedAt) }}</td>
          </tr>
        </BaseTable>
      </BaseCard>

      <div class="flex flex-col gap-4">
        <BaseCard :title="t('dashboard.todos')" :subtitle="t('dashboard.todosSubtitle')">
          <div v-if="todos.length === 0" class="py-12 text-center text-sm text-ink-faint">{{ t('dashboard.todosEmpty') }}</div>
          <div v-else class="space-y-2.5">
            <button
              v-for="(todo, idx) in todos"
              :key="idx"
              class="w-full flex items-start gap-2.5 rounded-lg border border-line p-3 text-left hover:border-accent-track hover:bg-accent-soft/40 transition-colors"
              @click="router.push(todo.to)"
            >
              <span class="mt-1 h-2 w-2 rounded-full shrink-0" :class="todo.tag === t('dashboard.todosApprovalTag') ? 'bg-warn-500' : 'bg-accent'" />
              <span class="min-w-0">
                <span class="block text-sm font-medium text-ink truncate">{{ todo.title }}</span>
                <span class="block mt-0.5 text-xs text-ink-faint">{{ todo.desc }}</span>
              </span>
              <Icon name="chevron-right" :size="14" class="mt-1 ml-auto text-line-control shrink-0" />
            </button>
          </div>
        </BaseCard>

        <BaseCard :title="t('dashboard.notifications')" :subtitle="t('dashboard.notifSubtitle')">
          <div v-if="notifications.length === 0" class="py-10 text-center text-sm text-ink-faint">{{ t('dashboard.notificationsEmpty') }}</div>
          <div v-else class="space-y-2">
            <button
              v-for="n in notifications"
              :key="n.id"
              class="w-full flex items-start gap-2.5 rounded-lg border p-2.5 text-left transition-colors"
              :class="n.read ? 'border-line-rule opacity-60 hover:opacity-100' : 'border-line hover:border-accent-track hover:bg-accent-soft/40'"
              @click="onReadNotification(n)"
            >
              <span class="mt-1.5 h-2 w-2 rounded-full shrink-0" :class="notifDot[n.type] ?? 'bg-ink-faint'" />
              <span class="min-w-0 flex-1">
                <span class="block text-sm font-medium truncate" :class="n.read ? 'text-ink-muted' : 'text-ink'">{{ n.title }}</span>
                <span class="block mt-0.5 text-xs text-ink-faint line-clamp-2">{{ n.content }}</span>
                <span v-if="n.createdAt" class="block mt-1 text-[11px] text-line-control font-mono">{{ formatDateTime(n.createdAt) }}</span>
              </span>
              <span v-if="!n.read" class="mt-0.5 h-1.5 w-1.5 rounded-full bg-danger-500 shrink-0" :title="t('user.notRead')" />
            </button>
          </div>
        </BaseCard>
      </div>
    </div>
  </div>
</template>
