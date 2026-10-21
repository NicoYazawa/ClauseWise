<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQueryClient } from '@tanstack/vue-query'
import { fetchTask, fetchReport, resolveFinding, startReview, logReportExport } from '@/api/reviews'
import { fetchAgentTrace } from '@/api/agents'
import { fetchContract } from '@/api/contracts'
import { startApproval } from '@/api/workflows'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiDetail, useApiMutation } from '@/composables/useApiQuery'
import type { ReviewTask, ReviewReport, RiskFinding, Contract, AgentTraceItem } from '@/types'
import type { TimelineItem } from '@/components/ui/Timeline.vue'
import { canStartApproval, formatDateTime, formatDuration, findingStatusLabels, contractTypeLabels } from '@/utils/format'
import { buildReportHtml, downloadWord, printAsPdf } from '@/utils/export'
import { diffText, similarity, type DiffSeg } from '@/utils/diff'
import { toastSuccess, toastError, toastInfo } from '@/plugins/toast'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import RiskBadge from '@/components/ui/RiskBadge.vue'
import SourceBadge from '@/components/ui/SourceBadge.vue'
import ScoreRing from '@/components/ui/ScoreRing.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import Timeline from '@/components/ui/Timeline.vue'
import Icon from '@/components/ui/Icon.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const route = useRoute()
const router = useRouter()
const taskId = Number(route.params.taskId)
const queryClient = useQueryClient()

// ===== Data layer: TanStack Query =====
// 1) Task: auto-poll every 5s while running; auto-stop after completed/failed (replaces a hand-written setInterval state machine)
const {
  data: task,
  loading: taskLoading,
  error: taskError,
  reload: reloadTask,
} = useApiDetail<ReviewTask>(qk.review.task(taskId), () => fetchTask(taskId), {
  refetchInterval: (query: { state: { data?: unknown } }) => {
    const snapshot = query.state.data as ReviewTask | undefined
    return snapshot && (snapshot.status === 'running' || snapshot.status === 'pending') ? 5000 : false
  },
})

const isCompleted = computed(() => task.value?.status === 'completed')

// 2) Report: fetched only after the task completes; errors are layered independently and no longer share a field with task errors
const {
  data: report,
  loading: reportLoading,
  error: reportError,
  reload: reloadReport,
} = useApiDetail<ReviewReport | null>(qk.review.report(taskId), () => fetchReport(taskId), {
  enabled: isCompleted,
  retry: false,
})

// 3) Agent collaboration traces: fail silently (old tasks without traces do not affect report display)
const { list: agentTrace } = useApiList<AgentTraceItem>(
  qk.agents.trace(taskId),
  () => fetchAgentTrace('review', taskId),
  { enabled: isCompleted, retry: false },
)

// 4) Contract: the "rerun" on failure depends on it; fails silently
const contractId = computed(() => task.value?.contractId ?? 0)
const { data: contract } = useApiDetail<Contract>(
  computed(() => qk.contracts.detail(contractId.value)),
  () => fetchContract(contractId.value),
  { enabled: computed(() => contractId.value > 0), retry: false },
)

const agentPanelOpen = ref(false)
const levelFilter = ref<'all' | 'high' | 'medium' | 'low'>('all')
const expanding = ref<Set<number>>(new Set())
const acting = ref(false)

const loading = computed(() => taskLoading.value || reportLoading.value)

/** Error layering: task errors and report errors are attributed separately; Agent trace errors do not block display */
const loadError = computed(() => {
  if (taskError.value) return taskError.value instanceof Error ? taskError.value.message : t('review.report.taskFailed')
  if (reportError.value) return reportError.value instanceof Error ? reportError.value.message : t('review.report.reportFailed')
  return ''
})

function retryLoad() {
  reloadTask()
  if (isCompleted.value) reloadReport()
}

const filteredFindings = computed(() => {
  if (!report.value) return []
  return report.value.findings.filter((f) => levelFilter.value === 'all' || f.riskLevel === levelFilter.value)
})

const blocked = computed(() => (report.value?.summary.blockingHigh ?? 0) > 0)
/** Whether all rule-engine blocking items are applied (accepting one auto-amends the clause) -> guide a re-review to clear the block */
const highAllFixed = computed(() => {
  if (!report.value) return false
  const highs = report.value.findings.filter((f) => f.riskLevel === 'high' && f.source === 'rule')
  return highs.length > 0 && highs.every((f) => f.status === 'fixed')
})
const canApprove = computed(() => {
  if (!report.value) return false
  return canStartApproval(report.value.summary)
})

