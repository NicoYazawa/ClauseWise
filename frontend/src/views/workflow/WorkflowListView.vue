<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fetchInstances, withdrawInstance } from '@/api/workflows'
import { currentUser } from '@/stores/auth'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiMutation } from '@/composables/useApiQuery'
import type { WorkflowInstance } from '@/types'
import { formatDateTime, formatAmount, fromNow } from '@/utils/format'
import { translateData } from '@/utils/i18nData'
import { toastSuccess, toastError } from '@/plugins/toast'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseTabs from '@/components/ui/BaseTabs.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import Icon from '@/components/ui/Icon.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const router = useRouter()

// ===== Data layer: TanStack Query =====
const { list: instances, loading } = useApiList(qk.workflow.instances(), () => fetchInstances())

const tab = ref('todo')
const statusFilter = ref('')

/** Todo: running instances the current user can handle (including legal-countersign nodes) */
const todoList = computed(() =>
  instances.value.filter(
    (i) => i.status === 'running' && ['法务加签', '部门经理审批', '部门主管审批'].includes(i.currentNodeName),
  ),
)
const doneList = computed(() => instances.value.filter((i) => i.status !== 'running' || !todoList.value.includes(i)))
/** Mine: filtered by the current logged-in user's name */
const mineName = currentUser()?.realName ?? ''
const mineList = computed(() => instances.value.filter((i) => i.starterName === mineName))

const list = computed(() => {
  let base = tab.value === 'todo' ? todoList.value : tab.value === 'done' ? doneList.value : mineList.value
  if (statusFilter.value) base = base.filter((i) => i.status === statusFilter.value)
  return base
})

// ===== Withdraw =====
const withdrawTarget = ref<WorkflowInstance | null>(null)
const withdrawReason = ref('')
const withdrawing = ref(false)

const withdrawMutation = useApiMutation(
  (payload: { id: number; reason: string }) => withdrawInstance(payload.id, payload.reason),
  {
    invalidate: qk.workflow.instances(),
    onSuccess: () => {
      toastSuccess(t('workflow.list.toastWithdrawn'))
      withdrawTarget.value = null
      withdrawReason.value = ''
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('workflow.list.withdrawFailed')),
  },
)

async function confirmWithdraw() {
  if (!withdrawTarget.value) return
  if (!withdrawReason.value.trim()) {
    toastError(t('workflow.list.reasonRequired'))
    return
  }
  withdrawing.value = true
  try {
    await withdrawMutation.mutateAsync({ id: withdrawTarget.value.id, reason: withdrawReason.value })
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('workflow.list.withdrawFailed'))
  } finally {
    withdrawing.value = false
  }
}
</script>

