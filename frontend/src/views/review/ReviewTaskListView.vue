<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { fetchTasks, startReview } from '@/api/reviews'
import { fetchContracts, fetchVersions, fetchClauses } from '@/api/contracts'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiMutation } from '@/composables/useApiQuery'
import type { ReviewTask, ReviewTaskType, Contract, ContractVersion, ContractClause } from '@/types'
import { formatDateTime, formatDuration } from '@/utils/format'
import { toastSuccess, toastError } from '@/plugins/toast'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseTable from '@/components/ui/BaseTable.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import Icon from '@/components/ui/Icon.vue'

const { t } = useI18n()
const router = useRouter()

// ===== Data layer: TanStack Query (auto-poll every 5s while a task is running) =====
const { list: tasks, loading, reload: load } = useApiList(qk.review.tasks(), () => fetchTasks(), {
  refetchInterval: (query: { state: { data?: unknown } }) => {
    const list = query.state.data as ReviewTask[] | undefined
    return list?.some((t) => t.status === 'running' || t.status === 'pending') ? 5000 : false
  },
})

// Tone is language-independent; label comes from the locale.
const typeTone: Record<ReviewTaskType, 'primary' | 'info' | 'warn'> = { full: 'primary', clause: 'info', diff: 'warn' }

// ===== Start review modal =====
const startOpen = ref(false)
const form = ref({ contractId: '', taskType: 'full' as ReviewTaskType, baseVersionNo: '', clauseNo: '' })
const starting = ref(false)

const { list: contracts } = useApiList(
  computed(() => qk.contracts.list({ scope: 'review-start' })),
  () => fetchContracts({ status: '' }),
  { enabled: computed(() => startOpen.value) },
)

const { list: versions } = useApiList(
  computed(() => qk.contracts.versions(Number(form.value.contractId) || 0)),
  () => fetchVersions(Number(form.value.contractId)),
  { enabled: computed(() => !!form.value.contractId) },
)

const latestParsedVersionId = computed(() => versions.value.find((v) => v.parseStatus === 'parsed')?.id ?? 0)

const { list: clauses } = useApiList(
  computed(() => qk.contracts.clauses(latestParsedVersionId.value)),
  () => fetchClauses(latestParsedVersionId.value),
  { enabled: computed(() => latestParsedVersionId.value > 0) },
)

function openStart() {
  startOpen.value = true
}

const contractOptions = computed(() =>
  contracts.value
    .filter((c) => ['parsed', 'review_passed', 'review_blocked'].includes(c.status))
    .map((c) => ({ value: String(c.id), label: `${c.contractNo} · ${c.title}` })),
)

function onContractChange() {
  form.value.baseVersionNo = ''
  form.value.clauseNo = ''
}

const versionOptions = computed(() =>
  versions.value
    .filter((v) => v.parseStatus === 'parsed' && v.versionNo < (versions.value[0]?.versionNo ?? 0))
    .map((v) => ({ value: String(v.versionNo), label: `v${v.versionNo} · ${v.fileName}` })),
)

const startMutation = useApiMutation(
  (payload: Parameters<typeof startReview>[0]) => startReview(payload),
  {
    invalidate: qk.review.tasks(),
    onSuccess: (task) => {
      toastSuccess(t('review.createdToast', { id: task.id }))
      startOpen.value = false
      router.push(`/review/${task.id}`)
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('review.errorStart')),
  },
)

async function submitStart() {
  if (!form.value.contractId) {
    toastError(t('review.errorNoContract'))
    return
  }
  if (form.value.taskType === 'diff' && !form.value.baseVersionNo) {
    toastError(t('review.errorNoBase'))
    return
  }
  if (form.value.taskType === 'clause' && !form.value.clauseNo) {
    toastError(t('review.errorNoClause'))
    return
  }
  starting.value = true
  try {
    await startMutation.mutateAsync({
      contractId: Number(form.value.contractId),
      taskType: form.value.taskType,
      baseVersionNo: form.value.baseVersionNo ? Number(form.value.baseVersionNo) : undefined,
      clauseNo: form.value.clauseNo || undefined,
    })
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('review.errorStart'))
  } finally {
    starting.value = false
  }
}
</script>