// ===== Agent collaboration timeline (LangGraph five-role traces -> Timeline component) =====
const ACTION_LABELS = computed<Record<string, { label: string; tone: TimelineItem['tagTone'] }>>(() => ({
  plan: { label: t('review.report.actionPlan'), tone: 'info' },
  tool_loop: { label: t('review.report.actionToolLoop'), tone: 'primary' },
  decision: { label: t('review.report.actionDecision'), tone: 'warn' },
  report: { label: t('review.report.actionReport'), tone: 'success' },
  message: { label: t('review.report.actionMessage'), tone: 'slate' },
}))

function traceSummary(item: AgentTraceItem): string {
  const p = item.payload ?? {}
  const str = (v: unknown): string => (typeof v === 'string' ? v : '')
  if (item.agentName === 'review_planner') {
    const output = p.output as { summary?: string; focusPoints?: string[] } | undefined
    const focus = Array.isArray(output?.focusPoints) ? output!.focusPoints!.slice(0, 3) : []
    const head = t('review.report.tracePlan', { summary: output?.summary ?? '' })
    return [head, ...focus.map((f) => t('review.report.traceFocus', { point: f }))].filter(Boolean).join('\n')
  }
  if (item.agentName === 'rule_auditor') return str(p.summary)
  if (item.agentName === 'clause_reviewer') {
    const tools = Array.isArray(p.tools) ? (p.tools as Array<{ tool: string }>).map((x) => x.tool) : []
    const r = p.result as { riskLevel?: string; riskType?: string } | undefined
    const toolPart = tools.length ? t('review.report.traceTools', { tools: tools.join(' → ') }) : ''
    const level = r?.riskLevel === 'none' ? t('review.report.traceNoRisk') : `${r?.riskLevel ?? '-'} | ${r?.riskType ?? ''}`
    const resultPart = t('review.report.traceConclusion', { result: level })
    return [toolPart, resultPart].filter(Boolean).join(' · ')
  }
  if (item.agentName === 'verifier') {
    const verdicts = p.verdicts as Array<{ index: number; verdict: string }> | undefined
    if (verdicts) {
      const vs = verdicts.map((v) => `#${v.index} ${v.verdict}`)
      return t('review.report.traceVerdict', {
        n: p.candidates ?? 0,
        verdicts: vs.join(', ') || t('review.report.traceKeepAll'),
      })
    }
    return str(p.summary)
  }
  if (item.agentName === 'reporter') {
    const s = p.stats as { score?: number; high?: number; medium?: number; low?: number } | undefined
    return s
      ? t('review.report.traceReporter', { score: s.score, high: s.high, medium: s.medium, low: s.low, opinion: str(p.opinion) })
      : str(p.opinion)
  }
  return ''
}

const agentTimeline = computed<TimelineItem[]>(() =>
  agentTrace.value.map((item) => {
    const clauseNo = item.payload?.clauseNo
    return {
      title: `${item.role}${item.agentName === 'clause_reviewer' && typeof clauseNo === 'string' ? ` · ${clauseNo}` : ''}`,
      time: `${(item.createdAt ?? '').slice(11)} · ${item.latencyMs}ms${item.tokens ? ` · ${item.tokens.toLocaleString()} tokens` : ''}`,
      tag: ACTION_LABELS.value[item.action]?.label ?? item.action,
      tagTone: ACTION_LABELS.value[item.action]?.tone ?? 'slate',
      content: item.error ? t('review.report.traceDegraded', { error: item.error }) : traceSummary(item),
    }
  }),
)