<template>
  <div>
    <PageHeader
      :title="t('workflow.list.title')"
      :description="t('workflow.list.description')"
    >
      <template #actions>
        <BaseButton variant="secondary" icon="list" @click="router.push('/workflow/definitions')">{{ t('workflow.list.definitions') }}</BaseButton>
      </template>
    </PageHeader>

    <div class="card">
      <div class="px-4 pt-2">
        <BaseTabs
          v-model="tab"
          :tabs="[
            { key: 'todo', label: t('workflow.list.tabTodo'), count: todoList.length },
            { key: 'done', label: t('workflow.list.tabDone'), count: doneList.length },
            { key: 'mine', label: t('workflow.list.tabMine'), count: mineList.length },
          ]"
        />
      </div>

      <div class="px-4 py-3 flex items-center gap-2">
        <Icon name="filter" :size="14" class="text-ink-faint" />
        <button
          v-for="opt in [
            { value: '', label: t('common.all') },
            { value: 'running', label: t('status.workflow.running') },
            { value: 'approved', label: t('status.workflow.approved') },
            { value: 'rejected', label: t('status.workflow.rejected') },
            { value: 'withdrawn', label: t('status.workflow.withdrawn') },
          ]"
          :key="opt.value"
          class="px-2.5 py-1 rounded-md text-xs font-medium transition-colors"
          :class="statusFilter === opt.value ? 'bg-accent text-white' : 'bg-line-rule text-ink-muted hover:bg-line'"
          @click="statusFilter = opt.value"
        >{{ opt.label }}</button>
      </div>

      <div class="px-4 pb-4 space-y-3">
        <div v-if="loading" class="py-16 text-center">
          <Icon name="refresh" :size="24" class="inline-block animate-spin text-ink-faint" />
        </div>
        <p v-else-if="list.length === 0" class="py-14 text-center text-sm text-ink-faint">{{ t('workflow.list.emptyInstance') }}</p>

        <div
          v-for="inst in list"
          :key="inst.id"
          class="rounded-card border border-line p-4 transition-colors hover:border-accent hover:bg-accent-soft/40 cursor-pointer"
          @click="router.push(`/workflow/${inst.id}`)"
        >
          <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
            <StatusBadge kind="workflow" :value="inst.status" />
            <span class="text-sm font-semibold text-ink">{{ inst.contractTitle }}</span>
            <BaseBadge tone="slate">{{ t('workflow.list.instanceNo', { id: inst.id }) }}</BaseBadge>
            <BaseBadge tone="primary">{{ t('workflow.list.scoreLabel', { score: inst.contextSnapshot.score }) }}</BaseBadge>
            <BaseBadge v-if="inst.contextSnapshot.highRisk > 0" tone="danger">{{ t('workflow.list.highRiskTag', { n: inst.contextSnapshot.highRisk }) }}</BaseBadge>
            <span class="ml-auto text-xs text-ink-faint">{{ fromNow(inst.finishedAt ?? inst.startedAt) }}</span>
          </div>

          <div class="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-ink-muted">
            <span class="flex items-center gap-1"><Icon name="list" :size="12" />{{ translateData(inst.definitionName) }} v{{ inst.definitionVersion }}</span>
            <span class="flex items-center gap-1"><Icon name="user" :size="12" />{{ t('workflow.list.starterLabel', { name: inst.starterName }) }}</span>
            <span v-if="inst.status === 'running'" class="flex items-center gap-1 text-warn-600">
              <Icon name="clock" :size="12" />{{ t('workflow.list.currentNode', { node: translateData(inst.currentNodeName) }) }}
            </span>
            <span v-else class="flex items-center gap-1"><Icon name="clock" :size="12" />{{ t('workflow.list.finishedAt', { time: formatDateTime(inst.finishedAt) }) }}</span>
            <span class="flex items-center gap-1"><Icon name="scale" :size="12" />{{ t('workflow.list.amountLabel', { amount: formatAmount(inst.contextSnapshot.amount) }) }}</span>
            <span class="flex items-center gap-1"><Icon name="alert-triangle" :size="12" />{{ t('workflow.list.riskCount', { n: inst.contextSnapshot.riskTotal }) }}</span>
          </div>

          <div v-if="tab === 'mine' && inst.status === 'running'" class="mt-3 pt-3 border-t border-line-rule" @click.stop>
            <BaseButton size="sm" variant="secondary" icon="rotate-ccw" @click="withdrawTarget = inst">{{ t('workflow.list.withdrawAction') }}</BaseButton>
          </div>
        </div>
      </div>
    </div>

    <!-- Withdraw confirmation -->
    <BaseModal :open="!!withdrawTarget" :title="t('workflow.list.withdrawAction')" @close="withdrawTarget = null">
      <p class="text-sm text-ink-muted leading-relaxed">
        {{ t('workflow.list.withdrawConfirm', { title: withdrawTarget?.contractTitle }) }}
      </p>
      <div class="mt-4">
        <label class="label">{{ t('workflow.list.withdrawReasonLabel') }}</label>
        <textarea v-model="withdrawReason" rows="3" class="input resize-none" :placeholder="t('workflow.list.withdrawReasonPlaceholder')" />
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="withdrawTarget = null">{{ t('common.cancel') }}</BaseButton>
        <BaseButton variant="danger" icon="rotate-ccw" :loading="withdrawing" @click="confirmWithdraw">{{ t('workflow.list.confirmWithdraw') }}</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>