<template>
  <div>
    <PageHeader :title="t('review.title')" :description="t('review.description')">
      <template #actions>
        <BaseButton icon="sparkles" @click="openStart">{{ t('review.start') }}</BaseButton>
      </template>
    </PageHeader>

    <div class="card">
      <BaseTable
        :columns="[
          { key: 'id', label: t('review.colId'), width: '70px' },
          { key: 'contract', label: t('review.colContract') },
          { key: 'type', label: t('review.colType'), width: '110px' },
          { key: 'status', label: t('review.colStatus'), width: '100px' },
          { key: 'progress', label: t('review.colProgress'), width: '170px' },
          { key: 'meta', label: t('review.colModel'), width: '200px' },
          { key: 'time', label: t('review.colDuration'), width: '80px', align: 'right' },
          { key: 'actions', label: t('review.colActions'), width: '96px' },
        ]"
        :loading="loading"
        :empty="tasks.length === 0"
        :empty-text="t('review.empty')"
      >
        <tr v-for="task in tasks" :key="task.id" class="hover:bg-raised">
          <td class="table-td font-mono text-ink-muted">#{{ task.id }}</td>
          <td class="table-td">
            <p class="font-medium text-ink">{{ task.contractTitle }}</p>
            <p class="mt-0.5 text-xs text-ink-faint">
              {{ formatDateTime(task.createdAt) }}<span v-if="task.clauseNo"> · {{ t('review.targetClause') }} <b class="font-mono text-ink-muted">{{ task.clauseNo }}</b></span>
            </p>
          </td>
          <td class="table-td"><BaseBadge :tone="typeTone[task.taskType]">{{ t(`status.reviewType.${task.taskType}`) }}</BaseBadge></td>
          <td class="table-td"><StatusBadge kind="task" :value="task.status" /></td>
          <td class="table-td">
            <ProgressBar
              :value="task.progress"
              :status="task.status === 'completed' ? 'done' : task.status === 'failed' ? 'error' : task.status === 'running' ? 'active' : 'normal'"
              show-label
            />
            <p v-if="task.status === 'failed' && task.errorMsg" class="mt-1 text-xs text-danger-600">{{ task.errorMsg }}</p>
          </td>
          <td class="table-td">
            <p class="text-xs text-ink-muted font-mono truncate">{{ task.modelVersion }}</p>
            <p class="mt-0.5 text-xs text-ink-faint">Prompt {{ task.promptVersion }}</p>
          </td>
          <td class="table-td text-right text-ink-muted tabular-nums">{{ formatDuration(task.durationMs) }}</td>
          <td class="table-td">
            <button
              v-if="task.status === 'completed'"
              class="text-sm text-accent hover:underline"
              @click="router.push(`/review/${task.id}`)"
            >{{ t('review.viewReport') }}</button>
            <span v-else-if="task.status === 'running' || task.status === 'pending'" class="text-sm text-ink-faint">{{ t('review.running') }}</span>
            <button v-else class="text-sm text-ink-faint hover:text-ink-muted" :title="t('review.failDetailTitle')" @click="toastError(task.errorMsg ?? t('review.errorStart'))">{{ t('review.failDetail') }}</button>
          </td>
        </tr>
      </BaseTable>
    </div>

    <!-- Start review modal -->
    <BaseModal v-model:open="startOpen" :title="t('review.startTitle')" width="max-w-lg" @close="startOpen = false">
      <div class="space-y-4">
        <div>
          <label class="label">{{ t('review.selectContract') }}</label>
          <select v-model="form.contractId" class="input cursor-pointer" @change="onContractChange">
            <option value="">{{ t('review.contractPlaceholder') }}</option>
            <option v-for="o in contractOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
        </div>
        <div>
          <label class="label">{{ t('review.typeLabel') }}</label>
          <div class="grid grid-cols-3 gap-2">
            <button
              v-for="(meta, key) in typeTone"
              :key="key"
              type="button"
              class="rounded-md border p-3 text-left transition-colors"
              :class="form.taskType === key ? 'border-accent bg-accent-soft' : 'border-line hover:border-accent-track'"
              @click="form.taskType = key"
            >
              <p class="text-sm font-medium" :class="form.taskType === key ? 'text-accent-ink' : 'text-ink'">{{ t(`status.reviewType.${key}`) }}</p>
              <p class="mt-0.5 text-xs text-ink-faint">{{ t(`review.typeDesc.${key}`) }}</p>
            </button>
          </div>
        </div>
        <div v-if="form.taskType === 'diff'">
          <label class="label">{{ t('review.baseVersionLabel') }}</label>
          <select v-model="form.baseVersionNo" class="input cursor-pointer">
            <option value="">{{ t('review.baseVersionPlaceholder') }}</option>
            <option v-for="o in versionOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
          <p v-if="versionOptions.length === 0" class="mt-1.5 text-xs text-warn-600">{{ t('review.noVersions') }}</p>
        </div>
        <div v-if="form.taskType === 'clause'">
          <label class="label">{{ t('review.clauseLabel') }}</label>
          <select v-model="form.clauseNo" class="input cursor-pointer">
            <option value="">{{ t('review.clausePlaceholder') }}</option>
            <option v-for="cl in clauses" :key="cl.id" :value="cl.clauseNo">{{ cl.clauseNo }} · {{ cl.clauseType }} · {{ cl.content.slice(0, 30) }}…</option>
          </select>
          <p v-if="clauses.length === 0" class="mt-1.5 text-xs text-warn-600">{{ t('review.noClauses') }}</p>
          <p v-else-if="form.clauseNo" class="mt-1.5 text-xs text-ink-faint line-clamp-2">{{ clauses.find((c) => c.clauseNo === form.clauseNo)?.content }}</p>
        </div>
        <div class="rounded-md bg-raised border border-line p-3 text-xs text-ink-muted leading-relaxed">
          <p class="flex items-center gap-1.5 font-medium text-ink-muted"><Icon name="cpu" :size="13" /> {{ t('review.execChainTitle') }}</p>
          <p class="mt-1.5">{{ t('review.execChain') }}</p>
        </div>
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="startOpen = false">{{ t('common.cancel') }}</BaseButton>
        <BaseButton icon="send" :loading="starting" @click="submitStart">{{ t('review.createTask') }}</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>