function toggleExpand(id: number) {
  const s = new Set(expanding.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  expanding.value = s
}

// ===== Original/suggested char-level diff (3.2.5): highlight when a rewritten full text meets the similarity threshold, otherwise show the whole block =====
const DIFF_THRESHOLD = 0.45

function diffPair(f: RiskFinding): { left: DiffSeg[]; right: DiffSeg[] } {
  const target = f.suggestedText ?? f.suggestion
  if (f.suggestedText && similarity(f.originalText, f.suggestedText) >= DIFF_THRESHOLD) {
    return diffText(f.originalText, f.suggestedText)
  }
  return {
    left: [{ type: 'same', text: f.originalText }],
    right: [{ type: 'same', text: f.suggestedText ?? target }],
  }
}

function isDiffable(f: RiskFinding): boolean {
  return !!f.suggestedText && similarity(f.originalText, f.suggestedText) >= DIFF_THRESHOLD
}

// ===== Mutation: risk disposition =====
const resolveMutation = useApiMutation(
  (payload: { id: number; status: 'accepted' | 'rejected' }) => resolveFinding(payload.id, payload.status),
  {
    invalidate: qk.review.findings(),
    onSuccess: (updated, payload) => {
      // Locally update the report cache: avoid refetching the whole report just to change one finding
      queryClient.setQueryData<ReviewReport>(qk.review.report(taskId), (old) => {
        if (!old) return old
        return {
          ...old,
          findings: old.findings.map((f) => (f.id === payload.id ? { ...f, ...updated } : f)),
        }
      })
      if (payload.status === 'accepted') {
        updated.applied
          ? toastSuccess(t('review.report.toastAccepted'))
          : toastSuccess(t('review.report.toastAcceptedNoRewrite'))
      } else {
        toastInfo(t('review.report.toastRejected'))
      }
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('review.report.resolveFailed')),
  },
)

async function onResolve(f: RiskFinding, status: 'accepted' | 'rejected') {
  await resolveMutation.mutateAsync({ id: f.id, status })
}

// ===== Mutation: re-review =====
const rerunMutation = useApiMutation(
  (payload: { contractId: number; taskType: 'full' | 'diff' }) => startReview(payload),
  {
    invalidate: qk.review.tasks(),
    onSuccess: (createdTask) => {
      toastSuccess(t('review.report.rerunCreated'))
      router.push(`/review/${createdTask.id}`)
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('review.errorStart')),
  },
)

async function onRerun() {
  if (!contract.value) return
  await rerunMutation.mutateAsync({
    contractId: contract.value.id,
    taskType: contract.value.currentVersion > 1 ? 'diff' : 'full',
  })
}

/** Export the report: Word downloads directly / PDF uses the browser's save-as, both written to the audit log */
const exportMutation = useApiMutation(
  (payload: { taskId: number; format: 'word' | 'pdf' }) => logReportExport(payload.taskId, payload.format),
)

async function onExport(format: 'word' | 'pdf') {
  if (!report.value || !contract.value || !task.value) return
  const html = buildReportHtml(report.value, contract.value, task.value)
  if (format === 'word') {
    downloadWord(
      html,
      t('review.report.exportFilename', { no: contract.value.contractNo, id: report.value.taskId }),
    )
    toastSuccess(t('review.report.exportWordToast'))
  } else {
    printAsPdf(html)
    toastInfo(t('review.report.exportPdfToast'))
  }
  await exportMutation.mutateAsync({ taskId: report.value.taskId, format })
}

// ===== Mutation: start approval =====
const approvalMutation = useApiMutation(
  (payload: {
    contractId: number
    contractTitle: string
    score: number
    amount: number
    highRisk: number
    riskTotal: number
  }) => startApproval(payload),
  {
    invalidate: qk.workflow.instances(),
    onSuccess: (inst) => {
      toastSuccess(t('review.report.approvalCreated'))
      router.push(`/workflow/${inst.id}`)
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('review.errorStart')),
  },
)

async function onStartApproval() {
  if (!report.value || !contract.value) return
  acting.value = true
  try {
    await approvalMutation.mutateAsync({
      contractId: contract.value.id,
      contractTitle: contract.value.title,
      score: report.value.summary.score,
      amount: contract.value.amount,
      highRisk: report.value.summary.blockingHigh,
      riskTotal: report.value.findings.length,
    })
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('review.errorStart'))
  } finally {
    acting.value = false
  }
}
</script>

