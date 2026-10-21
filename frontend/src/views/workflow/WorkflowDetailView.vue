<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchInstance, fetchDefinitions, actOnInstance, urgeInstance } from '@/api/workflows'
import { fetchContract } from '@/api/contracts'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiDetail, useApiMutation } from '@/composables/useApiQuery'
import type { WorkflowInstance, WorkflowDefinition, Contract, ApprovalAction } from '@/types'
import { formatAmount, formatDateTime } from '@/utils/format'
import { translateData } from '@/utils/i18nData'
import { toastSuccess, toastError } from '@/plugins/toast'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import StepFlow from '@/components/ui/StepFlow.vue'
import Timeline from '@/components/ui/Timeline.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Icon from '@/components/ui/Icon.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const route = useRoute()
const router = useRouter()
const instanceId = Number(route.params.id)

// ===== Data layer: TanStack Query =====
// Instance and workflow definition are independent -> fetched in parallel; the contract depends on the instance's contractId -> fetched after the instance arrives
const { data: inst, loading: instLoading, error: instError } = useApiDetail<WorkflowInstance>(
  qk.workflow.detail(instanceId),
  () => fetchInstance(instanceId),
)

const { list: defs } = useApiList(qk.workflow.definitions(), () => fetchDefinitions())

const def = computed<WorkflowDefinition | null>(
  () => defs.value.find((d) => d.id === inst.value?.definitionId) ?? null,
)

const contractId = computed(() => inst.value?.contractId ?? 0)
const { data: contract, loading: contractLoading } = useApiDetail<Contract>(
  computed(() => qk.contracts.detail(contractId.value)),
  () => fetchContract(contractId.value),
  { enabled: computed(() => contractId.value > 0) },
)

const loading = computed(() => instLoading.value || contractLoading.value)

/** Node sequence for visualization (skip start, keep condition nodes) */
const flowNodes = computed(() => {
  if (!def.value) return []
  return def.value.nodes.filter((n) => n.type !== 'start')
})

const timelineItems = computed(() => {
  if (!inst.value) return []
  return [...inst.value.records]
    .reverse()
    .map((r) => ({
      title: translateData(r.nodeName),
      tag: t(`status.approval.${r.action}`) ?? r.action,
      tagTone: r.action === 'approve' || r.action === 'submit' ? ('success' as const)
        : r.action === 'reject' ? ('danger' as const)
        : r.action === 'withdraw' ? ('slate' as const)
        : ('info' as const),
      time: formatDateTime(r.createdAt),
      operator: r.operatorName,
      content: r.comment,
    }))
})

// ===== Approval actions =====
const actionType = ref<ApprovalAction>('approve')
const comment = ref('')
const acting = ref(false)

const actionButtons = computed<Array<{ action: ApprovalAction; label: string; icon: string; variant: 'primary' | 'danger' | 'secondary' }>>(() => [
  { action: 'approve', label: t('status.approval.approve'), icon: 'check', variant: 'primary' },
  { action: 'reject', label: t('status.approval.reject'), icon: 'ban', variant: 'danger' },
  { action: 'return', label: t('status.approval.return'), icon: 'return', variant: 'secondary' },
])

// ===== Mutations: urge / approve =====
const urging = ref(false)

// Only invalidate the affected queries (instance + instance list + contract); no full-page refetch
const actMutation = useApiMutation(
  (payload: { action: ApprovalAction; comment: string; expectedNodeId: string }) =>
    actOnInstance(instanceId, payload.action, payload.comment, payload.expectedNodeId),
  {
    invalidate: [qk.workflow.detail(instanceId), qk.workflow.instances(), qk.contracts.all],
    onSuccess: (_data, payload) => {
      toastSuccess(t('workflow.detail.toastActed', { action: t(`status.approval.${payload.action}`) }))
      comment.value = ''
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('common.operateFailed')),
  },
)

const urgeMutation = useApiMutation((id: number) => urgeInstance(id), {
  invalidate: [qk.workflow.detail(instanceId), qk.workflow.instances()],
  onSuccess: () => {
    const node = translateData(inst.value?.currentNodeName) ?? ''
    toastSuccess(t('workflow.detail.toastUrged', { node }))
  },
  onError: (e) => toastError(e instanceof Error ? e.message : t('workflow.detail.urgeFailed')),
})

