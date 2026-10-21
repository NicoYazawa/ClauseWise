<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { fetchDefinitions, saveDefinition, toggleDefinition, type DefinitionNodeInput } from '@/api/workflows'
import { qk } from '@/api/queryKeys'
import { useApiList, useApiMutation } from '@/composables/useApiQuery'
import type { WorkflowDefinition, ContractType } from '@/types'
import { contractTypeLabels, formatDateTime } from '@/utils/format'
import { translateData } from '@/utils/i18nData'
import { toastSuccess, toastError } from '@/plugins/toast'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import StepFlow from '@/components/ui/StepFlow.vue'
import Icon from '@/components/ui/Icon.vue'

// ===== Data layer: TanStack Query =====
const { list: defs, loading } = useApiList(qk.workflow.definitions(), () => fetchDefinitions())

const { t } = useI18n()

const typeLabels = computed<Record<string, { label: string; tone: 'primary' | 'warn' | 'info' | 'slate' }>>(() => ({
  start: { label: t('workflow.definitions.typeStart'), tone: 'slate' },
  approval: { label: t('workflow.definitions.typeApproval'), tone: 'primary' },
  condition: { label: t('workflow.definitions.typeCondition'), tone: 'warn' },
  cc: { label: t('workflow.definitions.typeCc'), tone: 'info' },
  end: { label: t('workflow.definitions.typeEnd'), tone: 'slate' },
}))

const signLabels = computed<Record<string, string>>(() => ({
  or: t('workflow.definitions.signOr'),
  and: t('workflow.definitions.signAnd'),
  sequence: t('workflow.definitions.signSequence'),
}))

// ===== Orchestration modal =====
const editOpen = ref(false)
const editing = ref<WorkflowDefinition | null>(null)
const saving = ref(false)
const formName = ref('')
const formTypes = ref<ContractType[]>([])
const allTypes = Object.keys(contractTypeLabels) as ContractType[]

interface DraftNode {
  key: number
  type: 'approval' | 'condition' | 'cc'
  name: string
  signMode: 'or' | 'and' | 'sequence'
  assignees: string
  timeoutHours: string
  riskThreshold: string
  amountWan: string
}

let draftKey = 1
const draftNodes = ref<DraftNode[]>([])

function blankNode(type: DraftNode['type'] = 'approval'): DraftNode {
  return { key: draftKey++, type, name: '', signMode: 'or', assignees: 'role:dept_manager', timeoutHours: '24', riskThreshold: '85', amountWan: '100' }
}

function openCreate() {
  editing.value = null
  formName.value = ''
  formTypes.value = ['other']
  draftNodes.value = [{ ...blankNode('approval'), name: t('workflow.definitions.defaultNodeName') }]
  editOpen.value = true
}

function openEdit(d: WorkflowDefinition) {
  editing.value = d
  formName.value = d.name
  formTypes.value = [...d.contractTypes]
  draftNodes.value = d.nodes
    .filter((n) => !['start', 'end'].includes(n.type))
    .map((n) => {
      const when = n.rules?.[0]?.when ?? ''
      const risk = /risk_score < (\d+)/.exec(when)?.[1] ?? '85'
      const amount = /amount >= (\d+)/.exec(when)?.[1] ?? '1000000'
      return {
        key: draftKey++,
        type: n.type === 'condition' ? 'condition' : n.type === 'cc' ? 'cc' : 'approval',
        name: n.name,
        signMode: n.signMode ?? 'or',
        assignees: (n.assignees ?? []).join(', '),
        timeoutHours: n.timeoutHours ? String(n.timeoutHours) : '',
        riskThreshold: risk,
        amountWan: String(Math.round(Number(amount) / 10000)),
      }
    })
  editOpen.value = true
}

function addNode() {
  draftNodes.value.push(blankNode())
}

function removeNode(key: number) {
  draftNodes.value = draftNodes.value.filter((n) => n.key !== key)
}

function moveNode(idx: number, dir: -1 | 1) {
  const arr = [...draftNodes.value]
  const target = idx + dir
  if (target < 0 || target >= arr.length) return
  ;[arr[idx], arr[target]] = [arr[target], arr[idx]]
  draftNodes.value = arr
}

function toggleType(ct: ContractType) {
  const i = formTypes.value.indexOf(ct)
  if (i >= 0) formTypes.value.splice(i, 1)
  else formTypes.value.push(ct)
}