<template>
  <div>
    <!-- Loading / in-progress state -->
    <div v-if="loading && !loadError" class="card p-20 text-center">
      <Icon name="refresh" :size="30" class="inline-block animate-spin text-ink-faint" />
      <p class="mt-3 text-sm text-ink-muted">{{ t('review.report.loading') }}</p>
    </div>

    <!-- Task/report fetch failed -->
    <div v-else-if="loadError" class="card p-12 text-center">
      <Icon name="alert-triangle" :size="30" class="mx-auto text-danger-500" />
      <p class="mt-2 text-sm text-danger-600">{{ loadError }}</p>
      <div class="mt-6 flex justify-center gap-3">
        <BaseButton icon="refresh" @click="retryLoad">{{ t('review.report.retry') }}</BaseButton>
        <BaseButton variant="secondary" @click="router.push('/review')">{{ t('review.report.backToList') }}</BaseButton>
      </div>
    </div>

    <div v-else-if="task && task.status !== 'completed'" class="card p-12">
      <div class="max-w-md mx-auto text-center">
        <Icon :name="task.status === 'failed' ? 'alert-triangle' : 'sparkles'" :size="36" class="mx-auto" :class="task.status === 'failed' ? 'text-danger-500' : 'text-accent'" />
        <h2 class="mt-4 text-lg font-bold text-ink">
          {{
            task.status === 'failed'
              ? t('review.report.statusFailed')
              : task.status === 'running'
                ? t('review.report.statusRunning')
                : t('review.report.statusPending')
          }}
        </h2>
        <p class="mt-2 text-sm text-ink-muted">{{ task.contractTitle }}</p>
        <div v-if="task.status !== 'failed'" class="mt-6 max-w-xs mx-auto">
          <ProgressBar :value="task.progress" status="active" show-label />
        </div>
        <p v-else class="mt-3 text-sm text-danger-600">{{ task.errorMsg }}</p>
        <div class="mt-6 flex justify-center gap-3">
          <BaseButton variant="secondary" @click="router.push('/review')">{{ t('review.report.backToList') }}</BaseButton>
          <BaseButton v-if="task.status === 'failed'" icon="refresh" @click="onRerun">{{ t('review.report.rerun') }}</BaseButton>
        </div>
      </div>
    </div>

    <!-- Report body -->
    <template v-else-if="task && report">
      <PageHeader
        :title="t('review.report.title')"
        :description="t('review.report.taskLabel', { title: task.contractTitle, id: task.id })"
      >
        <template #breadcrumb>
          <router-link to="/review" class="hover:text-accent">{{ t('review.report.crumbRoot') }}</router-link>
          <Icon name="chevron-right" :size="12" />
          <span class="text-ink-muted">{{ t('review.report.crumbReport', { id: task.id }) }}</span>
        </template>
        <template #actions>
          <BaseButton variant="secondary" icon="download" @click="onExport('word')">{{ t('review.report.exportWord') }}</BaseButton>
          <BaseButton variant="secondary" icon="file-text" @click="onExport('pdf')">{{ t('review.report.exportPdf') }}</BaseButton>
          <BaseButton
            v-if="!canApprove"
            variant="secondary"
            icon="refresh"
            :disabled="blocked && !highAllFixed"
            @click="onRerun"
          >{{ t('review.report.rerunAfterFix') }}</BaseButton>
          <BaseButton
            v-if="canApprove"
            icon="send"
            :loading="acting"
            @click="onStartApproval"
          >{{ t('review.report.startApproval') }}</BaseButton>
        </template>
      </PageHeader>

      <!-- High-risk blocking banner: blocking only looks at the rule engine; AI reference risks do not block. Once all blocking items are accepted, switch to a "pending re-review confirmation" hint -->
      <div
        v-if="blocked"
        class="mb-4 rounded-lg border p-4 flex items-start gap-3"
        :class="highAllFixed ? 'border-success-300 bg-success-50' : 'border-danger-300 bg-danger-50'"
      >
        <Icon :name="highAllFixed ? 'check-circle' : 'ban'" :size="20" class="mt-0.5 shrink-0" :class="highAllFixed ? 'text-success-600' : 'text-danger-600'" />
        <div class="flex-1">
          <p class="text-sm font-bold" :class="highAllFixed ? 'text-success-800' : 'text-danger-800'">
            {{ highAllFixed ? t('review.report.blockAppliedTitle') : t('review.report.blockTitle') }}
          </p>
          <p class="mt-1 text-sm leading-relaxed" :class="highAllFixed ? 'text-success-700' : 'text-danger-700'">
            {{
              highAllFixed
                ? t('review.report.blockAppliedDesc', { n: report.summary.blockingHigh })
                : t('review.report.blockDesc', { n: report.summary.blockingHigh })
            }}
          </p>
        </div>
        <BaseButton :variant="highAllFixed ? 'success' : 'danger'" size="sm" icon="refresh" @click="onRerun">{{ t('review.report.rerunShort') }}</BaseButton>
      </div>

      <!-- AI reference risk hint (non-blocking): shown when there is an AI high risk but no blocking item -->
      <div
        v-else-if="(report.summary.aiHigh ?? 0) > 0"
        class="mb-4 rounded-lg border border-warn-300 bg-warn-50 p-4 flex items-start gap-3"
      >
        <Icon name="info" :size="20" class="mt-0.5 text-warn-600 shrink-0" />
        <div class="flex-1">
          <p class="text-sm font-bold text-warn-800">{{ t('review.report.aiHintTitle', { n: report.summary.aiHigh }) }}</p>
          <p class="mt-1 text-sm text-warn-700 leading-relaxed">
            {{ t('review.report.aiHintDesc') }}
          </p>
        </div>
      </div>

      <!-- Summary card -->
      <div class="card p-5 mb-4">
        <div class="flex flex-col lg:flex-row items-center gap-8">
          <ScoreRing :score="report.summary.score" />
          <div class="flex-1 w-full">
            <div class="grid grid-cols-3 gap-3">
              <div class="rounded-lg border p-3.5 text-center" :class="report.summary.blockingHigh > 0 ? 'border-danger-200 bg-danger-50/50' : 'border-success-200 bg-success-50/50'">
                <p class="text-2xl font-bold tabular-nums" :class="report.summary.blockingHigh > 0 ? 'text-danger-700' : 'text-success-700'">{{ report.summary.high }}</p>
                <p class="mt-1 text-xs" :class="report.summary.blockingHigh > 0 ? 'text-danger-600' : 'text-success-600'">
                  {{ t('review.report.highRiskLabel') }}<span v-if="report.summary.blockingHigh > 0"> · {{ t('review.report.blockingCount', { n: report.summary.blockingHigh }) }}</span><span v-else> · {{ t('review.report.noBlocking') }}</span>
                </p>
              </div>
              <div class="rounded-lg border border-warn-200 bg-warn-50/50 p-3.5 text-center">
                <p class="text-2xl font-bold text-warn-700 tabular-nums">{{ report.summary.medium }}</p>
                <p class="mt-1 text-xs text-warn-600">{{ t('review.report.mediumRiskLabel') }}</p>
              </div>
              <div class="rounded-lg border border-info-200 bg-info-50/50 p-3.5 text-center">
                <p class="text-2xl font-bold text-info-700 tabular-nums">{{ report.summary.low }}</p>
                <p class="mt-1 text-xs text-info-600">{{ t('review.report.lowRiskLabel') }}</p>
              </div>
            </div>
            <div class="mt-4 rounded-md bg-raised border border-line p-3.5">
              <p class="text-xs font-medium text-ink-muted">{{ t('review.report.overallOpinion') }}</p>
              <p class="mt-1 text-sm text-ink leading-relaxed">{{ report.overallOpinion }}</p>
            </div>
          </div>
        </div>

        <!-- meta provenance bar -->
        <div class="mt-4 pt-4 border-t border-line-rule flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-ink-faint">
          <span class="flex items-center gap-1"><Icon name="cpu" :size="12" /> {{ t('review.report.metaModel', { model: report.meta.model }) }}</span>
          <span>{{ t('review.report.metaPrompt', { version: report.meta.promptVersion }) }}</span>
          <span>{{ t('review.report.metaTokens', { tokens: report.meta.tokensUsed.toLocaleString() }) }}</span>
          <span>{{ t('review.report.metaDuration', { duration: formatDuration(report.meta.durationMs) }) }}</span>
          <span>{{ t('review.report.metaCreatedAt', { time: formatDateTime(report.createdAt) }) }}</span>
          <span v-if="contract" class="ml-auto">{{ t('review.report.scoreGate', { score: report.summary.score, blocking: report.summary.blockingHigh }) }}</span>
        </div>
      </div>

      <!-- Agent collaboration process (LangGraph five-role traces: planner -> rule auditor -> clause reviewer x N -> verifier -> reporter) -->
      <BaseCard
        v-if="agentTimeline.length > 0"
        :title="t('review.report.agentTitle')"
        :subtitle="t('review.report.agentSubtitle')"
      >
        <template #actions>
          <button
            class="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors"
            :class="agentPanelOpen ? 'bg-accent text-white' : 'bg-line-rule text-ink-muted hover:bg-line'"
            @click="agentPanelOpen = !agentPanelOpen"
          >
            <Icon name="cpu" :size="12" />
            {{ agentPanelOpen ? t('review.report.agentCollapse') : t('review.report.agentExpand', { n: agentTimeline.length }) }}
          </button>
        </template>
        <div v-if="agentPanelOpen" class="max-h-[420px] overflow-y-auto pr-1">
          <Timeline :items="agentTimeline" />
        </div>
        <p v-else class="text-sm text-ink-faint">
          {{ t('review.report.agentSummary', { n: agentTimeline.length }) }}
        </p>
      </BaseCard>

      <!-- Risk list -->
      <BaseCard :title="t('review.report.findingsTitle')" :subtitle="t('review.report.findingsSubtitle')">
        <template #actions>
          <div class="flex items-center gap-1.5">
            <button
              v-for="opt in [
                { key: 'all', label: t('review.report.filterAll') },
                { key: 'high', label: t('review.report.filterHigh') },
                { key: 'medium', label: t('review.report.filterMedium') },
                { key: 'low', label: t('review.report.filterLow') },
              ]"
              :key="opt.key"
              class="px-2.5 py-1 rounded-md text-xs font-medium transition-colors"
              :class="levelFilter === opt.key ? 'bg-accent text-white' : 'bg-line-rule text-ink-muted hover:bg-line'"
              @click="levelFilter = opt.key as typeof levelFilter"
            >{{ opt.label }}</button>
          </div>
        </template>

        <div class="space-y-3">
          <div
            v-for="(f, idx) in filteredFindings"
            :key="f.id"
            class="rounded-lg border border-line overflow-hidden"
            :class="f.riskLevel === 'high' ? 'border-l-4 border-l-danger-500' : f.riskLevel === 'medium' ? 'border-l-4 border-l-warn-500' : 'border-l-4 border-l-info-400'"
          >
            <!-- Risk header -->
            <button class="w-full flex items-center gap-3 p-4 text-left hover:bg-raised" @click="toggleExpand(f.id)">
              <span class="text-sm font-mono text-ink-faint shrink-0">F-{{ f.id }}</span>
              <RiskBadge :level="f.riskLevel" />
              <span class="text-sm font-semibold text-ink">{{ f.riskType }}</span>
              <BaseBadge tone="slate">
                <Icon name="file-text" :size="11" />
                {{ f.clauseNo }}
              </BaseBadge>
              <SourceBadge :source="f.source" />
              <BaseBadge v-if="f.status !== 'open'" :tone="f.status === 'accepted' ? 'success' : 'slate'">{{ findingStatusLabels[f.status] }}</BaseBadge>
              <span class="ml-auto flex items-center gap-2 text-xs text-ink-faint truncate max-w-[260px] hidden md:block">{{ f.issue }}</span>
              <Icon :name="expanding.has(f.id) ? 'chevron-down' : 'chevron-right'" :size="15" class="text-line-control shrink-0" />
            </button>

            <!-- Expanded details -->
            <div v-if="expanding.has(f.id)" class="border-t border-line-rule p-4 bg-raised/50 space-y-3.5">
              <div>
                <p class="text-xs font-semibold text-ink-muted mb-1.5">{{ t('review.report.issueLabel') }}</p>
                <p class="text-sm text-ink leading-relaxed">{{ f.issue }}</p>
              </div>
              <div>
                <p class="text-xs font-semibold text-ink-muted mb-1.5">{{ t('review.report.clauseExcerpt') }}</p>
                <blockquote class="border-l-4 border-line-control bg-white rounded-r-md px-3.5 py-2.5 text-sm text-ink-muted leading-relaxed">
                  {{ f.clauseNo }}: {{ f.originalText }}
                </blockquote>
              </div>
              <div>
                <p class="text-xs font-semibold text-ink-muted mb-1.5">{{ t('review.report.legalBasisLabel') }}</p>
                <div class="rounded-md border border-accent-track bg-accent-soft/60 px-3.5 py-2.5">
                  <p class="text-sm text-accent-ink leading-relaxed">{{ f.legalBasis }}</p>
                </div>
                <div v-if="f.ragHits && f.ragHits.length > 0" class="mt-2 flex flex-wrap gap-1.5">
                  <span v-for="h in f.ragHits" :key="h" class="inline-flex items-center gap-1 rounded-md bg-line-rule border border-line px-2 py-0.5 text-[11px] text-ink-muted">
                    <Icon name="search" :size="10" class="text-accent" />{{ h }}
                  </span>
                </div>
              </div>

              <!-- Original vs suggested two columns (char-level diff highlight, 3.2.5) -->
              <div>
                <p class="text-xs font-semibold text-ink-muted mb-1.5">
                  {{ isDiffable(f) ? t('review.report.suggestionDiffLabel') : t('review.report.suggestionLabel') }}
                </p>
                <p v-if="!f.suggestedText" class="mb-2 text-xs text-ink-muted leading-relaxed">{{ f.suggestion }}</p>
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  <div class="rounded-md border border-danger-200 bg-danger-50/50 p-3">
                    <p class="mb-1.5 text-xs font-medium text-danger-700">
                      {{ t('review.report.originalLabel') }}<span v-if="isDiffable(f)" class="ml-1 font-normal">{{ t('review.report.delHint') }}</span>
                    </p>
                    <p class="text-sm text-ink-muted leading-relaxed">
                      <template v-for="(seg, si) in diffPair(f).left" :key="si">
                        <span v-if="seg.type === 'del'" class="bg-danger-200/70 text-danger-800 line-through rounded-sm">{{ seg.text }}</span>
                        <template v-else>{{ seg.text }}</template>
                      </template>
                    </p>
                  </div>
                  <div class="rounded-md border border-success-200 bg-success-50/50 p-3">
                    <p class="mb-1.5 text-xs font-medium text-success-700">
                      {{ t('review.report.revisedLabel') }}<span v-if="isDiffable(f)" class="ml-1 font-normal">{{ t('review.report.addHint') }}</span>
                    </p>
                    <p class="text-sm text-ink leading-relaxed">
                      <template v-for="(seg, si) in diffPair(f).right" :key="si">
                        <span v-if="seg.type === 'add'" class="bg-success-200/70 text-success-800 rounded-sm">{{ seg.text }}</span>
                        <template v-else>{{ seg.text }}</template>
                      </template>
                    </p>
                  </div>
                </div>
              </div>

              <!-- Disposition actions -->
              <div class="flex items-center gap-2.5 pt-1">
                <template v-if="f.status === 'open'">
                  <BaseButton size="sm" variant="success" icon="thumbs-up" @click="onResolve(f, 'accepted')">{{ t('review.report.acceptAction') }}</BaseButton>
                  <BaseButton size="sm" variant="secondary" icon="thumbs-down" @click="onResolve(f, 'rejected')">{{ t('review.report.rejectAction') }}</BaseButton>
                  <span class="text-xs text-ink-faint">{{ t('review.report.resolveHint') }}</span>
                </template>
                <template v-else>
                  <BaseBadge :tone="f.status === 'rejected' ? 'slate' : 'success'">{{ findingStatusLabels[f.status] }}</BaseBadge>
                  <span class="text-xs text-ink-faint">{{ t('review.report.traceHint') }}</span>
                </template>
              </div>
            </div>
          </div>

          <p v-if="filteredFindings.length === 0" class="py-12 text-center text-sm text-ink-faint">{{ t('review.report.noFindingInLevel') }}</p>
        </div>
      </BaseCard>

      <p class="mt-3 text-xs text-ink-faint">
        {{ t('review.report.footerNote') }}
        {{ t('review.report.contractTypeLabel', { type: contract ? contractTypeLabels[contract.contractType] : '-' }) }}
        {{ t('review.report.reviewTypeLabel', { type: task.taskType === 'full' ? t('review.report.reviewTypeFull') : task.taskType === 'clause' ? t('review.report.reviewTypeClause') : t('review.report.reviewTypeDiff') }) }}
      </p>
    </template>

    <!-- Task completed but no report (abnormal fallback) -->
    <div v-else class="card p-16 text-center">
      <Icon name="inbox" :size="30" class="mx-auto text-line-control" />
      <p class="mt-2 text-sm text-ink-muted">{{ t('review.report.noReport') }}</p>
    </div>
  </div>
</template>