async function onUrge() {
  if (!inst.value) return
  urging.value = true
  try {
    await urgeMutation.mutateAsync(inst.value.id)
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('workflow.detail.urgeFailed'))
  } finally {
    urging.value = false
  }
}

async function submitAction() {
  if (!inst.value) return
  if (!comment.value.trim() && actionType.value !== 'approve') {
    toastError(t('workflow.detail.commentRequired'))
    return
  }
  acting.value = true
  try {
    await actMutation.mutateAsync({
      action: actionType.value,
      expectedNodeId: inst.value.currentNodeId,
      comment: comment.value || t('workflow.detail.defaultComment'),
    })
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('common.operateFailed'))
  } finally {
    acting.value = false
  }
}
</script>

<template>
  <div>
    <div v-if="loading || !inst" class="card p-20 text-center">
      <Icon name="refresh" :size="28" class="inline-block animate-spin text-ink-faint" />
    </div>

    <template v-else>
      <PageHeader
        :title="inst.contractTitle"
        :description="t('workflow.detail.instanceLabel', { name: translateData(inst.definitionName), version: inst.definitionVersion, id: inst.id })"
      >
        <template #breadcrumb>
          <router-link to="/workflow" class="hover:text-accent">{{ t('workflow.detail.breadcrumbRoot') }}</router-link>
          <Icon name="chevron-right" :size="12" />
          <span class="text-ink-muted">{{ t('workflow.detail.breadcrumbDetail') }}</span>
        </template>
        <template #actions>
          <BaseButton variant="secondary" icon="arrow-left" @click="router.push('/workflow')">{{ t('workflow.detail.backToList') }}</BaseButton>
        </template>
      </PageHeader>

      <!-- Summary + flow visualization -->
      <BaseCard :title="t('workflow.detail.progressTitle')" class="mb-4">
        <template #actions>
          <StatusBadge kind="workflow" :value="inst.status" />
        </template>

        <!-- Context snapshot -->
        <div class="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg bg-raised border border-line px-4 py-3 text-sm">
          <span class="text-ink-muted">
            {{ t('workflow.detail.starterLabel', { name: '' }) }}<b class="text-ink font-semibold">{{ inst.starterName }}</b>
          </span>
          <span class="text-ink-muted">{{ t('workflow.detail.startedAt', { time: formatDateTime(inst.startedAt) }) }}</span>
          <span v-if="inst.finishedAt" class="text-ink-muted">{{ t('workflow.detail.finishedAt', { time: formatDateTime(inst.finishedAt) }) }}</span>
          <span class="text-ink-muted">
            {{ t('workflow.detail.reviewScore', { score: '' }).trim() }}
            <b class="font-semibold" :class="inst.contextSnapshot.score >= 85 ? 'text-success-700' : 'text-warn-700'">{{ inst.contextSnapshot.score }}</b>
          </span>
          <span class="text-ink-muted">{{ t('workflow.detail.amountLabel', { amount: formatAmount(inst.contextSnapshot.amount) }) }}</span>
          <span class="text-ink-muted">{{ t('workflow.detail.riskSummary', { total: inst.contextSnapshot.riskTotal, high: inst.contextSnapshot.highRisk }) }}</span>
          <router-link v-if="contract" :to="`/contracts/${contract.id}`" class="ml-auto text-xs text-accent hover:underline">{{ t('workflow.detail.viewContract') }}</router-link>
        </div>

        <StepFlow :nodes="flowNodes" :current-node-id="inst.currentNodeId" :status="inst.status" />

        <!-- Approval action area -->
        <div v-if="inst.status === 'running'" class="mt-4 rounded-lg border border-accent-track bg-accent-soft/40 p-4">
          <div class="flex flex-wrap items-center justify-between gap-2 mb-3">
            <p class="text-sm font-semibold text-accent-ink">{{ t('workflow.detail.currentNodePending', { node: translateData(inst.currentNodeName) }) }}</p>
            <button
              class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border border-warn-300 bg-warn-50 text-warn-700 hover:bg-warn-100 transition-colors"
              :disabled="urging"
              @click="onUrge"
            >
              <Icon name="zap" :size="13" /> {{ urging ? t('workflow.detail.urging') : t('workflow.detail.urgeAction') }}
            </button>
          </div>
          <div class="flex flex-wrap gap-2 mb-3">
            <button
              v-for="btn in actionButtons"
              :key="btn.action"
              class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border transition-colors"
              :class="actionType === btn.action
                ? btn.variant === 'primary' ? 'bg-accent text-white border-accent' : btn.variant === 'danger' ? 'bg-danger-600 text-white border-danger-600' : 'bg-ink text-white border-ink'
                : 'bg-white text-ink-muted border-line-control hover:border-accent'"
              @click="actionType = btn.action"
            >
              <Icon :name="btn.icon" :size="13" /> {{ btn.label }}
            </button>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div class="md:col-span-2">
              <label class="label">{{ t('workflow.detail.commentLabel') }}</label>
              <textarea v-model="comment" rows="2" class="input resize-none" :placeholder="t('workflow.detail.commentPlaceholder')" />
            </div>
          </div>

          <div class="mt-3 flex justify-end">
            <BaseButton icon="send" :loading="acting" @click="submitAction">
              {{ t('workflow.detail.confirmPrefix') }}{{ t(`status.approval.${actionType}`) }}
            </BaseButton>
          </div>
        </div>
        <div v-else class="mt-4 rounded-lg border border-line bg-raised p-4 text-sm text-ink-muted">
          {{
            t('workflow.detail.finishedNote', {
              result:
                inst.status === 'approved'
                  ? t('workflow.detail.resultApproved')
                  : inst.status === 'rejected'
                    ? t('workflow.detail.resultRejected')
                    : t('workflow.detail.resultWithdrawn'),
            })
          }}
        </div>
      </BaseCard>

      <!-- Contract info + approval records -->
      <div class="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <BaseCard :title="t('workflow.detail.contractSummary')" v-if="contract">
          <div class="space-y-3 text-sm">
            <div class="flex justify-between"><span class="text-ink-faint">{{ t('workflow.detail.contractNo') }}</span><span class="font-mono text-ink">{{ contract.contractNo }}</span></div>
            <div class="flex justify-between"><span class="text-ink-faint">{{ t('workflow.detail.currentStatus') }}</span><StatusBadge kind="contract" :value="contract.status" /></div>
            <div class="flex justify-between"><span class="text-ink-faint">{{ t('workflow.detail.versionLabel') }}</span><span class="font-mono text-ink">v{{ contract.currentVersion }}</span></div>
            <div class="flex justify-between"><span class="text-ink-faint">{{ t('workflow.detail.counterparty') }}</span><span class="text-ink">{{ contract.counterparty.name }}</span></div>
            <div class="flex justify-between"><span class="text-ink-faint">{{ t('workflow.detail.owner') }}</span><span class="text-ink">{{ contract.ownerName }}</span></div>
          </div>
          <div class="mt-4 pt-4 border-t border-line-rule">
            <p class="text-xs font-medium text-ink-muted mb-2">{{ t('workflow.detail.nodeDesc') }}</p>
            <div class="space-y-1.5">
              <div v-for="n in def?.nodes ?? []" :key="n.id" class="flex items-center gap-2 text-xs">
                <BaseBadge :tone="n.type === 'approval' ? 'primary' : n.type === 'condition' ? 'warn' : n.type === 'cc' ? 'info' : 'slate'">{{ n.type }}</BaseBadge>
                <span class="text-ink-muted">{{ translateData(n.name) }}</span>
              </div>
            </div>
          </div>
        </BaseCard>

        <BaseCard :title="t('workflow.detail.recordsTitle')" :subtitle="t('workflow.detail.recordsSubtitle')" class="xl:col-span-2">
          <Timeline :items="timelineItems" />
        </BaseCard>
      </div>
    </template>
  </div>
</template>