async function submitSave() {
  if (!formName.value.trim()) {
    toastError(t('workflow.definitions.nameRequired'))
    return
  }
  if (formTypes.value.length === 0) {
    toastError(t('workflow.definitions.typeRequired'))
    return
  }
  for (const n of draftNodes.value) {
    if (!n.name.trim()) {
      toastError(t('workflow.definitions.nodeNameRequired'))
      return
    }
    if (n.type !== 'condition' && !n.assignees.trim()) {
      toastError(t('workflow.definitions.assigneeRequired', { name: n.name }))
      return
    }
  }
  const nodes: DefinitionNodeInput[] = draftNodes.value.map((n, i) => ({
    id: `n${i + 1}`,
    type: n.type,
    name: n.name.trim(),
    signMode: n.signMode,
    assignees: n.assignees.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
    timeoutHours: n.timeoutHours ? Number(n.timeoutHours) : undefined,
    riskThreshold: n.riskThreshold ? Number(n.riskThreshold) : undefined,
    amountThreshold: n.amountWan ? Number(n.amountWan) * 10000 : undefined,
  }))
  saving.value = true
  try {
    await saveMutation.mutateAsync({
      id: editing.value?.id,
      name: formName.value.trim(),
      contractTypes: formTypes.value,
      nodes,
    })
    editOpen.value = false
  } catch (e) {
    toastError(e instanceof Error ? e.message : t('common.saveFailed'))
  } finally {
    saving.value = false
  }
}

const saveMutation = useApiMutation(
  (payload: Parameters<typeof saveDefinition>[0]) => saveDefinition(payload),
  {
    invalidate: qk.workflow.definitions(),
    onSuccess: (d, payload) => {
      toastSuccess(
        payload.id
          ? t('workflow.definitions.toastPublished', { name: d.name, version: d.version })
          : t('workflow.definitions.toastCreated', { name: d.name }),
      )
    },
    onError: (e) => toastError(e instanceof Error ? e.message : t('common.saveFailed')),
  },
)

const toggleMutation = useApiMutation((id: number) => toggleDefinition(id), {
  invalidate: qk.workflow.definitions(),
  onSuccess: (nd) => {
    toastSuccess(
      nd.enabled
        ? t('workflow.definitions.toastEnabled', { name: nd.name })
        : t('workflow.definitions.toastDisabled', { name: nd.name }),
    )
  },
  onError: (e) => toastError(e instanceof Error ? e.message : t('common.operateFailed')),
})

async function onToggle(d: WorkflowDefinition) {
  try {
    await toggleMutation.mutateAsync(d.id)
  } catch {
    /* 错误已由 mutation 的 onError 统一提示，这里仅避免未处理的 Promise 拒绝 */
  }
}
</script>

<template>
  <div>
    <PageHeader
      :title="t('workflow.definitions.title')"
      :description="t('workflow.definitions.description')"
    >
      <template #breadcrumb>
        <router-link to="/workflow" class="hover:text-accent">{{ t('workflow.detail.breadcrumbRoot') }}</router-link>
        <Icon name="chevron-right" :size="12" />
        <span class="text-ink-muted">{{ t('workflow.definitions.title') }}</span>
      </template>
      <template #actions>
        <BaseButton icon="plus" @click="openCreate">{{ t('workflow.definitions.create') }}</BaseButton>
      </template>
    </PageHeader>

    <div v-if="loading" class="card p-20 text-center">
      <Icon name="refresh" :size="28" class="inline-block animate-spin text-ink-faint" />
    </div>

    <div v-else class="space-y-4">
      <BaseCard
        v-for="d in defs"
        :key="d.id"
        :title="d.name"
        :subtitle="t('workflow.definitions.versionMeta', { version: d.version, time: formatDateTime(d.updatedAt) })"
      >
        <template #actions>
          <div class="flex items-center gap-2">
            <BaseBadge :tone="d.enabled ? 'success' : 'slate'">{{ d.enabled ? t('common.enabled') : t('common.disabled') }}</BaseBadge>
            <button class="text-xs text-accent hover:underline" @click="openEdit(d)">{{ t('workflow.definitions.editNewVersion') }}</button>
            <button class="text-xs hover:underline" :class="d.enabled ? 'text-danger-600' : 'text-success-600'" @click="onToggle(d)">
              {{ d.enabled ? t('common.disable') : t('common.enable') }}
            </button>
          </div>
        </template>

        <!-- Applicable types -->
        <div class="mb-4 flex flex-wrap items-center gap-1.5">
          <span class="text-xs text-ink-faint mr-1">{{ t('workflow.definitions.applicableTypes') }}</span>
          <BaseBadge v-for="item in d.contractTypes" :key="item" tone="slate">{{ contractTypeLabels[item] }}</BaseBadge>
        </div>

        <!-- Node-chain visualization -->
        <StepFlow :nodes="d.nodes.filter(n => n.type !== 'start')" current-node-id="" status="approved" />

        <!-- Node details -->
        <div class="mt-4 overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-line text-xs text-ink-faint text-left">
                <th class="py-2 pr-4 font-medium">{{ t('workflow.definitions.colNodeId') }}</th>
                <th class="py-2 pr-4 font-medium">{{ t('common.type') }}</th>
                <th class="py-2 pr-4 font-medium">{{ t('workflow.definitions.colName') }}</th>
                <th class="py-2 pr-4 font-medium">{{ t('workflow.definitions.colSignRule') }}</th>
                <th class="py-2 pr-4 font-medium">{{ t('workflow.definitions.colAssignees') }}</th>
                <th class="py-2 font-medium">{{ t('workflow.definitions.colTimeout') }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-raised">
              <tr v-for="n in d.nodes" :key="n.id" class="text-ink-muted">
                <td class="py-2.5 pr-4 font-mono text-xs">{{ n.id }}</td>
                <td class="py-2.5 pr-4"><BaseBadge :tone="typeLabels[n.type].tone">{{ typeLabels[n.type].label }}</BaseBadge></td>
                <td class="py-2.5 pr-4">{{ translateData(n.name) }}</td>
                <td class="py-2.5 pr-4 text-xs">
                  <span v-if="n.signMode">{{ signLabels[n.signMode] }}</span>
                  <span v-else-if="n.rules" class="font-mono">{{ n.rules.map(r => `${r.when} → ${r.goto}`).join(', ') }}</span>
                  <span v-else class="text-ink-faint">—</span>
                </td>
                <td class="py-2.5 pr-4 text-xs">{{ n.assignees?.join(' / ') ?? '—' }}</td>
                <td class="py-2.5 text-xs">{{ n.timeoutHours ? t('workflow.definitions.hoursLabel', { n: n.timeoutHours }) : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <p class="mt-3 text-xs text-ink-faint">
          {{ t('workflow.definitions.ruleNote') }}
        </p>
      </BaseCard>
    </div>

    <!-- Orchestration modal -->
    <BaseModal
      v-model:open="editOpen"
      :title="editing ? t('workflow.definitions.editModalTitle', { name: editing.name }) : t('workflow.definitions.createModalTitle')"
      width="max-w-3xl"
      @close="editOpen = false"
    >
      <div class="space-y-5">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label class="label">{{ t('workflow.definitions.fieldName') }}</label>
            <input v-model="formName" class="input" :placeholder="t('workflow.definitions.namePlaceholder')" />
          </div>
          <div>
            <label class="label">{{ t('workflow.definitions.fieldTypes') }}</label>
            <div class="flex flex-wrap gap-1.5 pt-1">
              <button
                v-for="item in allTypes"
                :key="item"
                type="button"
                class="px-2.5 py-1 rounded-md text-xs font-medium border transition-colors"
                :class="formTypes.includes(item) ? 'border-accent bg-accent-soft text-accent-ink' : 'border-line text-ink-muted hover:border-accent-track'"
                @click="toggleType(item)"
              >{{ contractTypeLabels[item] }}</button>
            </div>
          </div>
        </div>

        <!-- Node orchestration -->
        <div>
          <div class="flex items-center justify-between mb-2">
            <label class="label mb-0">{{ t('workflow.definitions.nodeDesign') }}</label>
            <button class="inline-flex items-center gap-1 text-xs text-accent hover:underline" @click="addNode">
              <Icon name="plus" :size="12" /> {{ t('workflow.definitions.addNode') }}
            </button>
          </div>
          <div class="space-y-2.5">
            <div v-for="(n, idx) in draftNodes" :key="n.key" class="rounded-lg border border-line p-3.5">
              <div class="flex items-center gap-2">
                <span class="flex h-6 w-6 items-center justify-center rounded-full bg-line-rule text-xs font-mono font-semibold text-ink-muted">{{ idx + 1 }}</span>
                <select v-model="n.type" class="input cursor-pointer !w-28 !py-1 text-xs">
                  <option value="approval">{{ t('workflow.definitions.optionApproval') }}</option>
                  <option value="condition">{{ t('workflow.definitions.optionCondition') }}</option>
                  <option value="cc">{{ t('workflow.definitions.optionCc') }}</option>
                </select>
                <input
                  v-model="n.name"
                  class="input flex-1 !py-1"
                  :placeholder="n.type === 'approval'
                    ? t('workflow.definitions.nodeNameApproval')
                    : n.type === 'condition'
                      ? t('workflow.definitions.nodeNameCondition')
                      : t('workflow.definitions.nodeNameCc')"
                />
                <div class="flex items-center gap-0.5 shrink-0">
                  <button
                    class="p-1 rounded text-ink-faint hover:bg-line-rule hover:text-ink-muted disabled:opacity-30"
                    :disabled="idx === 0"
                    :title="t('workflow.definitions.moveUp')"
                    @click="moveNode(idx, -1)"
                  >
                    <Icon name="chevron-right" :size="14" class="rotate-90" />
                  </button>
                  <button
                    class="p-1 rounded text-ink-faint hover:bg-line-rule hover:text-ink-muted disabled:opacity-30"
                    :disabled="idx === draftNodes.length - 1"
                    :title="t('workflow.definitions.moveDown')"
                    @click="moveNode(idx, 1)"
                  >
                    <Icon name="chevron-down" :size="14" />
                  </button>
                  <button
                    class="p-1 rounded text-ink-faint hover:bg-danger-50 hover:text-danger-600"
                    :title="t('workflow.definitions.deleteNode')"
                    @click="removeNode(n.key)"
                  >
                    <Icon name="trash" :size="14" />
                  </button>
                </div>
              </div>

              <!-- Approval node config -->
              <div v-if="n.type === 'approval'" class="mt-2.5 grid grid-cols-1 md:grid-cols-3 gap-2.5">
                <select v-model="n.signMode" class="input cursor-pointer !py-1 text-xs">
                  <option value="or">{{ t('workflow.definitions.signOr') }}</option>
                  <option value="and">{{ t('workflow.definitions.signAnd') }}</option>
                  <option value="sequence">{{ t('workflow.definitions.signSequence') }}</option>
                </select>
                <div class="md:col-span-2">
                  <input v-model="n.assignees" class="input !py-1 text-xs" :placeholder="t('workflow.definitions.assigneesPlaceholder')" />
                </div>
                <div>
                  <label class="text-[10px] text-ink-faint">{{ t('workflow.definitions.timeoutLabel') }}</label>
                  <input v-model="n.timeoutHours" type="number" min="1" class="input !py-1 text-xs" placeholder="24" />
                </div>
              </div>

              <!-- Condition node config -->
              <div v-else-if="n.type === 'condition'" class="mt-2.5 grid grid-cols-1 md:grid-cols-2 gap-2.5">
                <div>
                  <label class="text-[10px] text-ink-faint">{{ t('workflow.definitions.riskThresholdLabel') }}</label>
                  <input v-model="n.riskThreshold" type="number" min="0" max="100" class="input !py-1 text-xs" placeholder="85" />
                </div>
                <div>
                  <label class="text-[10px] text-ink-faint">{{ t('workflow.definitions.amountThresholdLabel') }}</label>
                  <input v-model="n.amountWan" type="number" min="0" class="input !py-1 text-xs" placeholder="100" />
                </div>
                <p class="md:col-span-2 text-[11px] text-ink-faint leading-relaxed">
                  <span class="font-mono">risk_score &lt; {{ n.riskThreshold || 85 }} or amount &gt;= {{ (Number(n.amountWan) || 0) * 10000 }}</span>
                  {{ t('workflow.definitions.ruleArrow') }}
                </p>
              </div>

              <!-- CC node config -->
              <div v-else class="mt-2.5 grid grid-cols-1 md:grid-cols-2 gap-2.5">
                <div class="md:col-span-2">
                  <input v-model="n.assignees" class="input !py-1 text-xs" :placeholder="t('workflow.definitions.ccPlaceholder')" />
                </div>
              </div>
            </div>
          </div>
          <p v-if="draftNodes.length === 0" class="py-6 text-center text-sm text-ink-faint rounded-lg border border-dashed border-line">
            {{ t('workflow.definitions.noNodes') }}
          </p>
        </div>

        <div class="rounded-md bg-raised border border-line p-3 text-xs text-ink-muted leading-relaxed">
          {{
            editing
              ? t('workflow.definitions.editNote', { next: editing.version + 1, current: editing.version })
              : t('workflow.definitions.createNote')
          }}
        </div>
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="editOpen = false">{{ t('common.cancel') }}</BaseButton>
        <BaseButton icon="check" :loading="saving" @click="submitSave">{{ editing ? t('workflow.definitions.publishNewVersion') : t('workflow.definitions.createSubmit') }}</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>
